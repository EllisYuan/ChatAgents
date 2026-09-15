"""resolve_profiles：预设打底 + 逐字段覆盖，两条构造路径交汇于同一个 EndpointProfile。"""

from pathlib import Path

import pytest
from chat_agents.llm.errors import ProfileUnavailableError
from chat_agents.llm.override import ModelOverride
from chat_agents.llm.profile import EndpointProfile
from chat_agents.llm.resolve import resolve_profiles
from chat_agents.llm.server_config import ServerEndpointsConfig, load_server_endpoints
from pydantic import SecretStr

YAML = """
default_profile: anthropic-official
endpoints:
  - name: anthropic-official
    protocol: anthropic_messages
    base_url: https://api.anthropic.com
    auth_field: x-api-key
    auth_secret_ref: ANTHROPIC_API_KEY
    main_model: claude-sonnet-4-5-20250929
  - name: openai-official
    base_url: https://api.openai.com/v1
    auth_field: Authorization
    auth_secret_ref: OPENAI_API_KEY
    main_model: gpt-5.1
    auxiliary_model: gpt-5-nano
"""

BOTH_KEYS = {"ANTHROPIC_API_KEY": "sk-ant", "OPENAI_API_KEY": "sk-oai"}


def _load(tmp_path: Path) -> ServerEndpointsConfig:
    path = tmp_path / "endpoints.yaml"
    path.write_text(YAML, encoding="utf-8")
    return load_server_endpoints(path)


def test_zero_config_returns_one_profile_and_two_model_ids(tmp_path: Path) -> None:
    config = _load(tmp_path)

    resolved = resolve_profiles(config, env={"ANTHROPIC_API_KEY": "sk-ant"})

    assert isinstance(resolved.profile, EndpointProfile)
    assert resolved.profile.name == "anthropic-official"
    assert resolved.main_model == "claude-sonnet-4-5-20250929"
    assert resolved.auxiliary_model  # 非空
    assert resolved.auxiliary_model == resolved.main_model
    assert resolved.auxiliary_model_source == "fallback_to_main"
    assert resolved.key_source == "server_default"


def test_model_only_override_keeps_the_preset_profile_and_key(tmp_path: Path) -> None:
    """issue #82 的主场景：不填任何密钥，只换模型标识。"""

    config = _load(tmp_path)

    resolved = resolve_profiles(
        config, ModelOverride(main_model="claude-opus-5"), env={"ANTHROPIC_API_KEY": "sk-ant"}
    )

    assert resolved.main_model == "claude-opus-5"
    assert resolved.profile.base_url == "https://api.anthropic.com"
    assert resolved.profile.api_key.get_secret_value() == "sk-ant"
    assert resolved.key_source == "server_default"
    # auxiliary 未指定——跟随的是覆盖后的 main，不是档案里那个。
    assert resolved.auxiliary_model == "claude-opus-5"
    assert resolved.auxiliary_model_source == "fallback_to_main"


def test_profile_name_override_switches_preset_profile(tmp_path: Path) -> None:
    config = _load(tmp_path)

    resolved = resolve_profiles(
        config, ModelOverride(endpoint_profile="openai-official"), env=BOTH_KEYS
    )

    assert resolved.profile.name == "openai-official"
    assert resolved.profile.protocol == "openai_responses"
    assert resolved.profile.api_key.get_secret_value() == "sk-oai"
    assert resolved.main_model == "gpt-5.1"
    assert resolved.auxiliary_model == "gpt-5-nano"
    assert resolved.auxiliary_model_source == "specified"
    assert resolved.key_source == "server_default"


def test_profile_and_model_override_combine(tmp_path: Path) -> None:
    config = _load(tmp_path)

    resolved = resolve_profiles(
        config,
        ModelOverride(endpoint_profile="openai-official", main_model="gpt-5.4"),
        env=BOTH_KEYS,
    )

    assert resolved.profile.name == "openai-official"
    assert resolved.main_model == "gpt-5.4"
    # 模型覆盖不冲掉档案自己的 auxiliary——只有用户显式填了才换。
    assert resolved.auxiliary_model == "gpt-5-nano"
    assert resolved.auxiliary_model_source == "specified"


