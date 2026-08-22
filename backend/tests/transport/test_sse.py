"""``encode_sse``：``RunEvent`` → AG-UI over SSE 的唯一映射处（issue #52）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from uuid import UUID, uuid4

from chat_agents.agent.events import (
    IterationCompleted,
    IterationStarted,
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from chat_agents.exceptions import UpstreamUnavailable
from chat_agents.llm.events import Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.transport.sse import encode_sse

RUN_ID = str(uuid4())
SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")


async def _events(items: Iterable[RunEvent]) -> AsyncIterator[RunEvent]:
    for item in items:
        yield item


def _usage(**overrides: object) -> Usage:
    defaults: dict[str, object] = {
        "state": "complete",
        "input_tokens": 10,
        "output_tokens": 5,
        "reasoning_tokens": None,
    }
    defaults.update(overrides)
    return Usage(**defaults)


def _frames(source: AsyncIterator[RunEvent]) -> list[dict[str, object]]:
    async def collect() -> list[dict[str, object]]:
        out = []
        async for line in encode_sse(source, session_id=SESSION_ID, run_id=RUN_ID, model="gpt"):
            out.append(json.loads(line))
        return out

    return asyncio.run(collect())


def test_text_only_run_emits_expected_type_sequence() -> None:
    message = ModelMessage(role="assistant", content=(TextBlock(text="你好"),))
    frames = _frames(
        _events(
            [
                IterationStarted(run_id=RUN_ID, iteration=1),
                TextDelta(run_id=RUN_ID, iteration=1, text="你好"),
                IterationCompleted(
                    run_id=RUN_ID, iteration=1, message=message, usage=_usage(), stop_reason="stop"
                ),
                RunCompleted(run_id=RUN_ID, iteration=1, message=message),
            ]
        )
    )
    assert [f["type"] for f in frames] == [
        "RUN_STARTED",
        "STEP_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "STEP_FINISHED",
        "CUSTOM",
        "CUSTOM",
        "RUN_FINISHED",
    ]
    assert frames[3]["delta"] == "你好"
    usage_frame, span_frame = frames[6], frames[7]
    assert usage_frame["name"] == "chatagents.usage"
    assert usage_frame["value"] == {
        "role": "main",
        "model": "gpt",
        "usage_status": "complete",
        "input_tokens": 10,
        "output_tokens": 5,
        "reasoning_tokens": None,
    }
    assert span_frame["name"] == "chatagents.span"
    span_value = span_frame["value"]
    assert isinstance(span_value, dict)
    assert set(span_value) == {"span_id", "parent_span_id", "kind", "duration_ms"}
    assert span_value["kind"] == "llm"


def test_reasoning_then_text_closes_reasoning_before_opening_text() -> None:
    message = ModelMessage(role="assistant", content=(TextBlock(text="答案"),))
    frames = _frames(
        _events(
            [
                IterationStarted(run_id=RUN_ID, iteration=1),
                ReasoningDelta(run_id=RUN_ID, iteration=1, text="想想"),
                TextDelta(run_id=RUN_ID, iteration=1, text="答案"),
                IterationCompleted(
                    run_id=RUN_ID, iteration=1, message=message, usage=_usage(), stop_reason="stop"
                ),
                RunCompleted(run_id=RUN_ID, iteration=1, message=message),
            ]
        )
    )
    types = [f["type"] for f in frames]
    assert types[:8] == [
        "RUN_STARTED",
        "STEP_STARTED",
        "REASONING_START",
        "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT",
        "REASONING_MESSAGE_END",
        "REASONING_END",
        "TEXT_MESSAGE_START",
    ]
    assert "REASONING_MESSAGE_CHUNK" not in types
    assert "REASONING_ENCRYPTED_VALUE" not in types


def test_tool_round_trip_emits_both_result_outlets() -> None:
    tool_message = ModelMessage(role="assistant", content=())
    frames = _frames(
        _events(
            [
                IterationStarted(run_id=RUN_ID, iteration=1),
                IterationCompleted(
                    run_id=RUN_ID,
                    iteration=1,
                    message=tool_message,
                    usage=_usage(),
                    stop_reason="tool_use",
                ),
                ToolStarted(
                    run_id=RUN_ID,
                    iteration=1,
                    tool_call_id="call-1",
                    name="web_search",
                    arguments={"query": "q"},
                ),
                ToolFinished(
                    run_id=RUN_ID,
                    iteration=1,
                    tool_call_id="call-1",
                    name="web_search",
                    result="found it",
                    structured={"result_count": 1},
                ),
                RunFailed(run_id=RUN_ID, iteration=2, reason="stopped"),
            ]
        )
    )
    types = [f["type"] for f in frames]
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_ARGS" in types
    assert "TOOL_CALL_END" in types
    assert "TOOL_CALL_RESULT" in types
    tool_result_custom = next(f for f in frames if f.get("name") == "chatagents.tool_result")
    tool_result_value = tool_result_custom["value"]
    assert isinstance(tool_result_value, dict)
    assert tool_result_value["tool_call_id"] == "call-1"
    assert tool_result_value["result"] == "found it"
    assert isinstance(tool_result_value["duration_ms"], int)
    assert tool_result_value["duration_ms"] >= 0
    assert tool_result_value["structured"] == {"result_count": 1}
    assert tool_result_value["status"] == "ok"
    result_event = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")
    assert result_event["content"] == "found it"
    assert result_event["role"] == "tool"


def test_tool_result_status_is_error_when_structured_is_none() -> None:
    """耗尽重试的外部失败没有结构化结果——`status` 是显式字段，不靠前端反推（ADR-0023）。"""
    frames = _frames(
        _events(
            [
                IterationStarted(run_id=RUN_ID, iteration=1),
                ToolStarted(
                    run_id=RUN_ID,
                    iteration=1,
                    tool_call_id="call-1",
                    name="web_search",
                    arguments={"query": "q"},
                ),
                ToolFinished(
                    run_id=RUN_ID,
                    iteration=1,
                    tool_call_id="call-1",
                    name="web_search",
                    result="目标站拒绝",
                    structured=None,
                ),
                RunFailed(run_id=RUN_ID, iteration=1, reason="stopped"),
            ]
        )
    )
    tool_result_value = next(f for f in frames if f.get("name") == "chatagents.tool_result")[
        "value"
    ]
    assert isinstance(tool_result_value, dict)
    assert tool_result_value["structured"] is None
    assert tool_result_value["status"] == "error"


def test_run_failed_maps_to_run_error_with_dedicated_code() -> None:
    frames = _frames(_events([RunFailed(run_id=RUN_ID, iteration=1, reason="上游 429")]))
    assert frames[-1]["type"] == "RUN_ERROR"
    assert frames[-1]["message"] == "上游 429"
    assert frames[-1]["code"] == "run_failed"


def test_unexpected_exception_becomes_run_error_with_shared_error_code() -> None:
    async def failing() -> AsyncIterator[RunEvent]:
        yield IterationStarted(run_id=RUN_ID, iteration=1)
        raise UpstreamUnavailable("上游挂了")

    frames = _frames(failing())
    assert frames[-1]["type"] == "RUN_ERROR"
    assert frames[-1]["code"] == "upstream_unavailable"
    assert frames[-1]["message"] == "上游挂了"
