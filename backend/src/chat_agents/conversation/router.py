"""HTTP routes for the business conversation surface."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..exceptions import SessionNotFound
from .models import (
    MessageView,
    RenameSessionRequest,
    SessionDetail,
    SessionSummary,
    SessionView,
    UserMessageRequest,
    row_to_view,
    session_to_view,
)
from .service import ConversationService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
Db = Annotated[AsyncSession, Depends(get_db)]


def _service(session: AsyncSession) -> ConversationService:
    return ConversationService(session)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    session: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_updated_at: datetime | None = None,
    before_id: UUID | None = None,
) -> list[SessionSummary]:
    return await _service(session).list_sessions(
        limit=limit, before_updated_at=before_updated_at, before_id=before_id
    )


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: UUID, session: Db) -> SessionDetail:
    result = await _service(session).get_session(session_id)
    if result is None:
        raise SessionNotFound(f"Session {session_id} was not found")
    return result


@router.get("/{session_id}/messages", response_model=list[MessageView])
async def list_messages(session_id: UUID, session: Db) -> list[MessageView]:
    result = await _service(session).get_session(session_id)
    if result is None:
        raise SessionNotFound(f"Session {session_id} was not found")
    return result.messages


@router.post(
    "/{session_id}/messages", response_model=MessageView, status_code=status.HTTP_201_CREATED
)
async def append_user_message(
    session_id: UUID, request: UserMessageRequest, session: Db
) -> MessageView:
    async with session.begin():
        row = await _service(session).append_user_message(
            session_id=session_id, message_id=request.id, text=request.content
        )
    return row_to_view(row)


@router.patch("/{session_id}", response_model=SessionView)
async def rename_session(
    session_id: UUID, request: RenameSessionRequest, session: Db
) -> SessionView:
    async with session.begin():
        row = await _service(session).rename_session(session_id, request.title)
    if row is None:
        raise SessionNotFound(f"Session {session_id} was not found")
    return session_to_view(row)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: UUID, session: Db) -> Response:
    async with session.begin():
        deleted = await _service(session).delete_session(session_id)
    if not deleted:
        raise SessionNotFound(f"Session {session_id} was not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