def test_auxiliary_override_alone_leaves_main_on_the_preset(tmp_path: Path) -> None:
    config = _load(tmp_path)

    resolved = resolve_profiles(
        config, ModelOverride(auxiliary_model="claude-haiku-4-5"), env={"ANTHROPIC_API_KEY": "sk"}
    )

    assert resolved.main_model == "claude-sonnet-4-5-20250929"
    assert resolved.auxiliary_model == "claude-haiku-4-5"
    assert resolved.auxiliary_model_source == "specified"


def test_custom_endpoint_brings_its_own_url_key_and_model(tmp_path: Path) -> None:
    config = _load(tmp_path)

    resolved = resolve_profiles(
        config,
        ModelOverride(
            protocol="openai_chat_completions",
            base_url="https://relay.example.com/v1",
            auth_field="Authorization",
            api_key=SecretStr("sk-user"),
            main_model="custom-model",
            auxiliary_model="custom-aux-model",
        ),
        env=BOTH_KEYS,
    )

    assert resolved.profile.base_url == "https://relay.example.com/v1"
    assert resolved.profile.protocol == "openai_chat_completions"
    assert resolved.profile.api_key.get_secret_value() == "sk-user"
    assert resolved.main_model == "custom-model"
    assert resolved.auxiliary_model == "custom-aux-model"
    assert resolved.auxiliary_model_source == "specified"
    assert resolved.key_source == "user_provided"


def test_custom_endpoint_never_falls_back_to_the_server_key(tmp_path: Path) -> None:
    """用户自带中转站时服务端密钥一个字段都不参与——静默兜底会让他以为配置是对的。"""

    config = _load(tmp_path)

    resolved = resolve_profiles(
        config,
        ModelOverride(
            base_url="https://relay.example.com/v1",
            api_key=SecretStr("sk-user"),
            main_model="custom-model",
        ),
        env=BOTH_KEYS,
    )

    assert resolved.profile.api_key.get_secret_value() == "sk-user"
    assert resolved.key_source == "user_provided"
    # 预设档案的模型标识也不渗进来：auxiliary 回落到用户的 main，不是 claude-sonnet。
    assert resolved.auxiliary_model == "custom-model"


def test_both_construction_paths_produce_the_same_dataclass_type(tmp_path: Path) -> None:
    config = _load(tmp_path)

    server_resolved = resolve_profiles(config, env={"ANTHROPIC_API_KEY": "sk-ant"})
    user_resolved = resolve_profiles(
        config,
        ModelOverride(
            protocol="anthropic_messages",
            base_url="https://api.anthropic.com",
            auth_field="x-api-key",
            api_key=SecretStr("sk-user"),
            main_model="claude-sonnet-4-5-20250929",
        ),
    )

    assert type(server_resolved.profile) is type(user_resolved.profile) is EndpointProfile


def test_unavailable_default_profile_raises_profile_unavailable_error(tmp_path: Path) -> None:
    config = _load(tmp_path)

    with pytest.raises(ProfileUnavailableError):
        resolve_profiles(config, env={})


def test_unavailable_overridden_profile_raises_instead_of_falling_back(tmp_path: Path) -> None:
    """选中的档案没配密钥时如实报错——回落到默认档案就是系统代选（ADR-0014）。"""

    config = _load(tmp_path)

    with pytest.raises(ProfileUnavailableError):
        resolve_profiles(
            config,
            ModelOverride(endpoint_profile="openai-official"),
            env={"ANTHROPIC_API_KEY": "sk-ant"},
        )


def test_unknown_profile_name_raises(tmp_path: Path) -> None:
    config = _load(tmp_path)

    with pytest.raises(ProfileUnavailableError):
        resolve_profiles(config, ModelOverride(endpoint_profile="nope"), env=BOTH_KEYS)
