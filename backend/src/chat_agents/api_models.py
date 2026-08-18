"""REST 契约模型；所有字段由 FastAPI 的 OpenAPI 输出生成。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .llm.protocol import DEFAULT_PROTOCOL, Protocol


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ProblemDetails(BaseModel):
    """RFC 9457 问题详情及本项目的三个诊断扩展。"""

    type: str
    title: str
    detail: str
    status: int
    upstream_error: Any | None = None
    run_id: str | None = None
    key_source: str | None = None


class ModelItemView(BaseModel):
    """供前端自行按 owned_by 分组的平铺模型项。"""

    id: str
    owned_by: str
    endpoint_profile: str


class ModelProfileView(BaseModel):
    """模型档案层状态；不可用不等于模型清单发现失败。"""

    name: str
    status: Literal["available", "unavailable"]
    reason: str | None = None


class ModelsResponse(BaseModel):
    models: list[ModelItemView] = Field(default_factory=list)
    endpoint_profile: str
    profile: ModelProfileView
    source: Literal["discovered", "fallback"]
    last_success_at: datetime | None = None
    error: str | None = None


class ModelRefreshRequest(BaseModel):
    """刷新服务端档案，或临时发现一个用户自定义端点。"""

    model_config = ConfigDict(extra="forbid")

    endpoint_profile: str | None = None
    protocol: Protocol = DEFAULT_PROTOCOL
    base_url: str | None = None
    auth_field: str = "Authorization"
    api_key: SecretStr | None = None


class ModelRefreshResponse(ModelsResponse):
    pass
