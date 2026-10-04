"""标题生成已移出主运行（issue #93）：``AgentRunner`` 不再拥有标题职责。

旧边界测试（``generate_title`` / ``TitleGenerationStarted`` / ``TitleGenerated``）
整体废弃；这里断言主运行事件流里没有任何标题数据，且只触发一次主模型调用。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from chat_agents.agent.events import IterationStarted, RunCompleted
from chat_agents.agent.runner import AgentRunner
from chat_agents.agent.tool_executor import ToolExecutor
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, TextDelta, Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.profile import EndpointProfile
from pydantic import SecretStr


class _RecordingPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        *,
        messages: Any,
        tools: Any,
        model: str,
        effort: EffortTier,
        profile: EndpointProfile,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ModelEvent]:
        del effort, profile
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "model": model,
                "system_prompt": system_prompt,
            }
        )
        yield TextDelta(text="回答")
        yield ModelCallCompleted(
            message=ModelMessage(role="assistant", content=(TextBlock(text="回答"),)),
            usage=Usage(state="complete", input_tokens=5, output_tokens=2, reasoning_tokens=None),
            stop_reason="end_turn",
        )


def _profile() -> EndpointProfile:
    return EndpointProfile(
        name="test",
        protocol="anthropic_messages",
        base_url="https://example.com",
        auth_field="Authorization",
        api_key=SecretStr("test"),
    )


def test_main_run_emits_no_title_events() -> None:
    port = _RecordingPort()
    runner = AgentRunner(tool_executor=ToolExecutor({}), model_port_factory=lambda _p: port)

    async def collect() -> list[Any]:
        return [
            event
            async for event in runner.run(
                [ModelMessage(role="user", content=(TextBlock(text="请介绍 Python"),))],
                profile=_profile(),
                main_model="main-model",
                effort="low",
                http_client=object(),
                run_id="run-1",
            )
        ]

    events = asyncio.run(collect())

    assert not any(
        type(event).__name__ in {"TitleGenerated", "TitleGenerationStarted"} for event in events
    )
    # 主运行只调用主模型一次；没有额外的 auxiliary 调用。
    assert [call["model"] for call in port.calls] == ["main-model"]
    assert isinstance(events[0], IterationStarted)
    assert isinstance(events[-1], RunCompleted)
