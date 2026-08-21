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
from chat_agents.db.obs import Run
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, Usage
from chat_agents.llm.events import TextDelta as ModelTextDelta
from chat_agents.llm.message import ModelMessage, TextBlock
from sqlalchemy import select

from .db_helpers import migrated_engine, session_factory_for


class _ScriptedPort:
    def __init__(self, turns: list[list[ModelEvent]]) -> None:
        self._turns = turns
        self.calls = 0

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
