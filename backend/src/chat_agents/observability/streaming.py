"""``observe``——独立事务的观测包装（issue #52，ADR-0008）。

``agent/`` 完全不知道这个包存在——`observe` 单方向包一层事件流，不用依赖倒置
（ADR-0002 允许的方向本来就是 ``obs -> app``）。断连（生成器被 ``aclose()``/
取消）时，``finally`` 里把未闭合的跨度标记 ``partial``、运行标记 ``aborted``，
不伪造一次「跑完了」。所有写入独立事务，失败只记日志，不影响业务事务与线上流。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID

from ..agent.events import (
    IterationCompleted,
    IterationStarted,
    RunCompleted,
    RunEvent,
    RunFailed,
    llm_span_id,
)
from .writer import RunWriter


async def _close_partial_span(writer: RunWriter, *, span_id: UUID, run_id: str) -> None:
    """把一个还没等到 ``IterationCompleted`` 就中断的跨度标记为部分用量。

    ``RunFailed`` 与断连收尾（``finally``）共用这条——两者都是「没等到正常的
    模型调用完成事件」，用量三态因此都是 ``partial``（CONTEXT.md）。
    """

    await writer.close_span(
        span_id=span_id,
        run_id=run_id,
        status="error",
        usage_status="partial",
        input_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
    )


async def observe(
    events: AsyncIterator[RunEvent],
    *,
    session_id: UUID,
    trigger_message_id: UUID,
    effort: str | None,
    role: Literal["main"] = "main",
    model: str,
    session_factory: Any,
) -> AsyncIterator[RunEvent]:
    """透传每个 ``RunEvent``，旁路把运行/跨度增量写进 ``obs``。"""

    writer = RunWriter(session_factory=session_factory)
    run_id: str | None = None
    span_open: UUID | None = None
    terminal = False

    try:
        async for event in events:
            if run_id is None:
                run_id = event.run_id
                await writer.start_run(
                    run_id=run_id,
                    session_id=session_id,
                    trigger_message_id=trigger_message_id,
                    effort=effort,
                    prompt_version_id=(
                        event.prompt_version_id if isinstance(event, IterationStarted) else None
                    ),
                    tool_schema_version_id=(
                        event.tool_schema_version_id
                        if isinstance(event, IterationStarted)
                        else None
                    ),
                )

            if isinstance(event, IterationStarted):
                span_open = llm_span_id(run_id, event.iteration)
                await writer.open_span(
                    span_id=span_open,
                    run_id=run_id,
                    parent_span_id=None,
                    name="model_call",
                    kind="llm",
                    role=role,
                    model=model,
                )

            elif isinstance(event, IterationCompleted):
                await writer.close_span(
                    span_id=llm_span_id(run_id, event.iteration),
                    run_id=run_id,
                    status="ok",
                    usage_status=event.usage.state,
                    input_tokens=event.usage.input_tokens,
                    output_tokens=event.usage.output_tokens,
                    reasoning_tokens=event.usage.reasoning_tokens,
                )
                span_open = None

            elif isinstance(event, RunCompleted):
                terminal = True
                await writer.finish_run(run_id=run_id, status="completed")

            elif isinstance(event, RunFailed):
                terminal = True
                if span_open is not None:
                    await _close_partial_span(writer, span_id=span_open, run_id=run_id)
                    span_open = None
                await writer.finish_run(run_id=run_id, status="failed")

            yield event
    except Exception:
        # 往上游冒出的真实异常（比如 persist 的落库失败）——不是断连，是失败；
        # 标完 obs 再原样重新抛出，交给 encode_sse 收敛成 RUN_ERROR（ADR-0008）。
        # `except Exception` 接不住 `GeneratorExit`/`CancelledError`（两者都是
        # `BaseException`），断连因此只会落进下面的 `finally`，两条路径不会混。
        if run_id is not None and not terminal:
            if span_open is not None:
                await _close_partial_span(writer, span_id=span_open, run_id=run_id)
            await writer.finish_run(run_id=run_id, status="failed")
            terminal = True
        raise
    finally:
        if run_id is not None and not terminal:
            # 走到这里且未标记终态，只可能是客户端断连（生成器被取消）——
            # 这里是唯一的收尾机会（就地停，ADR-0008）。
            if span_open is not None:
                await _close_partial_span(writer, span_id=span_open, run_id=run_id)
            await writer.finish_run(run_id=run_id, status="aborted")
