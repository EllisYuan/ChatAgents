"""模型接入层：端点档案与配置。

`UserEndpointConfig`（用户自定义的 Pydantic 模型）不在此导出——按设计只活在
`llm/` 内部，外部模块不该拿到这个类型。
"""

from .effort import EFFORT_TIERS, EffortTier
from .errors import ConfigError, ProfileUnavailableError
from .events import (
    ModelCallCompleted,
    ModelEvent,
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    Usage,
    UsageState,
)
from .message import (
    ContentBlock,
    ModelMessage,
    OpaqueBlock,
    Role,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from .port import ModelPort, get_model_port
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
    "EFFORT_TIERS",
    "PROTOCOLS",
    "ConfigError",
    "ContentBlock",
    "EffortTier",
    "EndpointProfile",
    "ModelCallCompleted",
    "ModelEvent",
    "ModelMessage",
    "ModelPort",
    "OpaqueBlock",
    "ProfileUnavailableError",
    "Protocol",
    "ReasoningDelta",
    "ResolvedProfiles",
    "Role",
    "ServerEndpointsConfig",
    "ServerProfileDefinition",
    "Settings",
    "TextBlock",
    "TextDelta",
    "ToolCallArgsDelta",
    "ToolCallBlock",
    "ToolCallCompleted",
    "ToolCallStarted",
    "ToolResultBlock",
    "UnavailableProfile",
    "Usage",
    "UsageState",
    "build_available_profiles",
    "get_model_port",
    "load_server_endpoints",
    "resolve_profiles",
]
