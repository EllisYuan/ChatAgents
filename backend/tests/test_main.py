"""标题生成的独立 HTTP 契约（issue #93，ADR-0036）：真库 + 假 ``ModelPort``，走 ASGI 传输。

标题不再属于主运行（``POST /api/runs``）：主运行不认领、不调用、不投递标题，
它的 SSE 里没有 ``chatagents.title``、没有 auxiliary 用量或跨度。标题改为会话级
的独立调用 ``POST /api/sessions/{session_id}/title``——本模块用真 PostgreSQL 和
可控 ``ModelPort`` 覆盖它的成功、失败、交错完成、重复调用、人工改名保护、密钥
卫生，以及「主运行统计不含标题」这条分离约束。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from chat_agents import main as main_module
from chat_agents.agent.runner import AgentRunner
from chat_agents.agent.tool_executor import ToolExecutor
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.conversation.service import ConversationService
from chat_agents.db.app import Message as MessageRow
from chat_agents.db.app import Session as SessionRow
from chat_agents.db.obs import Run, Span
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, Usage
from chat_agents.llm.events import TextDelta as ModelTextDelta
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.observability.repository import ObservabilityRepository
from sqlalchemy import select

from .db_helpers import migrated_engine, session_factory_for

_SEED_TEXT = "首条用户消息"


class _ScriptedPort:
    """脚本化上游；逐次记录到达模型的参数，是最主要的观察点。

    ``error`` 让一次调用当场抛错（跑失败路径）；``on_call`` 在产出事件前执行一次
    副作用——用来把「人工改名发生在模型调用期间」这类交错做成确定性的，而不是靠
    真实时间竞速。
    """

    def __init__(
        self,
        turns: list[list[ModelEvent]] | None = None,
        *,
        error: bool = False,
        on_call: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._turns = turns or []
        self._error = error
        self._on_call = on_call
        self.calls = 0
        self.models: list[str] = []
        self.efforts: list[EffortTier] = []
        self.profiles: list[Any] = []
        self.messages: list[list[ModelMessage]] = []
        self.tools: list[list[Any]] = []
        self.system_prompts: list[str | None] = []

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
        if self._error:
            raise RuntimeError("上游拒绝了这次调用")
        turn = self._turns[self.calls]
        self.calls += 1
        self.models.append(model)
        self.efforts.append(effort)
        self.profiles.append(profile)
        self.messages.append(list(messages))
        self.tools.append(list(tools))
        self.system_prompts.append(system_prompt)
        if self._on_call is not None:
            await self._on_call(model)
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


def _override_runner(port: _ScriptedPort) -> None:
    runner = AgentRunner(tool_executor=ToolExecutor({}), model_port_factory=lambda _p: port)
    main_module.app.dependency_overrides[main_module.get_agent_runner] = lambda: runner


async def _run(port: _ScriptedPort, body: dict[str, Any]) -> list[dict[str, Any]]:
    """打一次 ``POST /api/runs`` 并收完整个 SSE 流；调用方负责建好数据库。"""

    _override_runner(port)
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


async def _post_title(
    client: httpx.AsyncClient,
    session_id: UUID,
    port: _ScriptedPort,
    *,
    model_override: dict[str, Any] | None = None,
) -> httpx.Response:
    """打一次独立标题调用，并把它绑到给定的可控端口上。"""

    main_module.app.dependency_overrides[main_module.get_title_model_port_factory] = lambda: (
        lambda _profile: port
    )
    try:
        body: dict[str, Any] = {}
        if model_override is not None:
            body["model_override"] = model_override
        return await client.post(f"/api/sessions/{session_id}/title", json=body)
    finally:
        main_module.app.dependency_overrides.pop(main_module.get_title_model_port_factory, None)


async def _seed_first_message(factory: Any, *, text: str = _SEED_TEXT) -> UUID:
    """直接建一个随首条用户消息诞生的会话（fallback 已写），不经过主运行。"""

    session_id = uuid4()
    async with factory() as session, session.begin():
        _, candidate = await ConversationService(session).append_user_message_with_title_candidate(
            session_id=session_id, message_id=uuid4(), text=text
        )
        assert candidate
    return session_id


def _usage_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [frame for frame in frames if frame.get("name") == "chatagents.usage"]


@pytest.mark.db
def test_post_api_runs_streams_sse_and_persists_incrementally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_e2e") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            session_id = uuid4()
            port = _ScriptedPort([[ModelTextDelta(text="你好"), _completed("你好")]])
            frames = await _run(port, {"session_id": str(session_id), "message": "嗨"})

            types = [f["type"] for f in frames]
            assert types[0] == "RUN_STARTED"
            assert "RUN_FINISHED" in types
            assert "RUN_ERROR" not in types
            assert "TEXT_MESSAGE_CONTENT" in types
            # 主运行只调用了一次主模型——它不再发起标题调用（issue #93）。
            assert port.calls == 1

            async with factory() as session:
                repository = ConversationRepository(session)
                rows = await repository.list_messages(session_id)
                assert [row.role for row in rows] == ["user", "assistant"]

                run = (
                    await session.execute(select(Run).where(Run.session_id == session_id))
                ).scalar_one()
                assert run.status == "completed"

    asyncio.run(scenario())


@pytest.mark.db
def test_main_run_never_emits_title_data_or_waits_for_the_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主运行正常完成不等待标题：SSE、用量、跨度、统计都只反映主处理。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_no_title") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            session_id = uuid4()
            port = _ScriptedPort([[_completed("你好")]])
            frames = await _run(port, {"session_id": str(session_id), "message": "嗨"})

            # 主事件流不含标题事件、不含 auxiliary 用量或标题跨度。
            assert not any(frame.get("name") == "chatagents.title" for frame in frames)
            assert {frame["value"]["role"] for frame in _usage_frames(frames)} == {"main"}

            async with factory() as session:
                span_names = (await session.execute(select(Span.name))).scalars().all()
                assert "title_generation" not in span_names
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                # 主运行不认领、不落标题：fallback（=首条消息）保持原样（ADR-0037/0036）。
                assert row.title == "嗨"
                assert row.title_generation_claimed_at is None
                assert row.title_generation_outcome is None

    asyncio.run(scenario())


@pytest.mark.db
def test_title_endpoint_calls_the_auxiliary_model_and_applies_the_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """标题 endpoint：真 HTTP，固定 low，素材只来自服务端保存的首条用户消息。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_apply") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)

            port = _ScriptedPort([[_completed("生成的标题")]])
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(client, session_id, port)

            assert response.status_code == 200
            body = response.json()
            assert body == {
                "session_id": str(session_id),
                "title": "生成的标题",
                "status": "applied",
            }

            # 调用确实发生了，且素材、无工具、固定 low、系统提示词都合规。
            assert port.calls == 1
            assert port.efforts == ["low"]
            assert port.tools == [[]]
            assert port.messages == [
                [ModelMessage(role="user", content=(TextBlock(text=_SEED_TEXT),))]
            ]
            assert port.system_prompts[0]

            async with factory() as session:
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title == "生成的标题"
                assert row.title_generation_outcome == "applied"
                assert row.title_generation_eligible is False
                messages = await ConversationRepository(session).list_messages(session_id)
                # auxiliary 输出永不写消息表（ADR-0012）。
                assert [m.role for m in messages] == ["user"]
                span = (
                    await session.execute(select(Span).where(Span.name == "title_generation"))
                ).scalar_one()
                assert span.run_id is None
                assert span.session_id == session_id
                assert span.parent_span_id is None
                assert span.role == "auxiliary"
                assert span.status == "ok"
                assert span.usage_status == "complete"
                assert span.input_tokens == 1
                assert span.output_tokens == 1
                assert span.attributes["application_result"] == "applied"

    asyncio.run(scenario())


