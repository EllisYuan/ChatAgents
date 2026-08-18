"""``encode_sse``——``RunEvent`` → AG-UI over SSE 的唯一映射处（ADR-0009）。

一处 ``match``：把 ``agent/`` 吐出的领域事件翻成 AG-UI 事件，再交
``ag_ui.encoder.EventEncoder`` 编成 ``data: {...}\\n\\n``。这是三重包装的最外
层，也是「流开始后失败走 ``RUN_ERROR``、HTTP 仍是 200」这条纪律唯一的执行位置
——包一层 ``try/except Exception``，任何从 ``persist``/``observe``/``runner``
冒出来的异常，在这里收敛成一条 ``RUN_ERROR`` 后结束流，不再向上抛。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Literal
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
from ag_ui.encoder import EventEncoder

from ..agent.events import (
    IterationCompleted,
    IterationStarted,
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    TextDelta,
    ToolFinished,
    ToolStarted,
    assistant_message_id,
    llm_span_id,
    reasoning_message_id,
    tool_message_id,
)
from ..error_codes import RUN_FAILED_CODE, error_code
from .custom_events import SpanPayload, ToolResultPayload, UsagePayload

logger = structlog.get_logger(__name__)

_encoder = EventEncoder()


def _emit(event: object) -> str:
    return str(_encoder.encode(event))


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

    try:
        async for event in events:
            match event:
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
                        yield _emit(
                            ReasoningMessageEndEvent(
                                type=EventType.REASONING_MESSAGE_END,
                                message_id=str(current_reasoning_id),
                            )
                        )
                        yield _emit(
                            ReasoningEndEvent(
                                type=EventType.REASONING_END, message_id=str(current_reasoning_id)
                            )
                        )
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
                        yield _emit(
                            ReasoningMessageEndEvent(
                                type=EventType.REASONING_MESSAGE_END,
                                message_id=str(current_reasoning_id),
                            )
                        )
                        yield _emit(
                            ReasoningEndEvent(
                                type=EventType.REASONING_END, message_id=str(current_reasoning_id)
                            )
                        )
                        reasoning_open = False
                    if text_open:
                        yield _emit(
                            TextMessageEndEvent(
                                type=EventType.TEXT_MESSAGE_END,
                                message_id=str(current_assistant_id),
                            )
                        )
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

                case ToolFinished(iteration=iteration, tool_call_id=tool_call_id, result=result):
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
                                tool_call_id=tool_call_id, result=result
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
                    if reasoning_open:
                        yield _emit(
                            ReasoningMessageEndEvent(
                                type=EventType.REASONING_MESSAGE_END,
                                message_id=str(current_reasoning_id),
                            )
                        )
                        yield _emit(
                            ReasoningEndEvent(
                                type=EventType.REASONING_END, message_id=str(current_reasoning_id)
                            )
                        )
                    if text_open:
                        yield _emit(
                            TextMessageEndEvent(
                                type=EventType.TEXT_MESSAGE_END,
                                message_id=str(current_assistant_id),
                            )
                        )
                    yield _emit(
                        RunErrorEvent(
                            type=EventType.RUN_ERROR, message=reason, code=RUN_FAILED_CODE
                        )
                    )
    except Exception as exc:
        logger.warning("run.stream_failed", run_id=run_id, error_code=error_code(exc))
        yield _emit(RunErrorEvent(type=EventType.RUN_ERROR, message=str(exc), code=error_code(exc)))
