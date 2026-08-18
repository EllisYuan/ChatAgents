"""Settings 读环境变量，决定 YAML 端点文件的位置。"""

from pathlib import Path

import pytest
from chat_agents.llm.settings import Settings


def test_default_endpoints_config_path_points_at_backend_config() -> None:
    settings = Settings()

    assert settings.endpoints_config_path.name == "endpoints.yaml"
    assert settings.endpoints_config_path.parent.name == "config"


def test_model_discovery_can_be_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATAGENTS_MODEL_DISCOVERY_ENABLED", "false")

    assert Settings().model_discovery_enabled is False


def test_endpoints_config_path_overridable_via_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom = tmp_path / "custom-endpoints.yaml"
    monkeypatch.setenv("CHATAGENTS_ENDPOINTS_CONFIG_PATH", str(custom))

    settings = Settings()

    assert settings.endpoints_config_path == custom
