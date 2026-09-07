"""``POST /api/runs`` 端到端（issue #52）：真库 + 假 ``ModelPort``，走 ASGI 传输。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from chat_agents import main as main_module
from chat_agents.agent.runner import AgentRunner
from chat_agents.agent.tool_executor import ToolExecutor
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.db.obs import Run, Span
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, Usage
from chat_agents.llm.events import TextDelta as ModelTextDelta
from chat_agents.llm.message import ModelMessage, TextBlock
from sqlalchemy import select

from .db_helpers import migrated_engine, session_factory_for


class _ScriptedPort:
    """脚本化上游；记下每次调用收到的模型与档案（issue #82 的主要观察点）。"""

    def __init__(self, turns: list[list[ModelEvent]]) -> None:
        self._turns = turns
        self.calls = 0
        self.models: list[str] = []
        self.profiles: list[Any] = []

    async def stream(
        self,
        *,
        messages: Any,
        tools: Any,
        model: str,
        effort: EffortTier,
        profile: Any,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ModelEvent]:
        turn = self._turns[self.calls]
        self.calls += 1
        self.models.append(model)
        self.profiles.append(profile)
        for event in turn:
            yield event


def _completed(text: str) -> ModelCallCompleted:
    return ModelCallCompleted(
        message=ModelMessage(role="assistant", content=(TextBlock(text=text),)),
        usage=Usage(state="complete", input_tokens=1, output_tokens=1, reasoning_tokens=None),
        stop_reason="stop",
    )


async def _parse_sse(response: httpx.Response) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    buffer = ""
    async for chunk in response.aiter_text():
        buffer += chunk
    for block in buffer.replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            frames.append(json.loads(block[len("data:") :].strip()))
    return frames


class _RaisingPort:
    """上游当场抛错——用来跑失败路径（错误跨度是密钥最可能泄漏的地方）。"""

    def __init__(self) -> None:
        self.models: list[str] = []
        self.profiles: list[Any] = []

    async def stream(
        self,
        *,
        messages: Any,
        tools: Any,
        model: str,
        effort: EffortTier,
        profile: Any,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ModelEvent]:
        self.models.append(model)
        self.profiles.append(profile)
        raise RuntimeError("上游拒绝了这次调用")
        yield  # pragma: no cover - 让本函数成为异步生成器


async def _run(port: Any, body: dict[str, Any]) -> list[dict[str, Any]]:
    """打一次 ``POST /api/runs`` 并收完整个 SSE 流；调用方负责建好数据库。"""

    fake_runner = AgentRunner(tool_executor=ToolExecutor({}), model_port_factory=lambda _p: port)
    main_module.app.dependency_overrides[main_module.get_agent_runner] = lambda: fake_runner
    try:
        transport = httpx.ASGITransport(app=main_module.app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream("POST", "/api/runs", json=body) as response,
        ):
            assert response.status_code == 200
            return await _parse_sse(response)
    finally:
        main_module.app.dependency_overrides.pop(main_module.get_agent_runner, None)


@pytest.mark.db
def test_post_api_runs_streams_sse_and_persists_incrementally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_e2e") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            port = _ScriptedPort(
                [
                    [_completed("测试标题")],
                    [ModelTextDelta(text="你好"), _completed("你好")],
                ]
            )
            fake_runner = AgentRunner(
                tool_executor=ToolExecutor({}), model_port_factory=lambda _profile: port
            )
            main_module.app.dependency_overrides[main_module.get_agent_runner] = lambda: fake_runner

            session_id = uuid4()
            try:
                transport = httpx.ASGITransport(app=main_module.app)
                async with (
                    httpx.AsyncClient(transport=transport, base_url="http://test") as client,
                    client.stream(
                        "POST",
                        "/api/runs",
                        json={"session_id": str(session_id), "message": "嗨"},
                    ) as response,
                ):
                    assert response.status_code == 200
                    frames = await _parse_sse(response)
            finally:
                main_module.app.dependency_overrides.pop(main_module.get_agent_runner, None)

            types = [f["type"] for f in frames]
            assert types[0] == "RUN_STARTED"
            assert "RUN_FINISHED" in types
            assert "RUN_ERROR" not in types
            assert "TEXT_MESSAGE_CONTENT" in types
            assert port.calls == 2

            async with factory() as session:
                repository = ConversationRepository(session)
                rows = await repository.list_messages(session_id)
                # user 消息 + 一条助手消息
                assert [row.role for row in rows] == ["user", "assistant"]

                run = (
                    await session.execute(select(Run).where(Run.session_id == session_id))
                ).scalar_one()
                assert run.status == "completed"

    asyncio.run(scenario())


