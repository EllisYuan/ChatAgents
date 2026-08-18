"""AgentRunner：纯 ReAct Loop（issue #51）——全部用 fake ModelPort/ToolExecutor，
零网络零数据库跑完整个 Loop（验收标准最后一条）。
"""

from __future__ import annotations

import ast
import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from chat_agents.agent.events import (
    IterationStarted,
    ReasoningDelta,
    RunCompleted,
    RunFailed,
    ToolFinished,
    ToolStarted,
)
from chat_agents.agent.runner import AgentRunner
from chat_agents.agent.step_budget import STEP_BUDGETS
from chat_agents.agent.tool_executor import ToolExecutor
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, Usage
from chat_agents.llm.events import ReasoningDelta as ModelReasoningDelta
from chat_agents.llm.events import TextDelta as ModelTextDelta
from chat_agents.llm.message import ModelMessage, TextBlock, ToolCallBlock
from chat_agents.llm.profile import EndpointProfile
from chat_agents.tools.types import ToolResult, ToolSpec
from pydantic import SecretStr


def _profile() -> EndpointProfile:
    return EndpointProfile(
        name="test",
        protocol="anthropic_messages",
        base_url="https://example.com",
        auth_field="Authorization",
        api_key=SecretStr("sk-test"),
    )


def _completed(
    *, text: str = "", tool_calls: Sequence[ToolCallBlock] = (), stop_reason: str = "end_turn"
) -> ModelCallCompleted:
    content: list[Any] = []
    if text:
        content.append(TextBlock(text=text))
    content.extend(tool_calls)
    return ModelCallCompleted(
        message=ModelMessage(role="assistant", content=tuple(content)),
        usage=Usage(state="complete", input_tokens=10, output_tokens=5, reasoning_tokens=None),
        stop_reason=stop_reason,
    )


class ScriptedModelPort:
    """按调用顺序回放一份录好的 ``ModelEvent`` 序列——回放注入点在 ModelPort（ADR-0025）。"""

    def __init__(self, turns: Sequence[Sequence[ModelEvent]]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self, *, messages: Any, tools: Any, model: str, effort: EffortTier, profile: Any
    ) -> AsyncIterator[ModelEvent]:
        self.calls.append({"messages": list(messages), "model": model, "effort": effort})
        turn = self._turns[len(self.calls) - 1]
        for event in turn:
            yield event


class RaisingModelPort:
    async def stream(self, **_kwargs: Any) -> AsyncIterator[ModelEvent]:
        raise RuntimeError("上游 5xx")
        yield  # pragma: no cover - 让这是一个 async generator


def _fake_tool_spec(
    name: str, *, delay: float = 0.0, parallelizable: bool = True
) -> tuple[ToolSpec, list[float]]:
    started_at: list[float] = []

    async def handler(_args: dict[str, Any], _ctx: Any) -> ToolResult:
        started_at.append(time.monotonic())
        if delay:
            await asyncio.sleep(delay)
        return ToolResult(structured={"tool": name}, model_text=f"{name} 的结果")

    spec = ToolSpec(
        name=name,
        description="",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        timeout_s=5.0,
        retryable=False,
        parallelizable=parallelizable,
    )
    return spec, started_at


async def _collect(runner: AgentRunner, **kwargs: Any) -> list[Any]:
    kwargs.setdefault("auxiliary_model", "aux-model")
    kwargs.setdefault("http_client", object())  # 假 handler 从不碰它，占位即可
    return [event async for event in runner.run(**kwargs)]


