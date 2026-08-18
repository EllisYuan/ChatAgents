"""模型清单发现任务的 app-schema 持久化边界。

这不是业务 CRUD：只有 discovery service 在一次成功发现后整体替换清单。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..model_catalog import ModelCatalogStore, ModelItem
from .app import DiscoveredModel, DiscoveredModelRefresh


class SqlAlchemyModelCatalogStore(ModelCatalogStore):
    """``app.discovered_model`` 与其批次元数据的最小读写封装。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def load(self, endpoint_profile: str) -> tuple[tuple[ModelItem, ...], datetime | None]:
        async with self._session_factory() as session:
            session = cast(AsyncSession, session)
            rows = (
                await session.scalars(
                    select(DiscoveredModel)
                    .where(DiscoveredModel.endpoint_profile == endpoint_profile)
                    .order_by(DiscoveredModel.model_id)
                )
            ).all()
            refresh = await session.scalar(
                select(DiscoveredModelRefresh).where(
                    DiscoveredModelRefresh.endpoint_profile == endpoint_profile
                )
            )
        models = tuple(ModelItem(model_id=row.model_id, owned_by=row.owned_by) for row in rows)
        last_success_at = (
            refresh.last_success_at
            if refresh is not None
            else max((row.discovered_at for row in rows), default=None)
        )
        return models, last_success_at

    async def replace(
        self,
        endpoint_profile: str,
        models: tuple[ModelItem, ...],
        discovered_at: datetime,
    ) -> None:
        async with self._session_factory() as session:
            session = cast(AsyncSession, session)
            async with session.begin():
                await session.execute(
                    delete(DiscoveredModel).where(
                        DiscoveredModel.endpoint_profile == endpoint_profile
                    )
                )
                session.add_all(
                    [
                        DiscoveredModel(
                            endpoint_profile=endpoint_profile,
                            model_id=model.model_id,
                            owned_by=model.owned_by,
                            discovered_at=discovered_at,
                        )
                        for model in models
                    ]
                )
                refresh = await session.get(DiscoveredModelRefresh, endpoint_profile)
                if refresh is None:
                    session.add(
                        DiscoveredModelRefresh(
                            endpoint_profile=endpoint_profile,
                            last_success_at=discovered_at,
                        )
                    )
                else:
                    refresh.last_success_at = discovered_at
