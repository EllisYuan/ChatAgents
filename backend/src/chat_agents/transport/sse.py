"""``encode_sse``——``RunEvent`` → AG-UI over SSE 的唯一映射处（ADR-0009）。

一处 ``match``：把 ``agent/`` 吐出的领域事件翻成 AG-UI 事件，序列化规则与
``ag_ui.encoder.EventEncoder`` 一致（``by_alias``、丢 ``None``），帧头（
``data: ...\\n\\n``、分隔符、心跳、断连收尾）交给 ``sse_starlette``
的 ``EventSourceResponse`` 统一处理，这里只产出 JSON 信封本身。这是三重包装
的最外层，也是「流开始后失败走 ``RUN_ERROR``、HTTP 仍是 200」这条纪律唯一的
执行位置——包一层 ``try/except Exception``，任何从 ``persist``/``observe``/
``runner`` 冒出来的异常，在这里收敛成一条 ``RUN_ERROR`` 后结束流，不再向上抛。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID

import structlog
from ag_ui.core import (
    CustomEvent,
    EventType,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from ..agent.events import (
    IterationCompleted,
    IterationStarted,
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    TextDelta,
    TitleGenerated,
    TitleGenerationStarted,
    ToolFinished,
    ToolStarted,
    assistant_message_id,
    llm_span_id,
    reasoning_message_id,
    title_span_id,
    tool_message_id,
)
from ..error_codes import RUN_FAILED_CODE, error_code
from ..llm.events import Usage
from .custom_events import SpanPayload, TitlePayload, ToolResultPayload, UsagePayload

logger = structlog.get_logger(__name__)


def _emit(event: Any) -> str:
    """按 ``ag_ui.encoder.EventEncoder`` 同款规则序列化（``by_alias``、丢 ``None``）。

    不经它的 ``encode()``——那一步会把 JSON 再包一层 ``data: ...\\n\\n`` 的 SSE
    帧头，而帧头交给 ``sse_starlette.EventSourceResponse`` 统一处理（分隔符、
    心跳、断连收尾都在那一层），这里只产出信封本身，避免帧头套两层。
    """

    result = event.model_dump_json(by_alias=True, exclude_none=True)
    return result if isinstance(result, str) else str(result)


async def _close_reasoning(reasoning_id: UUID) -> AsyncIterator[str]:
    """收尾一轮的 ``REASONING_*`` 分组——三处调用点（文本开始前/迭代结束/运行失败）共用。"""

    yield _emit(
        ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=str(reasoning_id))
    )
    yield _emit(ReasoningEndEvent(type=EventType.REASONING_END, message_id=str(reasoning_id)))


async def _close_text(assistant_id: UUID) -> AsyncIterator[str]:
    """收尾一轮的 ``TEXT_MESSAGE_*`` 分组——迭代结束/运行失败两处调用点共用。"""

    yield _emit(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=str(assistant_id)))


async def encode_sse(
    events: AsyncIterator[RunEvent],
    *,
    session_id: UUID,
    run_id: str,
    role: Literal["main"] = "main",
    model: str,
) -> AsyncIterator[str]:
    """把一次运行的领域事件流编码成 AG-UI over SSE 的线上字符串流。"""

    thread_id = str(session_id)
    yield _emit(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id))

    text_open = False
    reasoning_open = False
    current_assistant_id: UUID | None = None
    current_reasoning_id: UUID | None = None
    iteration_started_at = time.monotonic()
    tool_started_at: dict[str, float] = {}
    title_started_at: float | None = None
    title_model: str | None = None

    try:
        async for event in events:
            match event:
                case TitleGenerationStarted(model=model_name):
                    title_model = model_name
                    title_started_at = time.monotonic()

                case TitleGenerated(session_id=title_session_id, title=title, usage=usage):
                    title_usage = usage or Usage(
                        state="unavailable",
                        input_tokens=None,
                        output_tokens=None,
                        reasoning_tokens=None,
                    )
                    duration_ms = (
                        int((time.monotonic() - title_started_at) * 1000)
                        if title_started_at is not None
                        else 0
                    )
                    yield _emit(
                        CustomEvent(
                            type=EventType.CUSTOM,
                            name="chatagents.title",
                            value=TitlePayload(
                                session_id=str(title_session_id), title=title
                            ).model_dump(),
                        )
                    )
                    yield _emit(
                        CustomEvent(
                            type=EventType.CUSTOM,
                            name="chatagents.usage",
                            value=UsagePayload(
                                role="auxiliary",
                                model=title_model or model,
                                usage_status=title_usage.state,
                                input_tokens=title_usage.input_tokens,
                                output_tokens=title_usage.output_tokens,
                                reasoning_tokens=title_usage.reasoning_tokens,
                            ).model_dump(),
                        )
                    )
                    yield _emit(
                        CustomEvent(
                            type=EventType.CUSTOM,
                            name="chatagents.span",
                            value=SpanPayload(
                                span_id=str(title_span_id(run_id)),
                                parent_span_id=None,
                                kind="llm",
                                duration_ms=duration_ms,
                            ).model_dump(),
                        )
                    )

                case IterationStarted(iteration=iteration):
                    current_assistant_id = assistant_message_id(run_id, iteration)
                    current_reasoning_id = reasoning_message_id(run_id, iteration)
                    text_open = False
                    reasoning_open = False
                    iteration_started_at = time.monotonic()
                    yield _emit(
                        StepStartedEvent(
                            type=EventType.STEP_STARTED, step_name=f"iteration-{iteration}"
                        )
                    )

                case TextDelta(text=text):
                    assert current_assistant_id is not None
                    if reasoning_open:
                        assert current_reasoning_id is not None
                        async for frame in _close_reasoning(current_reasoning_id):
                            yield frame
                        reasoning_open = False
                    if not text_open:
                        yield _emit(
                            TextMessageStartEvent(
                                type=EventType.TEXT_MESSAGE_START,
                                message_id=str(current_assistant_id),
                                role="assistant",
                            )
                        )
                        text_open = True
                    yield _emit(
                        TextMessageContentEvent(
                            type=EventType.TEXT_MESSAGE_CONTENT,
                            message_id=str(current_assistant_id),
                            delta=text,
                        )
                    )

                case ReasoningDelta(text=text):
                    assert current_reasoning_id is not None
                    if not reasoning_open:
                        yield _emit(
                            ReasoningStartEvent(
                                type=EventType.REASONING_START,
                                message_id=str(current_reasoning_id),
                            )
                        )
                        yield _emit(
                            ReasoningMessageStartEvent(
                                type=EventType.REASONING_MESSAGE_START,
                                message_id=str(current_reasoning_id),
                                role="reasoning",
                            )
                        )
                        reasoning_open = True
                    yield _emit(
                        ReasoningMessageContentEvent(
                            type=EventType.REASONING_MESSAGE_CONTENT,
                            message_id=str(current_reasoning_id),
                            delta=text,
                        )
                    )

                case IterationCompleted(iteration=iteration, usage=usage):
                    if reasoning_open:
                        assert current_reasoning_id is not None
                        async for frame in _close_reasoning(current_reasoning_id):
                            yield frame
                        reasoning_open = False
                    if text_open:
                        assert current_assistant_id is not None
                        async for frame in _close_text(current_assistant_id):
                            yield frame
                        text_open = False
                    yield _emit(
                        StepFinishedEvent(
                            type=EventType.STEP_FINISHED, step_name=f"iteration-{iteration}"
                        )
                    )
                    duration_ms = int((time.monotonic() - iteration_started_at) * 1000)
                    yield _emit(
                        CustomEvent(
                            type=EventType.CUSTOM,
                            name="chatagents.usage",
                            value=UsagePayload(
                                role=role,
                                model=model,
                                usage_status=usage.state,
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                reasoning_tokens=usage.reasoning_tokens,
                            ).model_dump(),
                        )
                    )
                    yield _emit(
                        CustomEvent(
                            type=EventType.CUSTOM,
                            name="chatagents.span",
                            value=SpanPayload(
                                span_id=str(llm_span_id(run_id, iteration)),
                                parent_span_id=None,
                                kind="llm",
                                duration_ms=duration_ms,
                            ).model_dump(),
                        )
                    )

                case ToolStarted(tool_call_id=tool_call_id, name=name, arguments=arguments):
                    tool_started_at[tool_call_id] = time.monotonic()
                    yield _emit(
                        ToolCallStartEvent(
                            type=EventType.TOOL_CALL_START,
                            tool_call_id=tool_call_id,
                            tool_call_name=name,
                            parent_message_id=str(current_assistant_id),
                        )
                    )
                    yield _emit(
                        ToolCallArgsEvent(
                            type=EventType.TOOL_CALL_ARGS,
                            tool_call_id=tool_call_id,
                            delta=json.dumps(arguments, ensure_ascii=False),
                        )
                    )

                case ToolFinished(
                    iteration=iteration,
                    tool_call_id=tool_call_id,
                    result=result,
                    structured=structured,
                ):
                    started_at = tool_started_at.pop(tool_call_id, None)
                    tool_duration_ms = (
                        int((time.monotonic() - started_at) * 1000) if started_at is not None else 0
                    )
                    yield _emit(
                        ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id)
                    )
                    yield _emit(
                        ToolCallResultEvent(
                            type=EventType.TOOL_CALL_RESULT,
                            message_id=str(tool_message_id(run_id, iteration)),
                            tool_call_id=tool_call_id,
                            content=result,
                            role="tool",
                        )
                    )
                    yield _emit(
                        CustomEvent(
                            type=EventType.CUSTOM,
                            name="chatagents.tool_result",
                            value=ToolResultPayload(
                                tool_call_id=tool_call_id,
                                result=result,
                                duration_ms=tool_duration_ms,
                                structured=structured,
                                status="ok" if structured is not None else "error",
                            ).model_dump(),
                        )
                    )

                case RunCompleted():
                    yield _emit(
                        RunFinishedEvent(
                            type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id
                        )
                    )

                case RunFailed(reason=reason):
                    if reasoning_open and current_reasoning_id is not None:
                        async for frame in _close_reasoning(current_reasoning_id):
                            yield frame
                    if text_open and current_assistant_id is not None:
                        async for frame in _close_text(current_assistant_id):
                            yield frame
                    yield _emit(
                        RunErrorEvent(
                            type=EventType.RUN_ERROR, message=reason, code=RUN_FAILED_CODE
                        )
                    )
    except Exception as exc:
        logger.warning("run.stream_failed", run_id=run_id, error_code=error_code(exc))
        yield _emit(RunErrorEvent(type=EventType.RUN_ERROR, message=str(exc), code=error_code(exc)))
