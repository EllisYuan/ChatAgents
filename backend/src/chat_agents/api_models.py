"""REST 契约模型；所有字段由 FastAPI 的 OpenAPI 输出生成。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .llm.protocol import DEFAULT_PROTOCOL, Protocol
from .validation import (
    MAX_AUTH_FIELD_LENGTH,
    MAX_BASE_URL_LENGTH,
    MAX_PROFILE_NAME_LENGTH,
    validate_auth_field,
    validate_base_url,
    validate_identifier,
)


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

    endpoint_profile: str | None = Field(default=None, max_length=MAX_PROFILE_NAME_LENGTH)
    protocol: Protocol = DEFAULT_PROTOCOL
    base_url: str | None = Field(default=None, max_length=MAX_BASE_URL_LENGTH)
    auth_field: str = Field(default="Authorization", max_length=MAX_AUTH_FIELD_LENGTH)
    api_key: SecretStr | None = None

    @field_validator("endpoint_profile")
    @classmethod
    def _validate_endpoint_profile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_identifier(
            value, field="endpoint_profile", max_length=MAX_PROFILE_NAME_LENGTH
        )

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_base_url(value)

    @field_validator("auth_field")
    @classmethod
    def _validate_auth_field(cls, value: str) -> str:
        return validate_auth_field(value)

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("api_key 不能是空白字符串")
        return value

    @model_validator(mode="after")
    def _validate_custom_endpoint(self) -> ModelRefreshRequest:
        if self.base_url is None and self.api_key is not None:
            raise ValueError("api_key 只能和 base_url 一起使用")
        if self.base_url is not None and self.api_key is None:
            raise ValueError("自定义端点缺少 api_key")
        return self


class ModelRefreshResponse(ModelsResponse):
    pass