@pytest.mark.db
def test_model_override_reaches_upstream_and_the_span_records_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """issue #82 的主场景：不填任何密钥、只换模型标识，那一轮就得真用它。

    这条同时守住「跨度模型 == 调用模型」——两者一旦分叉，跨度就开始撒谎，而
    ``close_span`` 不写模型列，此后没有纠正点。
    """

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_override") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            port = _ScriptedPort([[_completed("标题")], [_completed("你好")]])
            frames = await _run(
                port,
                {
                    "session_id": str(uuid4()),
                    "message": "嗨",
                    "model_override": {"main_model": "claude-opus-5"},
                },
            )

            # 两次调用（auxiliary 标题 + main）都用覆盖后的标识：auxiliary 未指定，
            # 跟随的是覆盖后的 main，而不是 endpoints.yaml 里那个。
            assert port.models == ["claude-opus-5", "claude-opus-5"]
            # 密钥与 base URL 仍来自服务端预设档案——用户一个字都没填。
            assert port.profiles[0].api_key.get_secret_value() == "server-key"
            assert port.profiles[0].base_url == "https://api.anthropic.com"

            usage_models = {
                frame["value"]["model"]
                for frame in frames
                if frame.get("name") == "chatagents.usage"
            }
            assert usage_models == {"claude-opus-5"}

            async with factory() as session:
                spans = (await session.execute(select(Span))).scalars().all()
                assert {span.model for span in spans} == {"claude-opus-5"}

    asyncio.run(scenario())


@pytest.mark.db
def test_custom_endpoint_override_switches_base_url_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BYOK：请求真的打用户的中转站，服务端密钥一个字段都不参与。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_byok") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            port = _ScriptedPort([[_completed("标题")], [_completed("你好")]])
            await _run(
                port,
                {
                    "session_id": str(uuid4()),
                    "message": "嗨",
                    "model_override": {
                        "protocol": "openai_chat_completions",
                        "base_url": "https://relay.example.com/v1",
                        "auth_field": "Authorization",
                        "api_key": "sk-user",
                        "main_model": "gpt-luna",
                    },
                },
            )

            profile = port.profiles[0]
            assert profile.base_url == "https://relay.example.com/v1"
            assert profile.protocol == "openai_chat_completions"
            assert profile.api_key.get_secret_value() == "sk-user"
            assert port.models == ["gpt-luna", "gpt-luna"]

    asyncio.run(scenario())


