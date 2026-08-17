"""YAML 端点配置文件的结构校验：结构错误必须 ConfigError，供启动流程转为启动失败。"""

from pathlib import Path

import pytest
from chat_agents.llm.errors import ConfigError
from chat_agents.llm.server_config import load_server_endpoints

VALID_YAML = """
default_profile: anthropic-official
endpoints:
  - name: anthropic-official
    protocol: anthropic_messages
    base_url: https://api.anthropic.com
    auth_field: x-api-key
    auth_secret_ref: ANTHROPIC_API_KEY
    main_model: claude-sonnet-4-5-20250929
  - name: relay-openai-format
    base_url: https://relay.example.com
    auth_field: Authorization
    auth_secret_ref: RELAY_API_KEY
    main_model: gpt-5.1
  - name: relay-anthropic-format
    protocol: anthropic_messages
    base_url: https://relay.example.com
    auth_field: x-api-key
    auth_secret_ref: RELAY_API_KEY
    main_model: claude-sonnet-4-5-20250929
    auxiliary_model: claude-haiku-4-5-20251001
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "endpoints.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_multiple_profiles(tmp_path: Path) -> None:
    config = load_server_endpoints(_write(tmp_path, VALID_YAML))

    assert config.default_profile == "anthropic-official"
    assert set(config.profiles) == {
        "anthropic-official",
        "relay-openai-format",
        "relay-anthropic-format",
    }


def test_same_base_url_multiple_protocols(tmp_path: Path) -> None:
    config = load_server_endpoints(_write(tmp_path, VALID_YAML))

    openai_profile = config.profiles["relay-openai-format"]
    anthropic_profile = config.profiles["relay-anthropic-format"]
    assert openai_profile.base_url == anthropic_profile.base_url
    assert openai_profile.protocol != anthropic_profile.protocol


def test_protocol_defaults_to_openai_responses(tmp_path: Path) -> None:
    config = load_server_endpoints(_write(tmp_path, VALID_YAML))

    assert config.profiles["relay-openai-format"].protocol == "openai_responses"


def test_auxiliary_model_defaults_to_none_when_omitted(tmp_path: Path) -> None:
    config = load_server_endpoints(_write(tmp_path, VALID_YAML))

    assert config.profiles["anthropic-official"].auxiliary_model is None
    assert config.profiles["relay-anthropic-format"].auxiliary_model == (
        "claude-haiku-4-5-20251001"
    )


def test_auth_field_is_per_profile_not_hardcoded(tmp_path: Path) -> None:
    config = load_server_endpoints(_write(tmp_path, VALID_YAML))

    assert config.profiles["anthropic-official"].auth_field == "x-api-key"
    assert config.profiles["relay-openai-format"].auth_field == "Authorization"


@pytest.mark.parametrize(
    "broken_yaml",
    [
        "not: [a, mapping, at, top, level]\n- oops",
        "default_profile: 123\nendpoints: []",
        "endpoints: []",
        "default_profile: x\nendpoints:\n  - base_url: https://x\n"
        "    auth_field: a\n    auth_secret_ref: X\n    main_model: m",
        "default_profile: x\nendpoints:\n  - name: x\n    protocol: bogus_protocol\n"
        "    base_url: https://x\n    auth_field: a\n    auth_secret_ref: X\n    main_model: m",
        "default_profile: x\nendpoints:\n  - name: x\n    auth_field: a\n"
        "    auth_secret_ref: X\n    main_model: m",
        "default_profile: x\nendpoints:\n  - name: x\n    base_url: https://x\n"
        "    auth_secret_ref: X\n    main_model: m",
        "default_profile: x\nendpoints:\n  - name: x\n    base_url: https://x\n"
        "    auth_field: a\n    main_model: m",
        "default_profile: x\nendpoints:\n  - name: x\n    base_url: https://x\n"
        "    auth_field: a\n    auth_secret_ref: X",
        "default_profile: dup\nendpoints:\n"
        "  - name: dup\n    base_url: https://a\n    auth_field: a\n"
        "    auth_secret_ref: A\n    main_model: m\n"
        "  - name: dup\n    base_url: https://b\n    auth_field: b\n"
        "    auth_secret_ref: B\n    main_model: m",
        "default_profile: missing\nendpoints:\n"
        "  - name: present\n    base_url: https://a\n    auth_field: a\n"
        "    auth_secret_ref: A\n    main_model: m",
        "not valid yaml: [\n",
    ],
)
def test_structural_errors_raise_config_error(tmp_path: Path, broken_yaml: str) -> None:
    with pytest.raises(ConfigError):
        load_server_endpoints(_write(tmp_path, broken_yaml))


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_server_endpoints(tmp_path / "does-not-exist.yaml")
