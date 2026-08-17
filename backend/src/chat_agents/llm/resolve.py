"""端点档案解析——服务端预设与用户自定义交汇于同一个 EndpointProfile 类型。

`resolve_profiles` 是模型角色分离（ADR-0012、ADR-0014）在配置层的落点：返回一份
端点档案，加两个独立的模型标识。auxiliary 未指定时回落为与 main 相同，回落必须
留痕——`auxiliary_model_source` 就是那道痕迹，供上层（观测）决定要不要记进跨度。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .errors import ProfileUnavailableError
from .profile import EndpointProfile
from .server_config import ServerEndpointsConfig, build_available_profiles
from .user_config import UserEndpointConfig

AuxiliaryModelSource = Literal["specified", "fallback_to_main"]


@dataclass(frozen=True, slots=True)
class ResolvedProfiles:
    profile: EndpointProfile
    main_model: str
    auxiliary_model: str
    auxiliary_model_source: AuxiliaryModelSource


def resolve_profiles(
    server_config: ServerEndpointsConfig,
    user_config: UserEndpointConfig | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedProfiles:
    """用户填了优先用用户的，未填才降级到服务端预设。"""
    if user_config is not None:
        profile = EndpointProfile(
            name="user",
            protocol=user_config.protocol,
            base_url=user_config.base_url,
            auth_field=user_config.auth_field,
            api_key=user_config.api_key,
        )
        main_model = user_config.main_model
        auxiliary_requested = user_config.auxiliary_model
    else:
        available, unavailable = build_available_profiles(server_config, env)
        default_name = server_config.default_profile
        if default_name in unavailable:
            raise ProfileUnavailableError(
                f"默认端点档案 {default_name!r} 不可用：{unavailable[default_name].reason}"
            )
        profile = available[default_name]
        definition = server_config.profiles[default_name]
        main_model = definition.main_model
        auxiliary_requested = definition.auxiliary_model

    auxiliary_model_source: AuxiliaryModelSource
    if auxiliary_requested:
        auxiliary_model = auxiliary_requested
        auxiliary_model_source = "specified"
    else:
        auxiliary_model = main_model
        auxiliary_model_source = "fallback_to_main"

    return ResolvedProfiles(
        profile=profile,
        main_model=main_model,
        auxiliary_model=auxiliary_model,
        auxiliary_model_source=auxiliary_model_source,
    )