@pytest.mark.db
def test_no_override_still_uses_the_server_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    """不传覆盖时行为与本次改动之前完全一致。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_preset") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            port = _ScriptedPort([[_completed("标题")], [_completed("你好")]])
            await _run(port, {"session_id": str(uuid4()), "message": "嗨"})

            assert port.models == ["claude-sonnet-5", "claude-sonnet-5"]
            assert port.profiles[0].base_url == "https://api.anthropic.com"

    asyncio.run(scenario())


@pytest.mark.db
def test_each_run_records_its_own_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一会话里逐轮换模型，每轮的跨度各自记录当轮的那个。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_per_run") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            session_id = uuid4()
            # 第一轮生成标题（两次调用），第二轮只有主调用。
            first = _ScriptedPort([[_completed("标题")], [_completed("甲")]])
            await _run(
                first,
                {
                    "session_id": str(session_id),
                    "message": "第一问",
                    "model_override": {"main_model": "model-a"},
                },
            )
            second = _ScriptedPort([[_completed("乙")]])
            await _run(
                second,
                {
                    "session_id": str(session_id),
                    "message": "第二问",
                    "model_override": {"main_model": "model-b"},
                },
            )

            async with factory() as session:
                spans = (
                    (await session.execute(select(Span).where(Span.name == "model_call")))
                    .scalars()
                    .all()
                )
                assert {span.model for span in spans} == {"model-a", "model-b"}

    asyncio.run(scenario())


@pytest.mark.db
def test_auxiliary_fallback_is_recorded_on_the_title_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0014：auxiliary 回落必须留痕，否则用户会以为用的是自己填的那个。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_aux") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            fallback_port = _ScriptedPort([[_completed("标题")], [_completed("你好")]])
            await _run(
                fallback_port,
                {
                    "session_id": str(uuid4()),
                    "message": "嗨",
                    "model_override": {"main_model": "model-a"},
                },
            )

            async with factory() as session:
                title_span = (
                    await session.execute(select(Span).where(Span.name == "title_generation"))
                ).scalar_one()
                assert title_span.attributes["auxiliary_model_source"] == "fallback_to_main"
                assert title_span.model == "model-a"

            aux_port = _ScriptedPort([[_completed("标题")], [_completed("你好")]])
            await _run(
                aux_port,
                {
                    "session_id": str(uuid4()),
                    "message": "嗨",
                    "model_override": {"main_model": "model-a", "auxiliary_model": "model-aux"},
                },
            )
            assert aux_port.models[0] == "model-aux"

            async with factory() as session:
                title_spans = (
                    (await session.execute(select(Span).where(Span.name == "title_generation")))
                    .scalars()
                    .all()
                )
                sources = {span.attributes["auxiliary_model_source"] for span in title_spans}
                assert sources == {"fallback_to_main", "specified"}

    asyncio.run(scenario())


@pytest.mark.db
def test_no_span_attribute_ever_carries_the_user_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0029 的卫生要求：密钥不出现在跨度属性里，失败态也不例外。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_secret") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            override = {
                "base_url": "https://relay.example.com/v1",
                "api_key": "sk-user-secret",
                "main_model": "gpt-luna",
            }
            await _run(
                _ScriptedPort([[_completed("标题")], [_completed("你好")]]),
                {"session_id": str(uuid4()), "message": "嗨", "model_override": override},
            )
            # 失败路径单独跑一遍——泄漏最可能发生在错误跨度里。
            await _run(
                _RaisingPort(),
                {"session_id": str(uuid4()), "message": "嗨", "model_override": override},
            )

            async with factory() as session:
                spans = (await session.execute(select(Span))).scalars().all()
                assert spans
                for span in spans:
                    assert "sk-user-secret" not in json.dumps(span.attributes or {})

    asyncio.run(scenario())


def test_post_api_runs_rejects_an_incomplete_custom_endpoint() -> None:
    """自定义端点缺密钥是 400 而不是静默忽略——静默忽略正是本票要修的失效。"""

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/runs",
                json={
                    "session_id": str(uuid4()),
                    "message": "嗨",
                    "model_override": {"base_url": "https://relay.example.com/v1"},
                },
            )
        assert response.status_code == 400
        assert response.json()["type"] == "protocol_error"

    asyncio.run(scenario())


# 断连场景（生成器被 aclose() 掐断 -> aborted/partial）已经在
# tests/conversation/test_streaming.py 与 tests/observability/test_streaming.py
# 用真实取消直接覆盖。httpx 的 ``ASGITransport`` 是进程内调用、不建立真实
# 连接，客户端提前退出并不会像真实网络那样触发 ASGI ``http.disconnect``，在
# 这一层伪造断连只会得到一次「假阳性」的假 SlowPort 超时，因此不在这里重复。


def test_openapi_carries_the_three_custom_payload_schemas_snake_case() -> None:
    """ADR-0021：三个 Custom 载荷即使没有路径引用，也要进 components.schemas，且是 snake_case。"""

    schema = main_module.app.openapi()
    schemas = schema["components"]["schemas"]
    for name in ("ChatAgentsUsagePayload", "ChatAgentsSpanPayload", "ChatAgentsToolResultPayload"):
        assert name in schemas
        for field_name in schemas[name]["properties"]:
            assert field_name == field_name.lower()
            assert "-" not in field_name


def test_post_api_runs_rejects_blank_message_before_streaming() -> None:
    """流开始前的失败走状态码——空消息不应该产出任何 SSE 帧。"""

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/runs", json={"session_id": str(uuid4()), "message": "   "}
            )
        assert response.status_code == 400
        body = response.json()
        assert body["type"] == "protocol_error"

    asyncio.run(scenario())
