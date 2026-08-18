"""模型接入层：端点档案与配置。

`UserEndpointConfig`（用户自定义的 Pydantic 模型）不在此导出——按设计只活在
`llm/` 内部，外部模块不该拿到这个类型。
"""

from ..model_catalog import ModelCatalogSource
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
from .model_discovery import (
    MODEL_DISCOVERY_ENABLED_ENV,
    MODEL_DISCOVERY_INTERVAL_SECONDS,
    MODEL_DISCOVERY_TIMEOUT_SECONDS,
    InMemoryModelCatalogStore,
    ModelCatalog,
    ModelDiscoveryError,
    ModelDiscoveryService,
    ModelItem,
    discover_openai_models,
    is_model_discovery_enabled,
    model_discovery_lifespan,
    models_url,
    periodic_model_refresh,
    start_model_refresh_task,
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
    "MODEL_DISCOVERY_ENABLED_ENV",
    "MODEL_DISCOVERY_INTERVAL_SECONDS",
    "MODEL_DISCOVERY_TIMEOUT_SECONDS",
    "PROTOCOLS",
    "ConfigError",
    "ContentBlock",
    "EffortTier",
    "EndpointProfile",
    "InMemoryModelCatalogStore",
    "ModelCallCompleted",
    "ModelCatalog",
    "ModelCatalogSource",
    "ModelDiscoveryError",
    "ModelDiscoveryService",
    "ModelEvent",
    "ModelItem",
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
    "discover_openai_models",
    "get_model_port",
    "is_model_discovery_enabled",
    "load_server_endpoints",
    "model_discovery_lifespan",
    "models_url",
    "periodic_model_refresh",
    "resolve_profiles",
    "start_model_refresh_task",
]
