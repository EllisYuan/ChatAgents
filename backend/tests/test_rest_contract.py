"""#59 的 REST 契约 seam 测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from chat_agents import main as main_module
from chat_agents.model_catalog import ModelItem


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
    assert "/api/models/refresh" in paths
    assert "/health" in paths
    assert "/" not in paths
    schemas = schema["components"]["schemas"]
    assert {
        "ChatAgentsUsagePayload",
        "ChatAgentsSpanPayload",
        "ChatAgentsToolResultPayload",
        "ProblemDetails",
    } <= schemas.keys()