def test_full_run_message_tool_model_answer() -> None:
    """验收标准第一条：用户消息 → 模型调用 → 工具调用 → 再次模型调用 → 最终回答。"""
    search_spec, _ = _fake_tool_spec("search")
    executor = ToolExecutor({"search": search_spec})
    port = ScriptedModelPort(
        [
            [
                ModelTextDelta(text="我先搜一下"),
                _completed(
                    text="我先搜一下",
                    tool_calls=[ToolCallBlock(id="call-1", name="search", arguments={"q": "x"})],
                ),
            ],
            [ModelTextDelta(text="答案是 42"), _completed(text="答案是 42")],
        ]
    )
    runner = AgentRunner(tool_executor=executor, model_port_factory=lambda _profile: port)

    events = asyncio.run(
        _collect(
            runner,
            messages=[ModelMessage(role="user", content=(TextBlock(text="42 是多少"),))],
            profile=_profile(),
            main_model="claude-x",
            effort="medium",
        )
    )

    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "IterationStarted",
        "TextDelta",
        "IterationCompleted",
        "ToolStarted",
        "ToolFinished",
        "IterationStarted",
        "TextDelta",
        "IterationCompleted",
        "RunCompleted",
    ]
    final = events[-1]
    assert isinstance(final, RunCompleted)
    assert final.iteration == 2
    assert final.message.content[0].text == "答案是 42"

    tool_started = next(e for e in events if isinstance(e, ToolStarted))
    tool_finished = next(e for e in events if isinstance(e, ToolFinished))
    assert tool_started.name == "search"
    assert tool_finished.result == "search 的结果"

    # 第二次模型调用的输入序列里带上了第一轮的助手消息与工具结果消息。
    assert [m.role for m in port.calls[1]["messages"]] == ["user", "assistant", "tool"]


def test_reasoning_delta_is_forwarded_as_agent_level_event() -> None:
    port = ScriptedModelPort([[ModelReasoningDelta(text="嗯我想想"), _completed(text="好的")]])
    runner = AgentRunner(tool_executor=ToolExecutor({}), model_port_factory=lambda _p: port)

    events = asyncio.run(
        _collect(
            runner,
            messages=[ModelMessage(role="user", content=(TextBlock(text="嗨"),))],
            profile=_profile(),
            main_model="m",
            effort="low",
        )
    )

    reasoning = next(e for e in events if isinstance(e, ReasoningDelta))
    assert reasoning.text == "嗯我想想"
    assert reasoning.iteration == 1


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh"])
def test_effort_drives_hard_cap_and_reasoning_effort(effort: EffortTier) -> None:
    """验收标准第五条：努力档位驱动步数预算与 reasoning effort 两处。"""
    hard_cap = STEP_BUDGETS[effort].hard_cap
    search_spec, started_at = _fake_tool_spec("search")
    executor = ToolExecutor({"search": search_spec})
    # 每一轮都继续发起工具调用，永不给出最终回答——迫使 Runner 撞硬上限。
    always_calls_tool: list[Sequence[ModelEvent]] = [
        [
            _completed(
                tool_calls=[
                    ToolCallBlock(id=f"call-{i}", name="search", arguments={}),
                ]
            )
        ]
        for i in range(hard_cap)
    ]
    port = ScriptedModelPort(always_calls_tool)
    runner = AgentRunner(tool_executor=executor, model_port_factory=lambda _p: port)

    events = asyncio.run(
        _collect(
            runner,
            messages=[ModelMessage(role="user", content=(TextBlock(text="一直搜"),))],
            profile=_profile(),
            main_model="m",
            effort=effort,
        )
    )

    assert len(port.calls) == hard_cap
    assert all(call["effort"] == effort for call in port.calls)
    assert isinstance(events[-1], RunFailed)
    assert "硬上限" in events[-1].reason
    assert events[-1].iteration == hard_cap
    iteration_starts = [e for e in events if isinstance(e, IterationStarted)]
    assert [e.iteration for e in iteration_starts] == list(range(1, hard_cap + 1))
    # 第 hard_cap 轮的工具调用永远等不到下一次模型调用去读，执行它纯属浪费——
    # Runner 应当在触达上限时直接失败，不执行这一轮的工具。
    assert len(started_at) == hard_cap - 1


def test_parallel_tool_calls_actually_run_concurrently() -> None:
    """验收标准第六条：并发工具调用真的并行执行，不是串行伪装。"""
    delay = 0.2
    spec_a, started_a = _fake_tool_spec("search_a", delay=delay)
    spec_b, started_b = _fake_tool_spec("search_b", delay=delay)
    executor = ToolExecutor({"search_a": spec_a, "search_b": spec_b})
    port = ScriptedModelPort(
        [
            [
                _completed(
                    tool_calls=[
                        ToolCallBlock(id="call-a", name="search_a", arguments={}),
                        ToolCallBlock(id="call-b", name="search_b", arguments={}),
                    ]
                )
            ],
            [_completed(text="都拿到了")],
        ]
    )
    runner = AgentRunner(tool_executor=executor, model_port_factory=lambda _p: port)

    start = time.monotonic()
    events = asyncio.run(
        _collect(
            runner,
            messages=[ModelMessage(role="user", content=(TextBlock(text="并行搜两个"),))],
            profile=_profile(),
            main_model="m",
            effort="medium",
        )
    )
    elapsed = time.monotonic() - start

    assert elapsed < delay * 1.6  # 串行会 >= 2*delay；并行应明显小于
    assert abs(started_a[0] - started_b[0]) < delay / 2  # 两个 handler 几乎同时开始
    assert isinstance(events[-1], RunCompleted)


