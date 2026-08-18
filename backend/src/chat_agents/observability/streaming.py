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
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    TitleGenerated,
    TitleGenerationStarted,
    llm_span_id,
    title_span_id,
)
from .reasoning import reasoning_attributes
from .writer import RunWriter


async def _close_partial_span(
    writer: RunWriter,
    *,
    span_id: UUID,
    run_id: str,
    attributes: dict[str, Any] | None = None,
) -> None:
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
        attributes=attributes,
    )


async def observe(
    events: AsyncIterator[RunEvent],
    *,
    session_id: UUID,
    trigger_message_id: UUID,
    effort: str | None,
    role: Literal["main"] = "main",
    model: str,
    protocol: str | None = None,
    retention_window: int | None = None,
    run_attributes: dict[str, Any] | None = None,
    session_factory: Any,
    expect_title: bool = False,
) -> AsyncIterator[RunEvent]:
    """透传事件，并记录主模型与 auxiliary 标题的兄弟跨度。"""

    writer = RunWriter(session_factory=session_factory)
    run_id: str | None = None
    main_span_open: UUID | None = None
    title_span_open: UUID | None = None
    main_terminal = False
    main_status: Literal["completed", "failed"] = "completed"
    title_terminal = not expect_title
    terminal = False
    main_attributes: dict[str, Any] = {"protocol": protocol} if protocol is not None else {}
    title_attributes: dict[str, Any] = {"protocol": protocol} if protocol is not None else {}
    main_reasoning: list[str] = []
    title_reasoning: list[str] = []

    async def finish_if_ready() -> None:
        nonlocal terminal
        if run_id is not None and main_terminal and title_terminal and not terminal:
            await writer.finish_run(run_id=run_id, status=main_status)
            terminal = True

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
                    retention_window=retention_window,
                    attributes=run_attributes,
                )

            if isinstance(event, TitleGenerationStarted):
                title_terminal = False
                title_reasoning.clear()
                title_span_open = title_span_id(run_id)
                await writer.open_span(
                    span_id=title_span_open,
                    run_id=run_id,
                    parent_span_id=None,
                    name="title_generation",
                    kind="llm",
                    role="auxiliary",
                    model=event.model,
                    attributes=title_attributes,
                )

            elif isinstance(event, IterationStarted):
                main_reasoning.clear()
                main_span_open = llm_span_id(run_id, event.iteration)
                await writer.open_span(
                    span_id=main_span_open,
                    run_id=run_id,
                    parent_span_id=None,
                    name="model_call",
                    kind="llm",
                    role=role,
                    model=model,
                    attributes=main_attributes,
                )

            elif isinstance(event, ReasoningDelta):
                main_reasoning.append(event.text)

            elif isinstance(event, IterationCompleted):
                attributes = dict(main_attributes)
                summary = reasoning_attributes("".join(main_reasoning))
                if summary is not None:
                    attributes.update(summary)
                await writer.close_span(
                    span_id=llm_span_id(run_id, event.iteration),
                    run_id=run_id,
                    status="ok",
                    usage_status=event.usage.state,
                    input_tokens=event.usage.input_tokens,
                    output_tokens=event.usage.output_tokens,
                    reasoning_tokens=event.usage.reasoning_tokens,
                    attributes=attributes,
                )
                main_span_open = None

            elif isinstance(event, TitleGenerated):
                title_terminal = True
                if title_span_open is not None:
                    usage = event.usage
                    attributes = dict(title_attributes)
                    summary = reasoning_attributes("".join(title_reasoning))
                    if summary is not None:
                        attributes.update(summary)
                    await writer.close_span(
                        span_id=title_span_open,
                        run_id=run_id,
                        status="error" if event.error is not None else "ok",
                        usage_status=usage.state if usage is not None else "unavailable",
                        input_tokens=usage.input_tokens if usage is not None else None,
                        output_tokens=usage.output_tokens if usage is not None else None,
                        reasoning_tokens=usage.reasoning_tokens if usage is not None else None,
                        attributes=attributes,
                    )
                    title_span_open = None
                await finish_if_ready()

            elif isinstance(event, RunCompleted):
                main_terminal = True
                main_status = "completed"
                await finish_if_ready()

            elif isinstance(event, RunFailed):
                main_terminal = True
                main_status = "failed"
                if main_span_open is not None:
                    await _close_partial_span(writer, span_id=main_span_open, run_id=run_id)
                    main_span_open = None
                if title_terminal:
                    await writer.finish_run(run_id=run_id, status="failed")
                    terminal = True

            yield event
    except Exception:
        # 上游真实异常先标 failed，再原样交给 transport 收敛成 RUN_ERROR。
        if run_id is not None and not terminal:
            if main_span_open is not None:
                await _close_partial_span(writer, span_id=main_span_open, run_id=run_id)
            if title_span_open is not None:
                await _close_partial_span(writer, span_id=title_span_open, run_id=run_id)
            await writer.finish_run(run_id=run_id, status="failed")
            terminal = True
        raise
    finally:
        if run_id is not None and not terminal:
            if main_span_open is not None:
                await _close_partial_span(writer, span_id=main_span_open, run_id=run_id)
            if title_span_open is not None:
                await _close_partial_span(writer, span_id=title_span_open, run_id=run_id)
            await writer.finish_run(run_id=run_id, status="aborted")
