"""同一 SDK base 下的发现与生成路径，经过真实 ModelPort / SDK / HTTP。"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from chat_agents.llm.endpoint_address import AddressMode
from chat_agents.llm.events import ModelCallCompleted
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.model_discovery import ModelDiscoveryError, discover_openai_models
from chat_agents.llm.port import get_model_port, model_port_scope
from chat_agents.llm.profile import EndpointProfile
from chat_agents.llm.protocol import Protocol
from pydantic import SecretStr

from ..endpoint_gateway import ANSWER, API_KEY, MODEL, endpoint_gateway


async def _generate(profile: EndpointProfile) -> ModelCallCompleted:
    async with model_port_scope(profile, shared_client=False) as port:
        events = [
            event
            async for event in port.stream(
                messages=[ModelMessage(role="user", content=(TextBlock("hi"),))],
                tools=[],
                model=MODEL,
                effort="medium",
                profile=profile,
            )
        ]
    completed = [event for event in events if isinstance(event, ModelCallCompleted)]
    assert len(completed) == 1
    assert TextBlock(ANSWER) in completed[0].message.content
    assert completed[0].usage.state == "complete"
    return completed[0]


def _profile(
    origin: str,
    base_path: str,
    protocol: Protocol,
    mode: AddressMode = "sdk_native",
    *,
    auth_field: str = "Authorization",
    api_key: str = API_KEY,
) -> EndpointProfile:
    return EndpointProfile(
        name="fixture",
        protocol=protocol,
        base_url=origin + base_path,
        auth_field=auth_field,
        api_key=SecretStr(api_key),
        address_mode=mode,
    )


CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "endpoint_address_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=lambda case: f"{case['mode']}-{case['protocol']}-{case['path'] or 'root'}",
)
def test_real_sdk_and_discovery_follow_the_resolved_addresses(case: dict[str, Any]) -> None:
    """三种模式下真实 SDK / 发现打出的 path，与共享用例表逐条一致。"""

    protocol: Protocol = case["protocol"]
    mode: AddressMode = case["mode"]
    discovery: str | None = case["discovery"]

    async def scenario() -> None:
        routes: dict[tuple[str, str], Protocol | None] = {("POST", case["generation"]): protocol}
        if discovery is not None:
            routes[("GET", discovery)] = None
        with endpoint_gateway(routes) as gateway:
            profile = _profile(gateway.origin, case["path"], protocol, mode)

            if discovery is None:
                # 推不出清单地址就不许发请求——试探别的路径等于替用户猜配置。
                with pytest.raises(ModelDiscoveryError, match="无法推导模型清单地址"):
                    await discover_openai_models(profile)
                assert gateway.requests == []
            else:
                models = await discover_openai_models(profile)
                assert MODEL in [item.model_id for item in models]

            await _generate(profile)
            assert gateway.requests[-1] == ("POST", case["generation"], MODEL)
            assert [request[1] for request in gateway.requests if request[0] == "GET"] == (
                [] if discovery is None else [discovery]
            )
            # 钩子只改那一个生成 POST，不额外重发或改写第二个请求。
            assert len([r for r in gateway.requests if r[0] == "POST"]) == 1

    asyncio.run(scenario())


def test_rewriting_the_generation_url_keeps_the_key_and_body_intact() -> None:
    """改的只是 URL：鉴权头与请求体仍由 SDK 构造，钩子一个字段都不碰。"""

    async def scenario() -> None:
        with endpoint_gateway({("POST", "/custom/infer"): "openai_chat_completions"}) as gateway:
            profile = _profile(gateway.origin, "/custom/infer", "openai_chat_completions", "full")
            await _generate(profile)

            assert gateway.requests == [("POST", "/custom/infer", MODEL)]
            assert gateway.headers[0]["authorization"] == f"Bearer {API_KEY}"
            assert gateway.headers[0]["host"] == gateway.origin.removeprefix("http://")
            assert gateway.payloads[0]["messages"][0]["content"] == "hi"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "protocol", ["openai_chat_completions", "openai_responses", "anthropic_messages"]
)
def test_bearer_gateway_accepts_generation_with_a_bearer_header(protocol: Protocol) -> None:
    async def scenario() -> None:
        path = (
            "/v1/messages"
            if protocol == "anthropic_messages"
            else ("/v1/responses" if protocol == "openai_responses" else "/v1/chat/completions")
        )
        with endpoint_gateway(
            {("POST", path): protocol},
            required_authorization=f"Bearer {API_KEY}",
        ) as gateway:
            profile = _profile(
                gateway.origin,
                "/v1" if protocol != "anthropic_messages" else "",
                protocol,
            )
            try:
                await _generate(profile)
            finally:
                assert gateway.headers[0]["authorization"] == f"Bearer {API_KEY}"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "protocol", ["openai_chat_completions", "openai_responses", "anthropic_messages"]
)
@pytest.mark.parametrize(
    ("auth_field", "api_key", "expected"),
    [
        ("authorization", API_KEY, f"Bearer {API_KEY}"),
        ("Authorization", f"Bearer {API_KEY}", f"Bearer {API_KEY}"),
        ("Authorization", API_KEY, f"Bearer {API_KEY}"),
        ("x-api-key", API_KEY, API_KEY),
        ("X-Custom-Key", API_KEY, API_KEY),
        ("X-ChatAgents-Auth-Field", API_KEY, API_KEY),
        ("X-ChatAgents-Auth-Field-Alt", API_KEY, API_KEY),
    ],
)
def test_generation_sends_only_the_selected_auth_header(
    protocol: Protocol, auth_field: str, api_key: str, expected: str
) -> None:
    async def scenario() -> None:
        path = (
            "/v1/messages"
            if protocol == "anthropic_messages"
            else ("/v1/responses" if protocol == "openai_responses" else "/v1/chat/completions")
        )
        with endpoint_gateway({("POST", path): protocol}) as gateway:
            profile = _profile(
                gateway.origin,
                "/v1" if protocol != "anthropic_messages" else "",
                protocol,
                auth_field=auth_field,
                api_key=api_key,
            )
            await _generate(profile)
            headers = gateway.headers[0]
            assert headers[auth_field.lower()] == expected
            assert gateway.authorization_values[0] == (
                [expected] if auth_field.lower() == "authorization" else []
            )
            assert gateway.api_key_values[0] == (
                [expected] if auth_field.lower() == "x-api-key" else []
            )
            if auth_field.lower() != "x-chatagents-auth-field":
                assert "x-chatagents-auth-field" not in headers
            if auth_field.lower() != "x-chatagents-auth-field-alt":
                assert "x-chatagents-auth-field-alt" not in headers
            if auth_field.lower() != "authorization":
                assert "authorization" not in headers
            if auth_field.lower() != "x-api-key":
                assert "x-api-key" not in headers

    asyncio.run(scenario())


@pytest.mark.parametrize("protocol", ["openai_responses", "anthropic_messages"])
def test_shared_http_client_keeps_auth_per_profile(protocol: Protocol) -> None:
    from chat_agents.llm.client_cache import HttpClientCache

    async def scenario() -> None:
        path = "/v1/messages" if protocol == "anthropic_messages" else "/v1/responses"
        with endpoint_gateway({("POST", path): protocol}) as gateway:
            cache = HttpClientCache()
            base = "/v1" if protocol == "openai_responses" else ""
            first = _profile(gateway.origin, base, protocol)
            second = _profile(
                gateway.origin,
                base,
                protocol,
                auth_field="x-api-key",
                api_key="second-fixture-secret",
            )
            for profile in (first, second, first):
                port = get_model_port(profile, client_cache=cache)
                events = [
                    event
                    async for event in port.stream(
                        messages=[ModelMessage(role="user", content=(TextBlock("hi"),))],
                        tools=[],
                        model=MODEL,
                        effort="medium",
                        profile=profile,
                    )
                ]
                assert any(isinstance(event, ModelCallCompleted) for event in events)
            assert gateway.authorization_values == [
                [f"Bearer {API_KEY}"],
                [],
                [f"Bearer {API_KEY}"],
            ]
            assert gateway.api_key_values == [[], ["second-fixture-secret"], []]

    asyncio.run(scenario())


def test_custom_address_modes_never_use_the_shared_client_cache() -> None:
    """共享缓存以 base_url 为键，装不下同址两解释；误用必须当场报错而不是串地址。"""

    for mode in ("auto", "full"):
        profile = _profile("https://relay.example.com", "/v1/responses", "openai_responses", mode)
        with pytest.raises(ValueError, match="共享客户端缓存"):
            get_model_port(profile)


@pytest.mark.parametrize(
    ("base_path", "prefix"),
    [
        ("", "/"),
        ("/", "/"),
        ("/v1", "/v1/"),
        ("/v1/", "/v1/"),
        ("/gateway", "/gateway/"),
        ("/gateway/v1", "/gateway/v1/"),
        ("/compatible", "/compatible/"),
        ("/compatible//", "/compatible//"),
        ("/compatible/%2e%2e/v1", "/compatible/%2e%2e/v1/"),
    ],
)
@pytest.mark.parametrize(
    ("protocol", "discovery", "generation"),
    [
        ("openai_chat_completions", "models", "chat/completions"),
        ("openai_responses", "models", "responses"),
        ("anthropic_messages", "v1/models", "v1/messages"),
    ],
)
def test_discovery_and_real_sdk_use_the_same_base(
    base_path: str,
    prefix: str,
    protocol: Protocol,
    discovery: str,
    generation: str,
) -> None:
    async def scenario() -> None:
        with endpoint_gateway(
            {
                ("GET", prefix + discovery): None,
                ("POST", prefix + generation): protocol,
            }
        ) as gateway:
            profile = _profile(gateway.origin, base_path, protocol)
            models = await discover_openai_models(profile)
            assert MODEL in [item.model_id for item in models]
            await _generate(profile)
            assert gateway.requests == [
                ("GET", prefix + discovery, None),
                ("POST", prefix + generation, MODEL),
            ]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("protocol", "base_path", "actual_discovery"),
    [
        ("openai_chat_completions", "", "/models"),
        ("openai_responses", "", "/models"),
        ("anthropic_messages", "/v1", "/v1/v1/models"),
        ("anthropic_messages", "/v1/", "/v1/v1/models"),
    ],
)
def test_discovery_does_not_repair_a_base_that_generation_will_use_verbatim(
    protocol: Protocol,
    base_path: str,
    actual_discovery: str,
) -> None:
    async def scenario() -> None:
        with endpoint_gateway({("GET", "/v1/models"): None}) as gateway:
            profile = _profile(gateway.origin, base_path, protocol)
            with pytest.raises(ModelDiscoveryError, match="HTTP 404"):
                await discover_openai_models(profile)
            assert gateway.requests == [("GET", actual_discovery, None)]

    asyncio.run(scenario())