def test_non_parallelizable_tool_calls_run_serially() -> None:
    order: list[str] = []

    async def make_handler(name: str) -> Any:
        async def handler(_args: dict[str, Any], _ctx: Any) -> ToolResult:
            order.append(f"{name}-start")
            await asyncio.sleep(0.02)
            order.append(f"{name}-end")
            return ToolResult(structured={}, model_text=name)

        return handler

    spec_a = ToolSpec(
        name="write_a",
        description="",
        parameters={"type": "object", "properties": {}},
        handler=asyncio.run(make_handler("write_a")),
        timeout_s=5.0,
        retryable=False,
        parallelizable=False,
    )
    spec_b = ToolSpec(
        name="write_b",
        description="",
        parameters={"type": "object", "properties": {}},
        handler=asyncio.run(make_handler("write_b")),
        timeout_s=5.0,
        retryable=False,
        parallelizable=False,
    )
    executor = ToolExecutor({"write_a": spec_a, "write_b": spec_b})
    port = ScriptedModelPort(
        [
            [
                _completed(
                    tool_calls=[
                        ToolCallBlock(id="call-a", name="write_a", arguments={}),
                        ToolCallBlock(id="call-b", name="write_b", arguments={}),
                    ]
                )
            ],
            [_completed(text="done")],
        ]
    )
    runner = AgentRunner(tool_executor=executor, model_port_factory=lambda _p: port)

    asyncio.run(
        _collect(
            runner,
            messages=[ModelMessage(role="user", content=(TextBlock(text="串行写两个"),))],
            profile=_profile(),
            main_model="m",
            effort="medium",
        )
    )

    assert order == ["write_a-start", "write_a-end", "write_b-start", "write_b-end"]


def test_upstream_model_error_yields_run_failed_not_an_exception() -> None:
    runner = AgentRunner(
        tool_executor=ToolExecutor({}), model_port_factory=lambda _p: RaisingModelPort()
    )

    events = asyncio.run(
        _collect(
            runner,
            messages=[ModelMessage(role="user", content=(TextBlock(text="嗨"),))],
            profile=_profile(),
            main_model="m",
            effort="medium",
        )
    )

    assert len(events) == 2  # IterationStarted, RunFailed
    assert isinstance(events[-1], RunFailed)
    assert "5xx" in events[-1].reason
    assert events[-1].iteration == 1


def test_run_id_is_stable_and_present_on_every_event() -> None:
    """验收标准第四条：层级标识随事件带出。"""
    port = ScriptedModelPort([[_completed(text="ok")]])
    runner = AgentRunner(tool_executor=ToolExecutor({}), model_port_factory=lambda _p: port)

    events = asyncio.run(
        _collect(
            runner,
            messages=[ModelMessage(role="user", content=(TextBlock(text="嗨"),))],
            profile=_profile(),
            main_model="m",
            effort="medium",
        )
    )

    run_ids = {e.run_id for e in events}
    assert len(run_ids) == 1
    assert next(iter(run_ids))  # 非空


def test_runner_module_imports_no_database_http_or_sse() -> None:
    """验收标准第二条：Runner 代码里没有任何数据库、HTTP、SSE 的 import。"""
    runner_path = (
        Path(__file__).resolve().parents[2] / "src" / "chat_agents" / "agent" / "runner.py"
    )
    source = runner_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = (
        "fastapi",
        "starlette",
        "sse_starlette",
        "sqlalchemy",
        "chat_agents.db",
        "psycopg",
        "httpx",
        "httpx2",
        "anthropic",
        "openai",
    )
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(name.startswith(forbidden) for name in imported)
