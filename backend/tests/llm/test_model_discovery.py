from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from chat_agents.llm.model_discovery import (
    ANTHROPIC_VERSION,
    MODEL_DISCOVERY_INTERVAL_SECONDS,
    MODEL_DISCOVERY_TIMEOUT_SECONDS,
    UNKNOWN_OWNER,
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
from chat_agents.llm.protocol import Protocol
from pydantic import SecretStr


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

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


def test_bearer_prefix_is_added_when_the_key_lacks_it() -> None:
    """裸密钥要补 ``Bearer `` ——官方 OpenAI 端点缺前缀直接 401（2026-09-01 实测）。

    生成路径由官方 SDK 构造请求、SDK 自己补前缀；清单请求是自己发的 HTTP，
    这一步没人替我们做。
    """

    async def scenario() -> None:
        bare = EndpointProfile(
            name="preset",
            protocol="openai_responses",
            base_url="https://api.openai.com/v1",
            auth_field="Authorization",
            api_key=SecretStr("sk-no-prefix"),
        )
        client = FakeHttpClient(FakeResponse({"data": []}))

        await discover_openai_models(bare, http_client=client)

        assert client.calls[0]["headers"] == {"Authorization": "Bearer sk-no-prefix"}

    asyncio.run(scenario())


def test_bearer_prefix_is_not_doubled() -> None:
    async def scenario() -> None:
        client = FakeHttpClient(FakeResponse({"data": []}))

        await discover_openai_models(profile(), http_client=client)

        assert client.calls[0]["headers"] == {"Authorization": "Bearer test-key"}

    asyncio.run(scenario())


def test_anthropic_profile_carries_the_required_version_header() -> None:
    """Anthropic 缺 ``anthropic-version`` 直接 400（2026-09-01 实测官方端点）。"""

    async def scenario() -> None:
        anthropic = EndpointProfile(
            name="anthropic-official",
            protocol="anthropic_messages",
            base_url="https://api.anthropic.com",
            auth_field="x-api-key",
            api_key=SecretStr("sk-ant-key"),
        )
        client = FakeHttpClient(FakeResponse({"data": []}))

        await discover_openai_models(anthropic, http_client=client)

        assert client.calls[0]["headers"] == {
            "x-api-key": "sk-ant-key",
            "anthropic-version": ANTHROPIC_VERSION,
        }

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("protocol", "suffix"),
    [
        ("openai_chat_completions", "models"),
        ("openai_responses", "models"),
        ("anthropic_messages", "v1/models"),
    ],
)
@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        ("", "/"),
        ("/v1", "/v1/"),
        ("/v1/", "/v1/"),
        ("/gateway/v1", "/gateway/v1/"),
        ("/compatible", "/compatible/"),
        ("/compatible//", "/compatible//"),
    ],
)
def test_models_url_preserves_the_sdk_base(
    protocol: Protocol,
    suffix: str,
    path: str,
    prefix: str,
) -> None:
    assert models_url("https://relay.example.com" + path, protocol=protocol) == (
        "https://relay.example.com" + prefix + suffix
    )


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


def test_non_2xx_response_carries_status_and_body_to_the_caller() -> None:
    """密钥/URL 填错时，用户得看到上游原话才能照着改（ADR-0015：原样透传）。"""

    async def scenario() -> None:
        client = FakeHttpClient(
            FakeResponse({}, status_code=401, text='{"error":"Invalid API key"}')
        )

        with pytest.raises(ModelDiscoveryError, match=r"HTTP 401.*Invalid API key"):
            await discover_openai_models(profile(), http_client=client)

    asyncio.run(scenario())


def test_discovery_rejects_malformed_model_entries() -> None:
    async def scenario() -> None:
        client = FakeHttpClient(FakeResponse({"data": [{"id": "bad-owner", "owned_by": 42}]}))

        with pytest.raises(ModelDiscoveryError, match="owned_by"):
            await discover_openai_models(profile(), http_client=client)

    asyncio.run(scenario())


def test_missing_owned_by_keeps_the_model_under_an_unknown_group() -> None:
    """``owned_by`` 只是选单分组标签；Anthropic 官方清单整个没有这个字段。

    缺一个显示细节不该让整份可寻址清单作废（2026-09-01 实测官方 /v1/models）。
    """

    async def scenario() -> None:
        client = FakeHttpClient(FakeResponse({"data": [{"id": "claude-opus-5"}]}))

        models = await discover_openai_models(profile(), http_client=client)

        assert [(m.model_id, m.owned_by) for m in models] == [("claude-opus-5", UNKNOWN_OWNER)]

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
        assert catalog.error == "模型清单上游不可达：upstream timed out"
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
