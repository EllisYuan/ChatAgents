"""用户自定义端点配置——前端高级选项那一层，只活在 llm/ 内部，不外泄。"""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..validation import (
    MAX_AUTH_FIELD_LENGTH,
    MAX_BASE_URL_LENGTH,
    MAX_MODEL_IDENTIFIER_LENGTH,
    validate_auth_field,
    validate_base_url,
    validate_model_identifier,
)
from .protocol import DEFAULT_PROTOCOL, Protocol


class UserEndpointConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol: Protocol = DEFAULT_PROTOCOL
    base_url: str = Field(max_length=MAX_BASE_URL_LENGTH)
    auth_field: str = Field(max_length=MAX_AUTH_FIELD_LENGTH)
    api_key: SecretStr
    main_model: str = Field(max_length=MAX_MODEL_IDENTIFIER_LENGTH)
    auxiliary_model: str | None = Field(default=None, max_length=MAX_MODEL_IDENTIFIER_LENGTH)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return validate_base_url(value)

    @field_validator("auth_field")
    @classmethod
    def _validate_auth_field(cls, value: str) -> str:
        return validate_auth_field(value)

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("api_key 不能是空白字符串")
        return value

    @field_validator("main_model")
    @classmethod
    def _validate_main_model(cls, value: str) -> str:
        return validate_model_identifier(value, field="main_model")

    @field_validator("auxiliary_model")
    @classmethod
    def _validate_auxiliary_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_model_identifier(value, field="auxiliary_model")
