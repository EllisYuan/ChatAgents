"""resolve_profiles：两条构造路径交汇于同一个 EndpointProfile 类型。"""

from pathlib import Path

import pytest
from chat_agents.llm.errors import ProfileUnavailableError
from chat_agents.llm.profile import EndpointProfile
from chat_agents.llm.resolve import resolve_profiles
from chat_agents.llm.server_config import ServerEndpointsConfig, load_server_endpoints
from chat_agents.llm.user_config import UserEndpointConfig
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


def test_user_config_without_auxiliary_falls_back_to_main(tmp_path: Path) -> None:
    config = _load(tmp_path)

    resolved = resolve_profiles(
        config,
        user_config=UserEndpointConfig(
            protocol="openai_responses",
            base_url="https://api.openai.com/v1",
            auth_field="Authorization",
            api_key=SecretStr("sk-user"),
            main_model="gpt-5.1",
        ),
    )
    assert resolved.auxiliary_model == "gpt-5.1"
    assert resolved.auxiliary_model_source == "fallback_to_main"


def test_user_config_takes_priority_over_server_preset(tmp_path: Path) -> None:
    config = _load(tmp_path)

    user_config = UserEndpointConfig(
        protocol="openai_chat_completions",
        base_url="https://relay.example.com/v1",
        auth_field="Authorization",
        api_key=SecretStr("sk-user"),
        main_model="custom-model",
        auxiliary_model="custom-aux-model",
    )

    resolved = resolve_profiles(config, user_config=user_config, env={})

    assert resolved.profile.base_url == "https://relay.example.com/v1"
    assert resolved.profile.protocol == "openai_chat_completions"
    assert resolved.main_model == "custom-model"
    assert resolved.auxiliary_model == "custom-aux-model"
    assert resolved.auxiliary_model_source == "specified"


def test_both_construction_paths_produce_the_same_dataclass_type(tmp_path: Path) -> None:
    config = _load(tmp_path)

    server_resolved = resolve_profiles(config, env={"ANTHROPIC_API_KEY": "sk-ant"})
    user_resolved = resolve_profiles(
        config,
        user_config=UserEndpointConfig(
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
