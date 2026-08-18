"""``obs`` schema 的查询仓库（issue #58）。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.obs import Run, Span
from ..llm.events import UsageState
from .models import DisplaySummary, RunDetail, RunSummary, SpanView, UsageAggregate


@dataclass(frozen=True, slots=True)
class RunObservation:
    run: Run
    spans: tuple[Span, ...]


class ObservabilityRepository:
    """只查询 ``obs`` 表，不验证或加载 ``app`` 记录。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_runs(self, session_id: UUID) -> list[RunSummary]:
        result = await self.session.execute(
            select(Run)
            .where(Run.session_id == session_id)
            .order_by(Run.started_at.desc(), Run.id.desc())
        )
        return [
            RunSummary(
                id=row.id,
                trigger_message_id=row.trigger_message_id,
                last_message_seq=row.last_message_seq,
            )
            for row in result.scalars()
        ]

    async def get_run(self, run_id: UUID) -> RunObservation | None:
        run_result = await self.session.execute(select(Run).where(Run.id == run_id))
        run = run_result.scalar_one_or_none()
        if run is None:
            return None
        span_result = await self.session.execute(
            select(Span).where(Span.run_id == run_id).order_by(Span.started_at.asc(), Span.id.asc())
        )
        return RunObservation(run=run, spans=tuple(span_result.scalars()))

    async def get_run_detail(self, run_id: UUID) -> RunDetail | None:
        observation = await self.get_run(run_id)
        if observation is None:
            return None
        return _run_detail(observation)


def _protocol(span: Span) -> str | None:
    value = span.attributes.get("protocol", span.attributes.get("llm.protocol"))
    return value if isinstance(value, str) else None


def _display_summary(attributes: dict[str, Any]) -> DisplaySummary | None:
    raw_content = attributes.get("message_content")
    if isinstance(raw_content, list):
        for item in raw_content:
            if not isinstance(item, dict) or item.get("type") != "reasoning":
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                return DisplaySummary(text=text, status="available")

    aged = attributes.get("display_summary_status") == "aged_out" or bool(
        attributes.get("reasoning_summary_aged_out")
    )
    return DisplaySummary(text=None, status="aged_out") if aged else None


def _span_view(span: Span, children: list[SpanView]) -> SpanView:
    view = SpanView(
        id=span.id,
        parent_span_id=span.parent_span_id,
        name=span.name,
        kind=span.kind,
        status=span.status,
        role=span.role,
        model=span.model,
        input_tokens=span.input_tokens,
        output_tokens=span.output_tokens,
        usage_status=cast(UsageState | None, span.usage_status),
        reasoning_tokens=span.reasoning_tokens,
        display_summary=_display_summary(span.attributes),
        started_at=span.started_at,
        ended_at=span.ended_at,
        children=children,
    )
    view._protocol = _protocol(span)
    return view


def _span_tree(spans: tuple[Span, ...]) -> list[SpanView]:
    by_parent: dict[UUID | None, list[Span]] = defaultdict(list)
    for span in spans:
        by_parent[span.parent_span_id].append(span)

    def build(parent_id: UUID | None) -> list[SpanView]:
        return [_span_view(span, build(span.id)) for span in by_parent.get(parent_id, [])]

    return build(None)


def _usage_aggregates(spans: tuple[Span, ...]) -> list[UsageAggregate]:
    """只把完整用量纳入汇总，避免把 partial 当成零或实测值。"""

    groups: dict[tuple[str, str], list[Span]] = defaultdict(list)
    for span in spans:
        if span.usage_status == "complete" and span.model is not None and span.role is not None:
            groups[(span.model, span.role)].append(span)

    aggregates: list[UsageAggregate] = []
    for (model, role), group in sorted(groups.items()):
        input_values = [span.input_tokens for span in group if span.input_tokens is not None]
        output_values = [span.output_tokens for span in group if span.output_tokens is not None]
        reasoning_values = [
            span.reasoning_tokens for span in group if span.reasoning_tokens is not None
        ]
        aggregates.append(
            UsageAggregate(
                model=model,
                role=role,
                input_tokens=sum(input_values) if input_values else None,
                output_tokens=sum(output_values) if output_values else None,
                reasoning_tokens=sum(reasoning_values) if reasoning_values else None,
                started_at=min(span.started_at for span in group),
                ended_at=(
                    max(
                        (span.ended_at for span in group if span.ended_at is not None), default=None
                    )
                ),
            )
        )
    return aggregates


def _run_detail(observation: RunObservation) -> RunDetail:
    run = observation.run
    attributes = run.attributes if isinstance(run.attributes, dict) else {}
    pruned_runs = attributes.get("pruned_runs")
    if isinstance(pruned_runs, list):
        pruned_count = len(pruned_runs)
    else:
        raw_count = attributes.get("pruned_run_count")
        pruned_count = raw_count if isinstance(raw_count, int) and raw_count >= 0 else 0
    return RunDetail(
        id=run.id,
        session_id=run.session_id,
        trigger_message_id=run.trigger_message_id,
        last_message_seq=run.last_message_seq,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        prompt_version_id=run.prompt_version_id,
        tool_schema_version_id=run.tool_schema_version_id,
        retention_window=run.retention_window,
        effort=run.effort,
        pruned_run_count=pruned_count,
        usage=_usage_aggregates(observation.spans),
        spans=_span_tree(observation.spans),
    )
