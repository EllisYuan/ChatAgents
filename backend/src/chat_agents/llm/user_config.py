"""用户自定义端点配置——前端高级选项那一层，只活在 llm/ 内部，不外泄。"""

from pydantic import BaseModel, ConfigDict, SecretStr

from .protocol import DEFAULT_PROTOCOL, Protocol


class UserEndpointConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol: Protocol = DEFAULT_PROTOCOL
    base_url: str
    auth_field: str
    api_key: SecretStr
    main_model: str
    auxiliary_model: str | None = None
