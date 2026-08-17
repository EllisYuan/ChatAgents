"""env 缺失只让该档案不进选单，不中断启动。"""

from pathlib import Path

from chat_agents.llm.profile import EndpointProfile
from chat_agents.llm.server_config import (
    ServerEndpointsConfig,
    build_available_profiles,
    load_server_endpoints,
)

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
"""


def _load(tmp_path: Path) -> ServerEndpointsConfig:
    path = tmp_path / "endpoints.yaml"
    path.write_text(YAML, encoding="utf-8")
    return load_server_endpoints(path)


def test_profile_with_env_present_is_available(tmp_path: Path) -> None:
    config = _load(tmp_path)

    available, unavailable = build_available_profiles(
        config, env={"ANTHROPIC_API_KEY": "sk-ant", "OPENAI_API_KEY": "sk-oai"}
    )

    assert set(available) == {"anthropic-official", "openai-official"}
    assert unavailable == {}
    assert isinstance(available["anthropic-official"], EndpointProfile)
    assert available["anthropic-official"].api_key.get_secret_value() == "sk-ant"


def test_missing_env_marks_only_that_profile_unavailable(tmp_path: Path) -> None:
    config = _load(tmp_path)

    available, unavailable = build_available_profiles(config, env={"ANTHROPIC_API_KEY": "sk-ant"})

    assert set(available) == {"anthropic-official"}
    assert set(unavailable) == {"openai-official"}
    assert "OPENAI_API_KEY" in unavailable["openai-official"].reason


def test_empty_env_value_also_counts_as_missing(tmp_path: Path) -> None:
    config = _load(tmp_path)

    available, unavailable = build_available_profiles(
        config, env={"ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "sk-oai"}
    )

    assert "anthropic-official" not in available
    assert "anthropic-official" in unavailable
