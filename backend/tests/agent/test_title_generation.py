"""首轮标题生成：``AgentRunner`` 的 auxiliary 调用边界。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from chat_agents.agent.events import TitleGenerated, TitleGenerationStarted
from chat_agents.agent.runner import AgentRunner
from chat_agents.agent.tool_executor import ToolExecutor
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, TextDelta, Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.profile import EndpointProfile
from pydantic import SecretStr


class _ParallelPort:
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
        if model == "aux-model":
            await asyncio.sleep(0)
            yield TextDelta(text="关于 Python 的标题")
            yield ModelCallCompleted(
                message=ModelMessage(
                    role="assistant", content=(TextBlock(text="关于 Python 的标题"),)
                ),
                usage=Usage(
                    state="complete", input_tokens=4, output_tokens=3, reasoning_tokens=None
                ),
                stop_reason="end_turn",
            )
        else:
            yield TextDelta(text="回答")
            yield ModelCallCompleted(
                message=ModelMessage(role="assistant", content=(TextBlock(text="回答"),)),
                usage=Usage(
                    state="complete", input_tokens=5, output_tokens=2, reasoning_tokens=None
                ),
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


def test_first_run_generates_title_with_auxiliary_model() -> None:
    port = _ParallelPort()
    runner = AgentRunner(tool_executor=ToolExecutor({}), model_port_factory=lambda _p: port)

    async def collect() -> list[Any]:
        return [
            event
            async for event in runner.run(
                [ModelMessage(role="user", content=(TextBlock(text="请介绍 Python"),))],
                profile=_profile(),
                main_model="main-model",
                auxiliary_model="aux-model",
                effort="low",
                http_client=object(),
                run_id="run-1",
                session_id=uuid4(),
                generate_title=True,
            )
        ]

    events = asyncio.run(collect())

    started = next(event for event in events if isinstance(event, TitleGenerationStarted))
    generated = next(event for event in events if isinstance(event, TitleGenerated))
    assert started.model == "aux-model"
    assert generated.title == "关于 Python 的标题"
    assert generated.usage is not None
    assert {call["model"] for call in port.calls} == {"aux-model", "main-model"}
    title_call = next(call for call in port.calls if call["model"] == "aux-model")
    assert title_call["tools"] == []
    assert title_call["messages"] == [
        ModelMessage(role="user", content=(TextBlock(text="请介绍 Python"),))
    ]
    assert title_call["system_prompt"]
