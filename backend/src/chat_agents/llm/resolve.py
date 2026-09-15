"""端点档案解析——服务端预设与用户覆盖交汇于同一个 EndpointProfile 类型。

`resolve_profiles` 是模型角色分离（ADR-0012、ADR-0014）在配置层的落点：返回一份
端点档案，加两个独立的模型标识。auxiliary 未指定时回落为与 main 相同，回落必须
留痕——`auxiliary_model_source` 就是那道痕迹，供上层（观测）决定要不要记进跨度。

语义是**预设打底 + 逐字段覆盖**，不是「用户配置」与「服务端预设」二选一：ADR-0014
说「模型由用户选定」，而用户最常见的选定动作是「就用你的档案与密钥，只换个型号」
（issue #82）。二选一表达不了这一档——那会逼用户为了换模型而自带一份密钥。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .errors import ProfileUnavailableError
from .override import ModelOverride
from .profile import EndpointProfile
from .server_config import ServerEndpointsConfig, build_available_profiles

AuxiliaryModelSource = Literal["specified", "fallback_to_main"]
KeySource = Literal["user_provided", "server_default"]


@dataclass(frozen=True, slots=True)
class ResolvedProfiles:
    profile: EndpointProfile
    main_model: str
    auxiliary_model: str
    auxiliary_model_source: AuxiliaryModelSource
    key_source: KeySource


def resolve_profiles(
    server_config: ServerEndpointsConfig,
    override: ModelOverride | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedProfiles:
    """服务端预设打底，用户覆盖逐字段生效；`override` 为 ``None`` 即纯预设。"""
    if override is not None and override.is_custom_endpoint:
        # 自带中转站就整份自带：base_url、鉴权与密钥全部来自用户，一个字段都不
        # 从预设兜底。静默拿服务端密钥去打用户的中转站会让他以为自己的配置是对
        # 的（ADR-0029 的失败态零例外同理），因此 `ModelOverride` 已在校验层要求
        # 自定义端点必须自带 api_key 与 main_model，这里两个断言只是把它说明白。
        assert override.base_url is not None
        assert override.api_key is not None
        assert override.main_model is not None
        profile = EndpointProfile(
            name="custom",
            protocol=override.protocol or "openai_responses",
            base_url=override.base_url,
            auth_field=override.auth_field or "Authorization",
            api_key=override.api_key,
        )
        main_model = override.main_model
        auxiliary_requested = override.auxiliary_model
        key_source: KeySource = "user_provided"
    else:
        available, unavailable = build_available_profiles(server_config, env)
        profile_name = (
            override.endpoint_profile
            if override is not None and override.endpoint_profile is not None
            else server_config.default_profile
        )
        if profile_name in unavailable:
            raise ProfileUnavailableError(
                f"端点档案 {profile_name!r} 不可用：{unavailable[profile_name].reason}"
            )
        if profile_name not in available:
            raise ProfileUnavailableError(f"未知端点档案：{profile_name}")
        profile = available[profile_name]
        definition = server_config.profiles[profile_name]
        main_model = definition.main_model
        auxiliary_requested = definition.auxiliary_model
        if override is not None:
            main_model = override.main_model or main_model
            # 用户显式填了 auxiliary 就用他的；没填才落回档案里那个（可能也没有，
            # 于是下面回落到 main）。这里不用 `or` 链把两者混起来读——顺序是
            # 「用户 > 档案 > main」，写成分支比写成一串 `or` 更难读错。
            if override.auxiliary_model is not None:
                auxiliary_requested = override.auxiliary_model
        key_source = "server_default"

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
        key_source=key_source,
    )
