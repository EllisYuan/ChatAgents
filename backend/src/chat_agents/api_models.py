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


class ModelProfileChoice(ModelProfileView):
    """档案枚举里的一项——档案层状态，加上它会用哪两个模型（issue #82）。

    模型标识只在这个响应里出现，不加进 ``ModelProfileView``：清单响应里的那个
    ``profile`` 字段答的是「这份档案能不能用」，模型标识对它是**结构性不存在**，
    摆一个恒为 ``null`` 的字段会让读者以为「这次没取到、下次可能有」（ADR-0023）。

    这里的两个字段则是「可能没有值」：``unavailable`` 的档案连密钥都没配，谈不上
    会用哪个模型，此时为 ``None``——``status`` 就是它自己的可用性状态字段，不必再
    配第二个。它们是 ``endpoints.yaml`` 里的配置不是密钥，不涉及 ADR-0029。
    """

    main_model: str | None = None
    auxiliary_model: str | None = None


class ModelProfilesResponse(BaseModel):
    """服务端已配置的全部端点档案及其可用性（issue #70：前端选单需要枚举档案）。

    ``default_profile`` 让前端能判断「用户选的档案是否偏离默认」，据此决定要不要
    在运行请求里带上档案覆盖（issue #82）——没有它，前端只能靠「列表第一个就是
    默认」这类猜测，而那与服务端的 ``default_profile`` 并无关系。
    """

    profiles: list[ModelProfileChoice] = Field(default_factory=list)
    default_profile: str


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
