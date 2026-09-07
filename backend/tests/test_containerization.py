"""Issue #63 的容器与 Compose 静态契约。"""

import re
from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PORT = "8000"


class _ComposeLoader(yaml.SafeLoader):
    pass


_ComposeLoader.add_constructor("!reset", lambda _loader, _node: None)


def _compose(path: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.load((REPO_ROOT / path).read_text(encoding="utf-8"), Loader=_ComposeLoader),
    )


def test_base_compose_has_only_backend_postgresql_and_migrate() -> None:
    compose = _compose("compose.yaml")

    assert set(compose["services"]) == {"backend", "postgresql", "migrate"}


def test_postgresql_is_loopback_pinned_and_persisted() -> None:
    postgresql = _compose("compose.yaml")["services"]["postgresql"]

    assert postgresql["container_name"] == "chatagent-postgresql"
    assert postgresql["image"] == "postgres:18.4"
    assert postgresql["ports"] == ["127.0.0.1:5432:5432"]
    assert postgresql["volumes"] == ["postgres-data:/var/lib/postgresql"]
    assert postgresql["environment"] == {
        "POSTGRES_DB": "${POSTGRES_DB:-chat_agents}",
        "POSTGRES_USER": "${POSTGRES_USER:-root}",
        "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:-Agent@Dev_1}",
    }


def test_backend_waits_for_migration_and_binds_loopback_only() -> None:
    backend = _compose("compose.yaml")["services"]["backend"]
    migrate = _compose("compose.yaml")["services"]["migrate"]
    expected_database_url = (
        "postgresql+psycopg://${POSTGRES_USER:-root}:"
        "${POSTGRES_PASSWORD_URLENCODED:-Agent%40Dev_1}"
        "@postgresql:5432/${POSTGRES_DB:-chat_agents}"
    )

    assert backend["ports"] == ["127.0.0.1:19180:8000"]
    assert backend["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}
    assert backend["environment"]["DATABASE_URL"] == expected_database_url
    assert migrate["depends_on"] == {"postgresql": {"condition": "service_healthy"}}
    assert migrate["environment"]["DATABASE_URL"] == expected_database_url
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


def test_backend_port_is_the_same_everywhere() -> None:
    """8000 有四处定义，漂一处就断一条链路（ADR-0034：能机械验证的就别只写进文档）。

    历史故障（彼时固定端口为 8080）：README 的本地直起命令漏了 ``--port``，
    uvicorn 退回默认 8000，而 vite 代理仍打 8080，前端每个 ``/api`` 请求
    收到代理自造的 500 空响应。
    """

    dockerfile = (REPO_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    vite_config = (REPO_ROOT / "frontend/vite.config.ts").read_text(encoding="utf-8")
    dev_script = (REPO_ROOT / "scripts/dev.py").read_text(encoding="utf-8")
    backend = _compose("compose.yaml")["services"]["backend"]

    # 容器内监听端口，与 EXPOSE 一致
    assert f"EXPOSE {BACKEND_PORT}" in dockerfile
    assert f'"--port", "{BACKEND_PORT}"' in dockerfile

    # compose 宿主映射的容器侧（宿主侧 19180 是机器属性，不在本断言范围内）
    assert backend["ports"] == [f"127.0.0.1:19180:{BACKEND_PORT}"]
    assert f"127.0.0.1:{BACKEND_PORT}/health" in " ".join(backend["healthcheck"]["test"])

    # 本地直起：dev.py 是执行真源，vite 代理默认值必须指向同一个端口
    assert f'BACKEND_PORT = "{BACKEND_PORT}"' in dev_script
    assert "BACKEND_PORT," in dev_script
    assert f'"http://127.0.0.1:{BACKEND_PORT}"' in vite_config


def test_readme_backend_command_pins_the_port() -> None:
    """README 的启动命令必须显式 ``--port``——写明是防止端口再次漂移的最低成本。"""

    for name in ("README.md", "README_EN.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for command in re.findall(r"^.*-m uvicorn chat_agents\.main:app.*$", text, re.MULTILINE):
            assert f"--port {BACKEND_PORT}" in command, f"{name} 的启动命令缺少端口: {command}"


def test_production_compose_uses_published_backend_image() -> None:
    compose = _compose("compose.prod.yaml")

    expected = "ghcr.io/ellisyuan/chatagents-backend:${APP_VERSION:?APP_VERSION must be set}"
    assert compose["services"]["backend"] == {"image": expected, "build": None}
    assert compose["services"]["migrate"] == {"image": expected, "build": None}
