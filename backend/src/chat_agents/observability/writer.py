"""``obs`` schema 的独立事务写入（issue #52，ADR-0002：失败只记日志）。

每次写入开自己的短事务，与业务事务物理隔离——两个 ``async with`` 不可能
同事务提交，ADR-0002「观测写失败不得影响业务」这条纪律因此结构性成立，
不靠人记住。写入异常在这里就地吞掉，只留一条 ``structlog`` 日志。
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy import func, update

from ..db.obs import Run, Span
from ..llm.events import UsageState

logger = structlog.get_logger(__name__)


async def _guarded(session_factory: Any, *, op: str, run_id: str, body: Any) -> None:
    try:
        async with session_factory() as session, session.begin():
            await body(session)
    except Exception as exc:
        logger.warning("observability.write_failed", op=op, run_id=run_id, error=str(exc))


class RunWriter:
    """``obs.run`` / ``obs.span`` 的增量写入器：闭合即写，不攒到最后一把写。"""

    def __init__(self, *, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def start_run(
        self,
        *,
        run_id: str,
        session_id: UUID,
        trigger_message_id: UUID,
        effort: str | None,
        prompt_version_id: str | None,
        tool_schema_version_id: str | None,
    ) -> None:
        async def body(session: Any) -> None:
            session.add(
                Run(
                    id=UUID(run_id),
                    session_id=session_id,
                    trigger_message_id=trigger_message_id,
                    status="running",
                    effort=effort,
                    prompt_version_id=prompt_version_id,
                    tool_schema_version_id=tool_schema_version_id,
                )
            )

        await _guarded(self._session_factory, op="start_run", run_id=run_id, body=body)

    async def open_span(
        self,
        *,
        span_id: UUID,
        run_id: str,
        parent_span_id: UUID | None,
        name: str,
        kind: str,
        role: str | None,
        model: str | None,
    ) -> None:
        async def body(session: Any) -> None:
            session.add(
                Span(
                    id=span_id,
                    run_id=UUID(run_id),
                    parent_span_id=parent_span_id,
                    name=name,
                    kind=kind,
                    role=role,
                    model=model,
                )
            )

        await _guarded(self._session_factory, op="open_span", run_id=run_id, body=body)

    async def close_span(
        self,
        *,
        span_id: UUID,
        run_id: str,
        status: Literal["ok", "error"],
        usage_status: UsageState | None,
        input_tokens: int | None,
        output_tokens: int | None,
        reasoning_tokens: int | None,
    ) -> None:
        async def body(session: Any) -> None:
            await session.execute(
                update(Span)
                .where(Span.id == span_id)
                .values(
                    status=status,
                    usage_status=usage_status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reasoning_tokens=reasoning_tokens,
                    ended_at=func.now(),
                )
            )

        await _guarded(self._session_factory, op="close_span", run_id=run_id, body=body)

    async def finish_run(
        self, *, run_id: str, status: Literal["completed", "failed", "aborted"]
    ) -> None:
        async def body(session: Any) -> None:
            await session.execute(
                update(Run).where(Run.id == UUID(run_id)).values(status=status, ended_at=func.now())
            )

        await _guarded(self._session_factory, op="finish_run", run_id=run_id, body=body)