@pytest.mark.db
def test_title_endpoint_failure_keeps_fallback_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上游失败保留 fallback、记录失败原因，且不重开资格——重复 POST 不再调模型。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_failure") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)

            failing = _ScriptedPort(error=True)
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(client, session_id, failing)
                assert response.json() == {
                    "session_id": str(session_id),
                    "title": _SEED_TEXT,
                    "status": "fallback",
                }
                assert failing.calls == 0  # 抛错发生在产出事件之前，计数保持 0

                # 重复 POST 返回持久化状态，不再调用模型、不重试。
                repeat_port = _ScriptedPort([[_completed("不该被调用")]])
                repeat = await _post_title(client, session_id, repeat_port)
                assert repeat.json()["status"] == "fallback"
                assert repeat.json()["title"] == _SEED_TEXT
                assert repeat_port.calls == 0

            async with factory() as session:
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title == _SEED_TEXT
                assert row.title_generation_outcome == "fallback"
                assert row.title_generation_eligible is False
                span = (
                    await session.execute(select(Span).where(Span.name == "title_generation"))
                ).scalar_one()
                assert span.status == "error"
                assert span.usage_status == "unavailable"
                assert span.input_tokens is None
                assert span.output_tokens is None
                assert span.attributes["failure_reason"] == "upstream"
                assert "application_result" not in span.attributes

    asyncio.run(scenario())


