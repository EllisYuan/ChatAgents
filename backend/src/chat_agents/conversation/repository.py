"""Data access for the ``app`` conversation tables.

This class deliberately contains no transaction management or business rules.
Callers provide an ``AsyncSession`` and decide when it is committed.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.app import Message, Session
from ..exceptions import SessionNotFound


def _session_filters(*, before_updated_at: datetime | None, before_id: UUID | None) -> list[Any]:
    filters: list[Any] = [Session.deleted_at.is_(None)]
    if before_updated_at is not None:
        cursor = Session.updated_at < before_updated_at
        if before_id is not None:
            cursor = or_(
                cursor,
                and_(Session.updated_at == before_updated_at, Session.id < before_id),
            )
        filters.append(cursor)
    return filters


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_session(self, session_id: UUID) -> Session | None:
        result = await self.session.execute(
            select(Session).where(Session.id == session_id, Session.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        *,
        limit: int = 50,
        before_updated_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[Session]:
        filters = _session_filters(before_updated_at=before_updated_at, before_id=before_id)
        result = await self.session.execute(
            select(Session)
            .where(*filters)
            .order_by(Session.updated_at.desc(), Session.id.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_session_summaries(
        self,
        *,
        limit: int = 50,
        before_updated_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[tuple[Session, int]]:
        filters = _session_filters(before_updated_at=before_updated_at, before_id=before_id)
        result = await self.session.execute(
            select(Session, func.count(Message.id))
            .outerjoin(Message, Message.session_id == Session.id)
            .where(*filters)
            .group_by(Session.id)
            .order_by(Session.updated_at.desc(), Session.id.desc())
            .limit(limit)
        )
        return [(row, int(count)) for row, count in result.all()]

    async def upsert_session(self, session_id: UUID) -> Session:
        """Insert a live session if absent, without reviving a soft-deleted row."""

        statement = (
            insert(Session)
            .values(id=session_id)
            .on_conflict_do_nothing(index_elements=[Session.id])
        )
        await self.session.execute(statement)
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        row = result.scalar_one()
        if row.deleted_at is not None:
            raise SessionNotFound("Cannot append to a deleted session")
        return row

    async def rename_session(self, session_id: UUID, title: str | None) -> Session | None:
        row = await self.get_session(session_id)
        if row is None:
            return None
        row.title = title
        await self.session.flush()
        return row

    async def soft_delete_session(self, session_id: UUID) -> bool:
        result = await self.session.execute(
            update(Session)
            .where(Session.id == session_id, Session.deleted_at.is_(None))
            .values(deleted_at=func.now())
        )
        return getattr(result, "rowcount", 0) == 1

    async def list_messages(self, session_id: UUID) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .join(Session, Session.id == Message.session_id)
            .where(Message.session_id == session_id, Session.deleted_at.is_(None))
            .order_by(Message.seq.asc())
        )
        return list(result.scalars())

    async def get_message(self, message_id: UUID) -> Message | None:
        result = await self.session.execute(
            select(Message)
            .join(Session, Session.id == Message.session_id)
            .where(Message.id == message_id, Session.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def next_message_seq(self, session_id: UUID) -> int:
        lock = await self.session.execute(
            select(Session.id)
            .where(Session.id == session_id, Session.deleted_at.is_(None))
            .with_for_update()
        )
        if lock.scalar_one_or_none() is None:
            raise SessionNotFound("Cannot append to a missing or deleted session")
        result = await self.session.execute(
            select(func.coalesce(func.max(Message.seq), -1) + 1).where(
                Message.session_id == session_id
            )
        )
        return int(result.scalar_one())

    async def insert_message(
        self,
        *,
        message_id: UUID,
        session_id: UUID,
        seq: int,
        role: str,
        content: list[dict],
        round_trip_payload: dict | None,
    ) -> Message:
        row = Message(
            id=message_id,
            session_id=session_id,
            seq=seq,
            role=role,
            content=content,
            round_trip_payload=round_trip_payload,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def clear_round_trip_payload(
        self, *, session_id: UUID, message_ids: Collection[UUID]
    ) -> int:
        if not message_ids:
            return 0
        result = await self.session.execute(
            update(Message)
            .where(
                Message.session_id == session_id,
                Message.id.in_(message_ids),
                Message.session_id.in_(
                    select(Session.id).where(Session.id == session_id, Session.deleted_at.is_(None))
                ),
            )
            .values(round_trip_payload=None)
        )
        return getattr(result, "rowcount", 0)

    async def touch_session(self, session_id: UUID, *, at: datetime | None = None) -> None:
        values = {"updated_at": at if at is not None else func.now()}
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id, Session.deleted_at.is_(None))
            .values(**values)
        )
