"""Issue #63 的容器与 Compose 静态契约。"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


class _ComposeLoader(yaml.SafeLoader):
    pass


_ComposeLoader.add_constructor("!reset", lambda _loader, _node: None)


def _compose(path: str) -> dict:
    return yaml.load((REPO_ROOT / path).read_text(encoding="utf-8"), Loader=_ComposeLoader)


def test_base_compose_has_only_backend_postgres_and_migrate() -> None:
    compose = _compose("compose.yaml")

    assert set(compose["services"]) == {"backend", "postgres", "migrate"}


def test_postgres_is_private_pinned_and_persisted() -> None:
    postgres = _compose("compose.yaml")["services"]["postgres"]

    assert postgres["image"] == "postgres:18.4"
    assert "ports" not in postgres
    assert "/var/lib/postgresql" in postgres["volumes"][0]


def test_backend_waits_for_migration_and_binds_loopback_only() -> None:
    backend = _compose("compose.yaml")["services"]["backend"]
    migrate = _compose("compose.yaml")["services"]["migrate"]

    assert backend["ports"] == ["127.0.0.1:19180:8080"]
    assert backend["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}
    assert migrate["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert migrate["command"] == ["python", "-m", "alembic", "upgrade", "head"]


def test_healthcheck_uses_python_and_logs_are_bounded() -> None:
    compose = _compose("compose.yaml")
    healthcheck = compose["services"]["backend"]["healthcheck"]["test"]

    assert healthcheck[0] == "CMD"
    assert "urllib.request" in " ".join(healthcheck)
    assert "curl" not in " ".join(healthcheck).lower()

    for service in compose["services"].values():
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }


def test_endpoint_config_is_baked_into_the_image() -> None:
    compose = _compose("compose.yaml")
    dockerfile = (REPO_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")

    assert (
        compose["services"]["backend"]["environment"]["CHATAGENTS_ENDPOINTS_CONFIG_PATH"]
        == "${CHATAGENTS_ENDPOINTS_CONFIG_PATH:-/app/config/endpoints.yaml}"
    )
    assert "COPY --from=build /app/backend/config /app/config" in dockerfile
    assert "config/endpoints.yaml" not in str(compose["services"]["backend"].get("volumes", []))


def test_backend_image_is_uv_multistage_without_source_tree() -> None:
    dockerfile = (REPO_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")

    assert "FROM ghcr.io/astral-sh/uv:" in dockerfile
    assert "FROM python:3.11-slim AS build" in dockerfile
    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "--no-install-project --no-editable --no-dev" in dockerfile
    assert dockerfile.count("--no-editable --no-dev") == 2
    assert "COPY . ." not in dockerfile
    assert "COPY --from=build /app/backend/.venv /app/.venv" in dockerfile
    assert "ARG APP_VERSION" in dockerfile
    assert 'ENV PATH="/app/.venv/bin:$PATH"' in dockerfile


def test_production_compose_uses_published_backend_image() -> None:
    compose = _compose("compose.prod.yaml")

    expected = "ghcr.io/ellisyuan/chatagents-backend:${APP_VERSION:?APP_VERSION must be set}"
    assert compose["services"]["backend"] == {"image": expected, "build": None}
    assert compose["services"]["migrate"] == {"image": expected, "build": None}
