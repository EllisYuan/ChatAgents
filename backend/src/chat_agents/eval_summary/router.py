"""站点级只读评测展示面路由（issue #66，ADR-0028）。

只读、站点级——不进聊天界面（会话/运行相关路由见 ``conversation`` 与
``observability``）。正好四个数字，数据来自磁盘上的评测产出文件，缺失时
优雅缺省，从不在这里硬编码分数。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..llm.settings import Settings
from .models import EvalSummaryView, eval_summary_view
from .store import EvalSummaryStore

router = APIRouter(prefix="/api", tags=["evals"])


def get_eval_summary_store() -> EvalSummaryStore:
    settings = Settings()
    return EvalSummaryStore(settings.eval_reports_dir)


Store = Annotated[EvalSummaryStore, Depends(get_eval_summary_store)]


@router.get("/evals/summary", response_model=EvalSummaryView)
async def get_eval_summary(store: Store) -> EvalSummaryView:
    return eval_summary_view(store.read())