@pytest.mark.db
@pytest.mark.parametrize(
    ("events", "reason"),
    [([], "missing_terminal"), ([_completed("  ")], "empty_output")],
)
def test_title_endpoint_incomplete_output_keeps_fallback(
    monkeypatch: pytest.MonkeyPatch, events: list[ModelEvent], reason: str
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine(f"chat_agents_title_{reason}") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)
            port = _ScriptedPort([events])
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(client, session_id, port)
            assert response.status_code == 200
            assert response.json()["status"] == "fallback"
            assert response.json()["title"] == _SEED_TEXT
            assert port.calls == 1
            async with factory() as session:
                observation = await ObservabilityRepository(session).get_title_generation(
                    session_id
                )
                assert len(observation.spans) == 1
                assert observation.spans[0].failure_reason == reason
                assert observation.spans[0].status == "error"
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title_generation_outcome == "fallback"

    asyncio.run(scenario())


@pytest.mark.db
def test_title_endpoint_times_out_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")
    monkeypatch.setattr(main_module, "_TITLE_TIMEOUT_SECONDS", 0.01)

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_timeout") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)
            cancelled = asyncio.Event()

            class SlowPort:
                calls = 0

                async def stream(self, **kwargs: Any) -> AsyncIterator[ModelEvent]:
                    self.calls += 1
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        raise
                    yield _completed("不该产出")

            port = SlowPort()
            main_module.app.dependency_overrides[main_module.get_title_model_port_factory] = (
                lambda: lambda _profile: port
            )
            try:
                transport = httpx.ASGITransport(app=main_module.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(f"/api/sessions/{session_id}/title", json={})
                    repeat = await client.post(f"/api/sessions/{session_id}/title", json={})
                assert response.status_code == 200
                assert response.json()["status"] == "fallback"
                assert repeat.json()["status"] == "fallback"
                assert port.calls == 1
                assert cancelled.is_set()
            finally:
                main_module.app.dependency_overrides.pop(
                    main_module.get_title_model_port_factory, None
                )
            async with factory() as session:
                observation = await ObservabilityRepository(session).get_title_generation(
                    session_id
                )
                assert observation.spans[0].failure_reason == "timeout"
                assert observation.spans[0].usage_status == "unavailable"
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title_generation_outcome == "fallback"

    asyncio.run(scenario())


@pytest.mark.db
def test_title_endpoint_reports_manual_not_applied_when_renamed_during_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """人工改名发生在模型调用期间：模型照跑，迟到结果不应用，也不重开资格。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_interleave") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)

            async def rename_during_call(_model: str) -> None:
                async with factory() as session, session.begin():
                    await ConversationService(session).rename_session(session_id, "人工标题")

            port = _ScriptedPort([[_completed("迟到的模型标题")]], on_call=rename_during_call)
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(client, session_id, port)

            assert response.status_code == 200
            assert response.json() == {
                "session_id": str(session_id),
                "title": "人工标题",
                "status": "manual_not_applied",
            }
            assert port.calls == 1  # 模型确实跑完了

            async with factory() as session:
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title == "人工标题"
                assert row.title_generation_outcome == "manual_not_applied"
                assert row.title_generation_eligible is False
                span = (
                    await session.execute(select(Span).where(Span.name == "title_generation"))
                ).scalar_one()
                assert span.status == "ok"
                assert span.usage_status == "complete"
                assert span.attributes["application_result"] == "manual_not_applied"
                assert "failure_reason" not in span.attributes

    asyncio.run(scenario())


@pytest.mark.db
def test_title_endpoint_skips_the_model_when_renamed_before_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """调用前人工改名：直接跳过模型，报告已处理，不产生任何标题跨度。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_pre_rename") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)
            async with factory() as session, session.begin():
                await ConversationService(session).rename_session(session_id, "人工标题")

            port = _ScriptedPort([[_completed("不该被调用")]])
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(client, session_id, port)

            assert response.json() == {
                "session_id": str(session_id),
                "title": "人工标题",
                "status": "processed",
            }
            assert port.calls == 0

            async with factory() as session:
                spans = (await session.execute(select(Span))).scalars().all()
                assert spans == []

    asyncio.run(scenario())


@pytest.mark.db
def test_title_endpoint_reports_generating_for_an_in_flight_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已认领但未终态：报告 generating，不重复调用模型、不等待原调用。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_generating") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)
            async with factory() as session, session.begin():
                assert await ConversationService(session).claim_title_generation(session_id)

            port = _ScriptedPort([[_completed("不该被调用")]])
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(client, session_id, port)

            assert response.json() == {
                "session_id": str(session_id),
                "title": _SEED_TEXT,
                "status": "generating",
            }
            assert port.calls == 0

    asyncio.run(scenario())


@pytest.mark.db
def test_title_endpoint_404_for_an_unknown_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_missing") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            port = _ScriptedPort([[_completed("不该被调用")]])
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(client, uuid4(), port)

            assert response.status_code == 404
            assert response.json()["type"] == "session_not_found"
            assert port.calls == 0

    asyncio.run(scenario())


@pytest.mark.db
def test_main_run_model_override_reaches_upstream_and_the_span_records_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """issue #82：不填任何密钥、只换模型标识，那一轮就得真用它。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_override") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            port = _ScriptedPort([[_completed("你好")]])
            frames = await _run(
                port,
                {
                    "session_id": str(uuid4()),
                    "message": "嗨",
                    "model_override": {"main_model": "claude-opus-5"},
                },
            )

            assert port.models == ["claude-opus-5"]
            # 密钥与 base URL 仍来自服务端预设档案——用户一个字都没填。
            assert port.profiles[0].api_key.get_secret_value() == "server-key"
            assert port.profiles[0].base_url == "https://api.anthropic.com"

            usage_models = {frame["value"]["model"] for frame in _usage_frames(frames)}
            assert usage_models == {"claude-opus-5"}

            async with factory() as session:
                spans = (await session.execute(select(Span))).scalars().all()
                assert {span.model for span in spans} == {"claude-opus-5"}

    asyncio.run(scenario())


@pytest.mark.db
def test_custom_endpoint_override_switches_base_url_and_key_on_the_title_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BYOK：标题调用真的打用户的中转站，服务端密钥一个字段都不参与。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_byok") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)

            port = _ScriptedPort([[_completed("标题")]])
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await _post_title(
                    client,
                    session_id,
                    port,
                    model_override={
                        "protocol": "openai_chat_completions",
                        "base_url": "https://relay.example.com/v1",
                        "auth_field": "Authorization",
                        "api_key": "sk-user",
                        "main_model": "gpt-luna",
                    },
                )

            assert response.status_code == 200
            profile = port.profiles[0]
            assert profile.base_url == "https://relay.example.com/v1"
            assert profile.protocol == "openai_chat_completions"
            assert profile.api_key.get_secret_value() == "sk-user"
            # auxiliary 未指定，跟随覆盖后的 main。
            assert port.models == ["gpt-luna"]

    asyncio.run(scenario())


@pytest.mark.db
def test_title_without_override_uses_the_server_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不传覆盖时标题走上服务端预设的 auxiliary 模型与密钥。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_preset") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = await _seed_first_message(factory)

            port = _ScriptedPort([[_completed("标题")]])
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await _post_title(client, session_id, port)

            assert port.models == ["claude-sonnet-5"]
            assert port.profiles[0].base_url == "https://api.anthropic.com"

    asyncio.run(scenario())


@pytest.mark.db
def test_each_run_records_its_own_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一会话里逐轮换模型，每轮的主跨度各自记录当轮的那个。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_main_per_run") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            session_id = uuid4()
            await _run(
                _ScriptedPort([[_completed("甲")]]),
                {
                    "session_id": str(session_id),
                    "message": "第一问",
                    "model_override": {"main_model": "model-a"},
                },
            )
            await _run(
                _ScriptedPort([[_completed("乙")]]),
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
def test_auxiliary_model_selection_is_recorded_on_the_title_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0014：auxiliary 的选定与回落都要在标题跨度上留痕。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_aux") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                fallback_session = await _seed_first_message(factory)
                fallback_port = _ScriptedPort([[_completed("标题")]])
                await _post_title(
                    client,
                    fallback_session,
                    fallback_port,
                    model_override={"main_model": "model-a"},
                )
                assert fallback_port.models == ["model-a"]  # 回落跟随覆盖后的 main

                specified_session = await _seed_first_message(factory)
                specified_port = _ScriptedPort([[_completed("标题")]])
                await _post_title(
                    client,
                    specified_session,
                    specified_port,
                    model_override={"main_model": "model-a", "auxiliary_model": "model-aux"},
                )
                assert specified_port.models == ["model-aux"]

            async with factory() as session:
                spans = (
                    (await session.execute(select(Span).where(Span.name == "title_generation")))
                    .scalars()
                    .all()
                )
                assert {span.model for span in spans} == {"model-a", "model-aux"}
                assert {span.attributes["auxiliary_model_source"] for span in spans} == {
                    "fallback_to_main",
                    "specified",
                }

    asyncio.run(scenario())


@pytest.mark.db
def test_no_persisted_fact_or_span_attribute_carries_the_user_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0029 的卫生要求：密钥不进业务数据、不进跨度属性，失败态也不例外。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_secret") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            override = {
                "base_url": "https://relay.example.com/v1",
                "api_key": "sk-user-secret",
                "main_model": "gpt-luna",
            }
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                success = await _seed_first_message(factory)
                await _post_title(
                    client, success, _ScriptedPort([[_completed("标题")]]), model_override=override
                )
                # 失败路径单独跑一遍——泄漏最可能发生在错误跨度里。
                failure = await _seed_first_message(factory)
                await _post_title(
                    client, failure, _ScriptedPort(error=True), model_override=override
                )

            async with factory() as session:
                spans = (await session.execute(select(Span))).scalars().all()
                assert spans
                assert "sk-user-secret" not in json.dumps([span.attributes or {} for span in spans])
                for entity in (SessionRow, MessageRow):
                    rows = (await session.execute(select(entity.__table__))).mappings().all()
                    assert "sk-user-secret" not in json.dumps(
                        [dict(row) for row in rows], default=str
                    )

    asyncio.run(scenario())


@pytest.mark.db
def test_key_source_is_recorded_on_the_title_span(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0029：标题跨度记录密钥来源，不记录密钥值。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_key_source") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                preset = await _seed_first_message(factory)
                await _post_title(client, preset, _ScriptedPort([[_completed("标题")]]))

                byok = await _seed_first_message(factory)
                await _post_title(
                    client,
                    byok,
                    _ScriptedPort([[_completed("标题")]]),
                    model_override={
                        "base_url": "https://relay.example.com/v1",
                        "api_key": "sk-user",
                        "main_model": "gpt-luna",
                    },
                )

            async with factory() as session:
                spans = (
                    (await session.execute(select(Span).where(Span.name == "title_generation")))
                    .scalars()
                    .all()
                )
                assert {span.attributes["key_source"] for span in spans} == {
                    "server_default",
                    "user_provided",
                }

    asyncio.run(scenario())


@pytest.mark.db
def test_a_late_title_never_changes_the_finished_runs_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主运行结束后标题才完成：运行统计、跨度树与 ``ended_at`` 只反映主运行。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_stats") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)

            session_id = uuid4()
            frames = await _run(
                _ScriptedPort([[_completed("回答")]]),
                {"session_id": str(session_id), "message": "嗨"},
            )
            assert "RUN_FINISHED" in [f["type"] for f in frames]

            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                title = await _post_title(
                    client, session_id, _ScriptedPort([[_completed("会话标题")]])
                )
                assert title.json()["status"] == "applied"

            async with factory() as session:
                run = (
                    await session.execute(select(Run).where(Run.session_id == session_id))
                ).scalar_one()
                run_detail = await ObservabilityRepository(session).get_run_detail(run.id)
                assert run_detail is not None
                # 标题的辅助模型一个 token、一毫秒都不混进主运行统计。
                assert [aggregate.model for aggregate in run_detail.usage] == ["claude-sonnet-5"]
                assert [span.name for span in run_detail.spans] == ["model_call"]
                span = (
                    await session.execute(select(Span).where(Span.name == "title_generation"))
                ).scalar_one()
                assert span.run_id is None
                assert span.session_id == session_id

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
