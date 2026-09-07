"""Conversation rules and model-input projection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Collection, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.app import Message as MessageRow
from ..db.app import Session as SessionRow
from ..exceptions import ProtocolError
from ..llm.message import ModelMessage, TextBlock, ToolCallBlock, ToolResultBlock
from ..validation import MAX_TITLE_LENGTH
from .masking import RETENTION_WINDOW, MaskedObservation, MaskingProjection, mask_tool_observations
from .models import (
    SessionDetail,
    SessionSummary,
    encode_content,
    row_to_model_message,
    row_to_view,
    session_to_view,
)
from .repository import ConversationRepository

OBSERVATION_KEEP = RETENTION_WINDOW
_ORPHAN_TOOL_RESULT = "Tool call ended before a result was recorded."


@dataclass(frozen=True, slots=True)
class RunInterval:
    """由 observability 层传入的一次运行消息区间。"""

    id: UUID | str
    start_seq: int
    end_seq: int | None
    status: str = "running"

    def __post_init__(self) -> None:
        if self.end_seq is not None and self.end_seq < self.start_seq:
            raise ValueError("run interval end_seq must not precede start_seq")


def select_prunable_run_intervals(
    intervals: Iterable[RunInterval],
    *,
    prune_count: int,
    current_run_id: UUID | str | None = None,
) -> tuple[RunInterval, ...]:
    """选择下一次投影可整块省略的最旧已完成运行。

    输入必须包含会话中的全部运行并按消息起始序列排序；首个运行永不入选。
    ``running`` 或没有结束序列的运行也永不入选，当前运行额外按标识保护。
    """

    if prune_count < 0:
        raise ValueError("prune_count must be non-negative")
    ordered = sorted(intervals, key=lambda interval: interval.start_seq)
    if not ordered or prune_count == 0:
        return ()
    current_id = str(current_run_id) if current_run_id is not None else None
    candidates = [
        interval
        for interval in ordered[1:]
        if interval.end_seq is not None
        and interval.status != "running"
        and (current_id is None or str(interval.id) != current_id)
    ]
    return tuple(candidates[:prune_count])


@dataclass(frozen=True, slots=True)
class ModelInputProjection:
    """一次模型输入重建的消息投影及其观测事实。"""

    messages: list[ModelMessage]
    masked_observations: tuple[MaskedObservation, ...]
    pruned_run_ids: tuple[str, ...] = ()
    retention_window: int = RETENTION_WINDOW

    @property
    def attributes(self) -> dict[str, Any]:
        attributes = MaskingProjection(
            messages=self.messages,
            masked_observations=self.masked_observations,
        ).attributes
        attributes["pruned_runs"] = list(self.pruned_run_ids)
        attributes["retention_window"] = self.retention_window
        return attributes


def _title_from_message(text: str) -> str:
    title = " ".join(text.strip().split())
    if len(title) > MAX_TITLE_LENGTH:
        return f"{title[:MAX_TITLE_LENGTH]}..."
    return title or "新对话"


def fallback_title(text: str) -> str:
    """返回首条用户消息的公开列表回落标题。"""

    return _title_from_message(text)


def _tool_calls(message: ModelMessage) -> list[ToolCallBlock]:
    return [block for block in message.content if isinstance(block, ToolCallBlock)]


def _tool_results(message: ModelMessage) -> list[ToolResultBlock]:
    return [block for block in message.content if isinstance(block, ToolResultBlock)]


def _repair_tool_results(
    calls: Sequence[ToolCallBlock], existing: Sequence[ToolResultBlock]
) -> tuple[ToolResultBlock, ...]:
    """Return results in call order, synthesizing only absent results."""

    by_id = {result.tool_call_id: result for result in existing}
    repaired: list[ToolResultBlock] = []
    for call in calls:
        repaired.append(
            by_id.get(
                call.id,
                ToolResultBlock(
                    tool_call_id=call.id,
                    content=_ORPHAN_TOOL_RESULT,
                    is_error=True,
                ),
            )
        )
    known = {call.id for call in calls}
    repaired.extend(result for result in existing if result.tool_call_id not in known)
    return tuple(repaired)


def _project_messages_unmasked(
    rows: Iterable[MessageRow],
    *,
    round_trip_from_seq: int | None = None,
    skipped_seq_ranges: Sequence[tuple[int, int]] = (),
) -> list[ModelMessage]:
    """把存储消息投影为合法的 protocol-neutral 模型输入序列。

    ``system`` 不是合法的存储角色，投影中永远不输出。助手工具调用必须紧跟
    工具结果；如果进程在结果落库前停止，只在本次投影中合成协议错误结果，
    不修改来源行。``skipped_seq_ranges`` 只从投影中省略完整运行区间，
    不删除或修改来源行。
    """

    def is_skipped(seq: int) -> bool:
        return any(start <= seq <= end for start, end in skipped_seq_ranges)

    ordered = [row for row in sorted(rows, key=lambda row: row.seq) if not is_skipped(row.seq)]
    projected: list[ModelMessage] = []
    index = 0
    while index < len(ordered):
        row = ordered[index]
        if row.role == "system":
            index += 1
            continue
        if row.role == "tool" and (not projected or not _tool_calls(projected[-1])):
            index += 1
            continue
        current = row_to_model_message(
            row,
            include_round_trip=(round_trip_from_seq is not None and row.seq >= round_trip_from_seq),
        )
        projected.append(current)
        calls = _tool_calls(current)
        if calls:
            next_row = ordered[index + 1] if index + 1 < len(ordered) else None
            if next_row is not None and next_row.role == "tool":
                existing = row_to_model_message(next_row)
                results = _repair_tool_results(calls, _tool_results(existing))
                projected.append(ModelMessage(role="tool", content=results))
                index += 2
                continue
            projected.append(
                ModelMessage(
                    role="tool",
                    content=_repair_tool_results(calls, ()),
                )
            )
        index += 1
    return projected


def project_messages(
    rows: Iterable[MessageRow],
    *,
    round_trip_from_seq: int | None = None,
    skipped_ranges: Sequence[tuple[int, int]] = (),
    observation_keep: int | None = None,
    run_intervals: Sequence[RunInterval] = (),
    pruned_run_count: int = 0,
    current_run_id: UUID | str | None = None,
    skipped_seq_ranges: Sequence[tuple[int, int]] = (),
    retention_window: int | None = None,
) -> list[ModelMessage]:
    """重建模型输入，并在投影期掩蔽较早的工具观察。

    ``skipped_ranges`` / ``observation_keep`` 是领域接口；带 ``seq`` 和
    ``retention`` 的两个参数是早期调用方的兼容别名。
    """

    return project_messages_with_metadata(
        rows,
        round_trip_from_seq=round_trip_from_seq,
        skipped_ranges=skipped_ranges,
        observation_keep=observation_keep,
        run_intervals=run_intervals,
        pruned_run_count=pruned_run_count,
        current_run_id=current_run_id,
        skipped_seq_ranges=skipped_seq_ranges,
        retention_window=retention_window,
    ).messages


def project_messages_with_metadata(
    rows: Iterable[MessageRow],
    *,
    round_trip_from_seq: int | None = None,
    skipped_ranges: Sequence[tuple[int, int]] = (),
    observation_keep: int | None = None,
    run_intervals: Sequence[RunInterval] = (),
    pruned_run_count: int = 0,
    current_run_id: UUID | str | None = None,
    pruned_run_ids: Sequence[UUID | str] = (),
    skipped_seq_ranges: Sequence[tuple[int, int]] = (),
    retention_window: int | None = None,
) -> ModelInputProjection:
    """重建模型输入，并返回掩蔽与整块削减的观测事实。"""

    if skipped_ranges and skipped_seq_ranges:
        raise ValueError("pass only one of skipped_ranges and skipped_seq_ranges")
    if run_intervals and (skipped_ranges or skipped_seq_ranges):
        raise ValueError("pass either run_intervals or explicit skipped ranges")
    if observation_keep is not None and retention_window is not None:
        raise ValueError("pass only one of observation_keep and retention_window")
    selected_runs = select_prunable_run_intervals(
        run_intervals,
        prune_count=pruned_run_count,
        current_run_id=current_run_id,
    )
    effective_ranges = (
        tuple((run.start_seq, run.end_seq) for run in selected_runs if run.end_seq is not None)
        if run_intervals
        else skipped_ranges or skipped_seq_ranges
    )
    effective_keep = (
        observation_keep
        if observation_keep is not None
        else retention_window
        if retention_window is not None
        else RETENTION_WINDOW
    )
    projected = _project_messages_unmasked(
        rows,
        round_trip_from_seq=round_trip_from_seq,
        skipped_seq_ranges=effective_ranges,
    )
    masking = mask_tool_observations(projected, retention_window=effective_keep)
    selected_ids = tuple(str(run.id) for run in selected_runs)
    recorded_ids = tuple(str(run_id) for run_id in pruned_run_ids)
    return ModelInputProjection(
        messages=masking.messages,
        masked_observations=masking.masked_observations,
        pruned_run_ids=selected_ids or recorded_ids,
        retention_window=effective_keep,
    )


class ConversationService:
    """Business operations for sessions and messages.

    The service does not commit.  The caller owns the transaction boundary,
    which lets CRUD requests and streaming writes use different lifetimes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.repository = ConversationRepository(session)

    async def get_session(self, session_id: UUID) -> SessionDetail | None:
        session = await self.repository.get_session(session_id)
        if session is None:
            return None
        messages = await self.repository.list_messages(session_id)
        return SessionDetail(
            **session_to_view(session).model_dump(),
            messages=[row_to_view(message) for message in messages],
        )

    async def list_sessions(
        self,
        *,
        limit: int = 50,
        before_updated_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[SessionSummary]:
        rows = await self.repository.list_session_summaries(
            limit=limit, before_updated_at=before_updated_at, before_id=before_id
        )
        return [
            SessionSummary(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                message_count=count,
            )
            for session, count in rows
        ]

    async def rename_session(self, session_id: UUID, title: str | None) -> SessionRow | None:
        return await self.repository.rename_session(session_id, title)

    async def set_generated_title(
        self, session_id: UUID, *, expected_title: str | None, title: str
    ) -> bool:
        """写入首轮生成标题，但不覆盖已有标题。"""

        if expected_title is None:
            return await self.repository.set_title_if_missing(session_id, title)
        return await self.repository.replace_title_if_current(
            session_id, expected_title=expected_title, title=title
        )

    async def delete_session(self, session_id: UUID) -> bool:
        return bool(await self.repository.soft_delete_session(session_id))

    async def append_user_message(
        self, *, session_id: UUID, message_id: UUID, text: str
    ) -> MessageRow:
        """Create the session and its first message in the caller's transaction."""

        row, _ = await self.append_user_message_with_title_claim(
            session_id=session_id, message_id=message_id, text=text
        )
        return row

    async def append_user_message_with_title_claim(
        self, *, session_id: UUID, message_id: UUID, text: str
    ) -> tuple[MessageRow, bool]:
        """追加用户消息，并在同一事务内原子认领首轮标题生成。"""

        if not text.strip():
            raise ProtocolError("User message must not be empty")
        session = await self.repository.get_session_for_update(session_id)
        if session is None:
            session = await self.repository.upsert_session(session_id)
        title_claimed = session.title is None
        if title_claimed:
            await self.repository.rename_session(session_id, _title_from_message(text))
        row = await self.append_model_message(
            session_id=session_id,
            message_id=message_id,
            message=ModelMessage(role="user", content=(TextBlock(text=text),)),
        )
        return row, title_claimed

    async def append_model_message(
        self, *, session_id: UUID, message_id: UUID, message: ModelMessage
    ) -> MessageRow:
        if message.role == "system":
            raise ProtocolError("System prompts are runtime configuration, not conversation memory")
        content, opaque = encode_content(message)
        payload: dict[str, Any] | None
        if not opaque:
            payload = None
        elif len(opaque) == 1:
            payload = opaque[0]
        else:
            payload = {"blocks": opaque}
        seq = await self.repository.next_message_seq(session_id)
        row = await self.repository.insert_message(
            message_id=message_id,
            session_id=session_id,
            seq=seq,
            role=message.role,
            content=content,
            round_trip_payload=payload,
        )
        await self.repository.touch_session(session_id)
        return row

    async def rebuild_model_input(
        self,
        session_id: UUID,
        *,
        round_trip_from_seq: int | None = None,
        skipped_ranges: Sequence[tuple[int, int]] = (),
        observation_keep: int | None = None,
        run_intervals: Sequence[RunInterval] = (),
        pruned_run_count: int = 0,
        current_run_id: UUID | str | None = None,
        skipped_seq_ranges: Sequence[tuple[int, int]] = (),
        retention_window: int | None = None,
    ) -> list[ModelMessage]:
        rows = await self.repository.list_messages(session_id)
        return project_messages(
            rows,
            round_trip_from_seq=round_trip_from_seq,
            skipped_ranges=skipped_ranges,
            observation_keep=observation_keep,
            run_intervals=run_intervals,
            pruned_run_count=pruned_run_count,
            current_run_id=current_run_id,
            skipped_seq_ranges=skipped_seq_ranges,
            retention_window=retention_window,
        )

    async def rebuild_model_input_with_metadata(
        self, session_id: UUID, **projection_kwargs: Any
    ) -> ModelInputProjection:
        """重建模型输入并保留掩蔽/削减事实，供 observability 层记录。"""

        rows = await self.repository.list_messages(session_id)
        return project_messages_with_metadata(rows, **projection_kwargs)

    async def clear_round_trip_payload(
        self, *, session_id: UUID, message_ids: Collection[UUID]
    ) -> int:
        return int(
            await self.repository.clear_round_trip_payload(
                session_id=session_id, message_ids=message_ids
            )
        )

    @asynccontextmanager
    async def round_trip_payload_scope(
        self, *, session_factory: Any, session_id: UUID
    ) -> AsyncIterator[set[UUID]]:
        """在运行终态清空本次运行登记的 opaque payload。

        调用方在每次增量写入助手消息后把行标识加入集合；``finally`` 覆盖成功、
        失败和 ``CancelledError``（客户端断连）三条终态路径。清理使用短事务，
        不借用持续流式请求的数据库 session。
        """

        message_ids: set[UUID] = set()
        try:
            yield message_ids
        finally:
            await self.short_transaction_clear_round_trip_payload(
                session_factory=session_factory,
                session_id=session_id,
                message_ids=message_ids,
            )

    async def short_transaction_append(
        self, *, session_factory: Any, session_id: UUID, message_id: UUID, message: ModelMessage
    ) -> MessageRow:
        """Persist one streaming message without borrowing a request session."""

        async with session_factory() as session, session.begin():
            service = ConversationService(session)
            return await service.append_model_message(
                session_id=session_id, message_id=message_id, message=message
            )

    async def short_transaction_clear_round_trip_payload(
        self, *, session_factory: Any, session_id: UUID, message_ids: Collection[UUID]
    ) -> int:
        """Clear one run's opaque payloads in a short terminal transaction."""

        async with session_factory() as session, session.begin():
            service = ConversationService(session)
            return await service.clear_round_trip_payload(
                session_id=session_id, message_ids=message_ids
            )
