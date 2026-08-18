from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from chat_agents.llm.model_discovery import (
    MODEL_DISCOVERY_INTERVAL_SECONDS,
    MODEL_DISCOVERY_TIMEOUT_SECONDS,
    InMemoryModelCatalogStore,
    ModelDiscoveryError,
    ModelDiscoveryService,
    ModelItem,
    discover_openai_models,
    is_model_discovery_enabled,
    model_discovery_lifespan,
    models_url,
    periodic_model_refresh,
)
from chat_agents.llm.profile import EndpointProfile
from pydantic import SecretStr


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,  # noqa: ASYNC109
    ) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FailingStore(InMemoryModelCatalogStore):
    async def replace(
        self,
        endpoint_profile: str,
        models: tuple[ModelItem, ...],
        discovered_at: datetime,
    ) -> None:
        raise AssertionError("custom discovery must not write to the store")


def profile(name: str = "preset") -> EndpointProfile:
    return EndpointProfile(
        name=name,
        protocol="openai_responses",
        base_url="https://relay.example.com/v1",
        auth_field="Authorization",
        api_key=SecretStr("Bearer test-key"),
    )


def test_models_url_supports_bases_with_or_without_v1_suffix() -> None:
    assert models_url("https://relay.example.com") == "https://relay.example.com/v1/models"
    assert models_url("https://relay.example.com/v1/") == "https://relay.example.com/v1/models"


def test_discovery_reads_only_openai_id_and_owned_by() -> None:
    async def scenario() -> None:
        client = FakeHttpClient(
            FakeResponse(
                {
                    "data": [
                        {"id": "gpt-one", "owned_by": "alpha", "created": 123},
                        {"id": "gpt-two", "owned_by": "beta", "capabilities": {"thinking": {}}},
                    ],
                    "object": "list",
                }
            )
        )

        result = await discover_openai_models(profile(), http_client=client)

        assert result == (
            ModelItem(model_id="gpt-one", owned_by="alpha"),
            ModelItem(model_id="gpt-two", owned_by="beta"),
        )
        assert client.calls == [
            {
                "url": "https://relay.example.com/v1/models",
                "headers": {"Authorization": "Bearer test-key"},
                "timeout": MODEL_DISCOVERY_TIMEOUT_SECONDS,
            }
        ]

    asyncio.run(scenario())


def test_discovery_rejects_malformed_model_entries() -> None:
    async def scenario() -> None:
        client = FakeHttpClient(FakeResponse({"data": [{"id": "missing-owner"}]}))

        with pytest.raises(ModelDiscoveryError, match="owned_by"):
            await discover_openai_models(profile(), http_client=client)

    asyncio.run(scenario())


def test_empty_discovery_is_fallback_and_does_not_replace_old_catalog() -> None:
    async def scenario() -> None:
        old_time = datetime(2026, 8, 17, 12, tzinfo=UTC)
        store = InMemoryModelCatalogStore()
        old_models = (ModelItem(model_id="old-model", owned_by="old-owner"),)
        await store.replace("preset", old_models, old_time)
        service = ModelDiscoveryService(
            store,
            http_client=FakeHttpClient(FakeResponse({"data": []})),
        )

        catalog = await service.refresh_preset(profile())

        assert catalog.models == old_models
        assert catalog.source == "fallback"
        assert catalog.last_success_at == old_time
        assert catalog.error == "模型清单为空"
        assert await store.load("preset") == (old_models, old_time)

    asyncio.run(scenario())


def test_preset_refresh_failure_keeps_old_catalog_and_marks_fallback() -> None:
    async def scenario() -> None:
        old_time = datetime(2026, 8, 17, 12, tzinfo=UTC)
        store = InMemoryModelCatalogStore()
        await store.replace(
            "preset",
            (ModelItem(model_id="old-model", owned_by="old-owner"),),
            old_time,
        )
        client = FakeHttpClient(TimeoutError("upstream timed out"))
        service = ModelDiscoveryService(store, http_client=client)

        catalog = await service.refresh_preset(profile())

        assert catalog.models == (ModelItem(model_id="old-model", owned_by="old-owner"),)
        assert catalog.source == "fallback"
        assert catalog.last_success_at == old_time
        assert catalog.error == "模型清单上游不可达"
        assert await store.load("preset") == (
            (ModelItem(model_id="old-model", owned_by="old-owner"),),
            old_time,
        )

    asyncio.run(scenario())


def test_custom_refresh_returns_models_without_persisting() -> None:
    async def scenario() -> None:
        client = FakeHttpClient(FakeResponse({"data": [{"id": "custom", "owned_by": "guest"}]}))
        service = ModelDiscoveryService(FailingStore(), http_client=client)

        catalog = await service.refresh_custom(profile("user"))

        assert catalog.models == (ModelItem(model_id="custom", owned_by="guest"),)
        assert catalog.source == "discovered"
        assert catalog.last_success_at is not None

    asyncio.run(scenario())


def test_periodic_refresh_runs_immediately_then_every_24_hours() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        sleeps: list[float] = []

        class Service:
            async def refresh_configured_presets(self) -> None:
                calls.append("refresh")
                if len(calls) == 2:
                    raise asyncio.CancelledError

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)

        with pytest.raises(asyncio.CancelledError):
            await periodic_model_refresh(Service(), sleep=sleep)

        assert calls == ["refresh", "refresh"]
        assert sleeps == [MODEL_DISCOVERY_INTERVAL_SECONDS]

    asyncio.run(scenario())


def test_disabled_lifespan_does_not_start_background_refresh() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        class Service:
            async def refresh_configured_presets(self) -> None:
                calls.append("refresh")

        async with model_discovery_lifespan(
            Service(), env={"CHATAGENTS_MODEL_DISCOVERY_ENABLED": "false"}
        ):
            await asyncio.sleep(0)

        assert calls == []

    asyncio.run(scenario())


def test_model_discovery_can_be_disabled_by_environment() -> None:
    assert is_model_discovery_enabled({}) is True
    assert is_model_discovery_enabled({"CHATAGENTS_MODEL_DISCOVERY_ENABLED": "false"}) is False
    assert is_model_discovery_enabled({"CHATAGENTS_MODEL_DISCOVERY_ENABLED": "0"}) is False
    assert is_model_discovery_enabled({"CHATAGENTS_MODEL_DISCOVERY_ENABLED": "yes"}) is True
