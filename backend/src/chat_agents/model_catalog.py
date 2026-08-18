"""模型清单的纯领域类型与持久化边界。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

ModelCatalogSource = Literal["discovered", "fallback"]


@dataclass(frozen=True, slots=True)
class ModelItem:
    """OpenAI ``/v1/models`` 清单项的最小内部表示。"""

    model_id: str
    owned_by: str


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """一次清单查询给 API 层使用的结果，不包含任何密钥信息。"""

    models: tuple[ModelItem, ...]
    source: ModelCatalogSource
    last_success_at: datetime | None
    error: str | None = None


class ModelCatalogStore(Protocol):
    async def load(
        self, endpoint_profile: str
    ) -> tuple[tuple[ModelItem, ...], datetime | None]: ...

    async def replace(
        self,
        endpoint_profile: str,
        models: tuple[ModelItem, ...],
        discovered_at: datetime,
    ) -> None: ...
