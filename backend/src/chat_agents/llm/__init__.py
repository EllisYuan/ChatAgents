"""模型接入层：端点档案与配置。

`UserEndpointConfig`（用户自定义的 Pydantic 模型）不在此导出——按设计只活在
`llm/` 内部，外部模块不该拿到这个类型。
"""

from .errors import ConfigError, ProfileUnavailableError
from .profile import EndpointProfile
from .protocol import DEFAULT_PROTOCOL, PROTOCOLS, Protocol
from .resolve import ResolvedProfiles, resolve_profiles
from .server_config import (
    ServerEndpointsConfig,
    ServerProfileDefinition,
    UnavailableProfile,
    build_available_profiles,
    load_server_endpoints,
)
from .settings import Settings

__all__ = [
    "DEFAULT_PROTOCOL",
    "PROTOCOLS",
    "ConfigError",
    "EndpointProfile",
    "ProfileUnavailableError",
    "Protocol",
    "ResolvedProfiles",
    "ServerEndpointsConfig",
    "ServerProfileDefinition",
    "Settings",
    "UnavailableProfile",
    "build_available_profiles",
    "load_server_endpoints",
    "resolve_profiles",
]
