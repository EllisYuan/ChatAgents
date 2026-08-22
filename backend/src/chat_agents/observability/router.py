"""HTTP 查询路由：观测面与业务面分开（ADR-0022）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .models import RunDetail, RunSummary, run_detail_payload
from .repository import ObservabilityRepository

router = APIRouter(prefix="/api", tags=["observability"])
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/sessions/{session_id}/runs", response_model=list[RunSummary])
async def list_session_runs(session_id: UUID, session: Db) -> list[RunSummary]:
    """返回观测侧运行骨架；不会读取 ``app.session`` 或 ``app.message``。"""

    return await ObservabilityRepository(session).list_runs(session_id)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: UUID, session: Db) -> RunDetail | JSONResponse:
    """返回一条运行的配置、聚合用量和完整跨度树。"""

    detail = await ObservabilityRepository(session).get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return JSONResponse(content=run_detail_payload(detail))
