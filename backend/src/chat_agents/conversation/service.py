"""Conversation rules and model-input projection."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.app import Message as MessageRow
from ..db.app import Session as SessionRow
from ..exceptions import ProtocolError
from ..llm.message import ModelMessage, TextBlock, ToolCallBlock, ToolResultBlock
from .models import (
    SessionDetail,
    SessionSummary,
    encode_content,
    row_to_model_message,
    row_to_view,
    session_to_view,
)
from .repository import ConversationRepository

_ORPHAN_TOOL_RESULT = "Tool call ended before a result was recorded."
_TITLE_LIMIT = 30


def _title_from_message(text: str) -> str:
    title = " ".join(text.strip().split())
    if len(title) > _TITLE_LIMIT:
        return f"{title[:_TITLE_LIMIT]}..."
    return title or "新对话"


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


def project_messages(
    rows: Iterable[MessageRow], *, round_trip_from_seq: int | None = None
) -> list[ModelMessage]:
    """Project stored messages into a valid protocol-neutral model sequence.

    ``system`` is intentionally not a valid stored role and is never emitted.
    An assistant tool call must be immediately followed by a tool result.  If a
    process stopped before that result was persisted, a synthetic protocol
    error result is inserted in this projection only; the source row is never
    changed.
    """

    ordered = sorted(rows, key=lambda row: row.seq)
    projected: list[ModelMessage] = []
    index = 0
    while index < len(ordered):
        row = ordered[index]
        if row.role == "system":
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

    async def delete_session(self, session_id: UUID) -> bool:
        return await self.repository.soft_delete_session(session_id)

    async def append_user_message(
        self, *, session_id: UUID, message_id: UUID, text: str
    ) -> MessageRow:
        """Create the session and its first message in the caller's transaction."""

        if not text.strip():
            raise ProtocolError("User message must not be empty")
        session = await self.repository.get_session(session_id)
        if session is None:
            session = await self.repository.upsert_session(session_id)
        if session.title is None:
            await self.repository.rename_session(session_id, _title_from_message(text))
        return await self.append_model_message(
            session_id=session_id,
            message_id=message_id,
            message=ModelMessage(role="user", content=(TextBlock(text=text),)),
        )

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
        self, session_id: UUID, *, round_trip_from_seq: int | None = None
    ) -> list[ModelMessage]:
        rows = await self.repository.list_messages(session_id)
        return project_messages(rows, round_trip_from_seq=round_trip_from_seq)

    async def clear_round_trip_payload(
        self, *, session_id: UUID, message_ids: Collection[UUID]
    ) -> int:
        return await self.repository.clear_round_trip_payload(
            session_id=session_id, message_ids=message_ids
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
