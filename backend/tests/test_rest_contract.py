"""#59 的 REST 契约 seam 测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from chat_agents import main as main_module
from chat_agents.model_catalog import ModelItem
from chat_agents.validation import MAX_MESSAGE_LENGTH, MAX_TITLE_LENGTH


class _Store:
    def __init__(self, models: tuple[ModelItem, ...], timestamp: datetime | None) -> None:
        self.models = models
        self.timestamp = timestamp

    async def load(self, endpoint_profile: str) -> tuple[tuple[ModelItem, ...], datetime | None]:
        assert endpoint_profile == "anthropic-official"
        return self.models, self.timestamp

    async def replace(
        self, endpoint_profile: str, models: tuple[ModelItem, ...], discovered_at: datetime
    ) -> None:
        self.models = models
        self.timestamp = discovered_at


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    )


def test_health_exposes_app_version_and_collection_post_is_absent(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("APP_VERSION", "v1.2.3")

    async def scenario() -> None:
        async with _client() as client:
            health = await client.get("/health")
            root = await client.get("/")
            collection_post = await client.post("/api/sessions", json={})

        assert health.status_code == 200
        assert health.json() == {"status": "ok", "version": "v1.2.3"}
        assert root.status_code == 404
        assert collection_post.status_code == 405

    asyncio.run(scenario())


def test_models_contract_keeps_discovered_catalog_flat(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    timestamp = datetime(2026, 8, 18, 12, tzinfo=UTC)
    store = _Store((ModelItem(model_id="gpt-test", owned_by="openai"),), timestamp)
    main_module.app.dependency_overrides[main_module.get_model_catalog_store] = lambda: store

    async def scenario() -> None:
        async with _client() as client:
            response = await client.get("/api/models")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "discovered"
        assert datetime.fromisoformat(body["last_success_at"]) == timestamp
        assert body["models"] == [
            {
                "id": "gpt-test",
                "owned_by": "openai",
                "endpoint_profile": "anthropic-official",
            }
        ]

    try:
        asyncio.run(scenario())
    finally:
        main_module.app.dependency_overrides.pop(main_module.get_model_catalog_store, None)


def test_models_contract_distinguishes_unavailable_profile_from_empty_catalog(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store = _Store((), None)
    main_module.app.dependency_overrides[main_module.get_model_catalog_store] = lambda: store

    async def scenario() -> None:
        async with _client() as client:
            response = await client.get("/api/models")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "fallback"
        assert body["profile"] == {
            "name": "anthropic-official",
            "status": "unavailable",
            "reason": "环境变量 ANTHROPIC_API_KEY 未设置",
        }
        assert body["error"] is None

    try:
        asyncio.run(scenario())
    finally:
        main_module.app.dependency_overrides.pop(main_module.get_model_catalog_store, None)


def test_model_profiles_lists_available_and_unavailable(monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def scenario() -> None:
        async with _client() as client:
            response = await client.get("/api/models/profiles")
        assert response.status_code == 200
        assert response.json() == {
            "profiles": [
                {"name": "anthropic-official", "status": "available", "reason": None},
                {
                    "name": "openai-official",
                    "status": "unavailable",
                    "reason": "环境变量 OPENAI_API_KEY 未设置",
                },
            ]
        }

    asyncio.run(scenario())


class _MultiProfileStore:
    """接受任意档案名的假 store，供档案切换测试使用。"""

    def __init__(self, catalogs: dict[str, tuple[tuple[ModelItem, ...], datetime | None]]) -> None:
        self._catalogs = catalogs

    async def load(self, endpoint_profile: str) -> tuple[tuple[ModelItem, ...], datetime | None]:
        return self._catalogs.get(endpoint_profile, ((), None))

    async def replace(
        self, endpoint_profile: str, models: tuple[ModelItem, ...], discovered_at: datetime
    ) -> None:
        self._catalogs[endpoint_profile] = (models, discovered_at)


def test_models_contract_switches_profile_via_query_param(monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    store = _MultiProfileStore(
        {"openai-official": ((ModelItem(model_id="gpt-5.1", owned_by="openai"),), None)}
    )
    main_module.app.dependency_overrides[main_module.get_model_catalog_store] = lambda: store

    async def scenario() -> None:
        async with _client() as client:
            response = await client.get(
                "/api/models", params={"endpoint_profile": "openai-official"}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["endpoint_profile"] == "openai-official"
        assert body["models"] == [
            {"id": "gpt-5.1", "owned_by": "openai", "endpoint_profile": "openai-official"}
        ]

    try:
        asyncio.run(scenario())
    finally:
        main_module.app.dependency_overrides.pop(main_module.get_model_catalog_store, None)


def test_models_contract_rejects_unknown_endpoint_profile(monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    store = _MultiProfileStore({})
    main_module.app.dependency_overrides[main_module.get_model_catalog_store] = lambda: store

    async def scenario() -> None:
        async with _client() as client:
            response = await client.get(
                "/api/models", params={"endpoint_profile": "does-not-exist"}
            )
        assert response.status_code == 400
        assert response.json()["type"] == "protocol_error"

    try:
        asyncio.run(scenario())
    finally:
        main_module.app.dependency_overrides.pop(main_module.get_model_catalog_store, None)


def test_problem_details_contains_rfc9457_extensions() -> None:
    async def scenario() -> None:
        async with _client() as client:
            response = await client.post(
                "/api/runs", json={"session_id": str(uuid4()), "message": "   "}
            )
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["type"] == "protocol_error"
        assert {"upstream_error", "run_id", "key_source"} <= body.keys()

    asyncio.run(scenario())


def test_openapi_contains_rest_and_custom_payload_schemas() -> None:
    schema = main_module.app.openapi()
    paths = schema["paths"]
    assert "/api/models" in paths
    assert "400" in paths["/api/runs"]["post"]["responses"]
    assert "/api/models/refresh" in paths
    assert "/health" in paths
    assert "/" not in paths
    schemas = schema["components"]["schemas"]
    assert {
        "ChatAgentsUsagePayload",
        "ChatAgentsSpanPayload",
        "ChatAgentsToolResultPayload",
        "ChatAgentsTitlePayload",
        "ProblemDetails",
    } <= schemas.keys()


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "not-a-uuid", "message": "hello"},
        {"session_id": str(uuid4()), "message": "   "},
        {"session_id": str(uuid4()), "message": "hello", "unexpected": True},
        {"session_id": str(uuid4()), "message": "x" * (MAX_MESSAGE_LENGTH + 1)},
    ],
)
def test_run_input_validation_returns_problem_details_before_stream(
    payload: dict[str, object],
) -> None:
    async def scenario() -> None:
        async with _client() as client:
            response = await client.post("/api/runs", json=payload)
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["type"] == "protocol_error"
        assert body["status"] == 400
        assert "请求参数校验失败" in body["detail"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   "},
        {"title": "x" * (MAX_TITLE_LENGTH + 1)},
        {"title": "有效", "unexpected": True},
    ],
)
def test_rename_input_validation_returns_problem_details(payload: dict[str, object]) -> None:
    async def scenario() -> None:
        async with _client() as client:
            response = await client.patch(f"/api/sessions/{uuid4()}", json=payload)
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["type"] == "protocol_error"

    asyncio.run(scenario())


def test_model_refresh_rejects_malformed_custom_endpoint() -> None:
    async def scenario() -> None:
        async with _client() as client:
            response = await client.post(
                "/api/models/refresh",
                json={"base_url": "not-a-url", "api_key": "key"},
            )
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["type"] == "protocol_error"

    asyncio.run(scenario())
