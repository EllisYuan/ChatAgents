"""模型覆盖——一次运行可以偏离服务端预设的那些字段。

`resolve_profiles` 的语义是「预设打底 + 逐字段覆盖」，因此这里的字段**全部可选**：
传了就用，没传就落回预设档案的对应值。整个对象为 `None` 时行为与没有覆盖完全一致。

端点来源二选一，判别式与 `ModelRefreshRequest` 同款——以 `base_url` 是否为 `None`
区分：给了 `base_url` 就是用户自带的中转站（连同密钥一起自带），否则用服务端预设
档案（`endpoint_profile` 指定用哪一个，不指定就是 `default_profile`）。模型标识两
条来源下都能单独覆盖，「用服务端的档案与密钥、只换模型」正是最常用的那一档。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from ..validation import (
    MAX_AUTH_FIELD_LENGTH,
    MAX_BASE_URL_LENGTH,
    MAX_MODEL_IDENTIFIER_LENGTH,
    MAX_PROFILE_NAME_LENGTH,
    validate_auth_field,
    validate_base_url,
    validate_identifier,
    validate_model_identifier,
)
from .endpoint_address import AddressMode
from .protocol import Protocol


class ModelOverride(BaseModel):
    """`POST /api/runs` 可选的模型覆盖；不落库、不进任何进程级状态，只活一次运行。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint_profile: str | None = Field(default=None, max_length=MAX_PROFILE_NAME_LENGTH)
    protocol: Protocol | None = None
    base_url: str | None = Field(default=None, max_length=MAX_BASE_URL_LENGTH)
    # 省略即 `auto`：根地址自动补 `/v1`，已有 path 当作 API 前缀。`True` 表示
    # `base_url` 就是最终生成 URL（issue #83）。
    full_url: bool | None = None
    auth_field: str | None = Field(default=None, max_length=MAX_AUTH_FIELD_LENGTH)
    api_key: SecretStr | None = None
    main_model: str | None = Field(default=None, max_length=MAX_MODEL_IDENTIFIER_LENGTH)
    auxiliary_model: str | None = Field(default=None, max_length=MAX_MODEL_IDENTIFIER_LENGTH)

    @property
    def is_custom_endpoint(self) -> bool:
        """端点来源的判别式——与 `ModelRefreshRequest` 用的是同一条。"""

        return self.base_url is not None

    @property
    def address_mode(self) -> AddressMode:
        """自定义端点的地址解释；服务端预设不走这里（仍是 `sdk_native`）。"""

        return "full" if self.full_url else "auto"

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
    def _validate_auth_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_auth_field(value)

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("api_key 不能是空白字符串")
        return value

    @field_validator("main_model")
    @classmethod
    def _validate_main_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_model_identifier(value, field="main_model")

    @field_validator("auxiliary_model")
    @classmethod
    def _validate_auxiliary_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_model_identifier(value, field="auxiliary_model")

    @model_validator(mode="after")
    def _validate_endpoint_source(self) -> ModelOverride:
        """两条端点来源不能混着传，自定义端点必须自带密钥与模型标识。

        没有 `base_url` 却带 `protocol` / `auth_field` / `api_key` 一律拒绝，而不是
        默默忽略——静默忽略用户填的字段正是本模块要修的那类失效（issue #82）。
        自定义端点不给 `main_model` 同理：拿服务端预设档案的模型标识去打用户自己的
        中转站是系统代选（ADR-0014），宁可 422。
        """

        if self.base_url is None:
            for field in ("protocol", "auth_field", "api_key", "full_url"):
                if getattr(self, field) is not None:
                    raise ValueError(f"{field} 只能和 base_url 一起使用")
            return self
        if self.endpoint_profile is not None:
            raise ValueError("base_url 与 endpoint_profile 是二选一的端点来源")
        if self.api_key is None:
            raise ValueError("自定义端点缺少 api_key")
        if self.main_model is None:
            raise ValueError("自定义端点缺少 main_model")
        return self
