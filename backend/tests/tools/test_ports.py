import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from chat_agents.tools.types import ToolExternalFailure
from chat_agents.tools.web_reader.port import JinaReaderPort
from chat_agents.tools.web_search.port import TavilySearchPort


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_tavily_search_uses_the_plainest_call_with_answer_and_raw_content_off():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"title": "t", "url": "u", "content": "c"}]})

    client = _client(handler)
    port = TavilySearchPort(client, api_key="test-key")

    hits = asyncio.run(port.search("查询", max_results=3))

    assert captured["json"]["include_answer"] is False
    assert captured["json"]["include_raw_content"] is False
    assert captured["json"]["max_results"] == 3
    assert hits[0].title == "t"
    asyncio.run(client.aclose())


def test_tavily_search_requires_api_key():
    client = _client(lambda r: httpx.Response(200, json={"results": []}))
    with pytest.raises(RuntimeError):
        TavilySearchPort(client, api_key=None)
    asyncio.run(client.aclose())


def test_tavily_search_rate_limit_is_retryable_external_failure():
    client = _client(lambda r: httpx.Response(429, text="slow down"))
    port = TavilySearchPort(client, api_key="test-key")

    with pytest.raises(ToolExternalFailure) as exc_info:
        asyncio.run(port.search("查询", max_results=3))

    assert exc_info.value.retryable is True
    asyncio.run(client.aclose())


def test_tavily_search_bad_request_is_not_retryable():
    client = _client(lambda r: httpx.Response(400, text="bad"))
    port = TavilySearchPort(client, api_key="test-key")

    with pytest.raises(ToolExternalFailure) as exc_info:
        asyncio.run(port.search("查询", max_results=3))

    assert exc_info.value.retryable is False
    asyncio.run(client.aclose())


def test_tavily_search_malformed_body_is_external_failure_not_a_crash():
    client = _client(lambda r: httpx.Response(200, text="not json"))
    port = TavilySearchPort(client, api_key="test-key")

    with pytest.raises(ToolExternalFailure) as exc_info:
        asyncio.run(port.search("查询", max_results=3))

    assert exc_info.value.retryable is False
    asyncio.run(client.aclose())


def test_jina_reader_hits_the_plain_get_endpoint():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, text="# 标题\n正文")

    client = _client(handler)
    port = JinaReaderPort(client, api_key=None)

    markdown = asyncio.run(port.fetch("https://example.com/post"))

    assert captured["url"] == "https://r.jina.ai/https://example.com/post"
    assert "authorization" not in captured["headers"]
    assert markdown == "# 标题\n正文"
    asyncio.run(client.aclose())


def test_jina_reader_adds_bearer_header_when_key_configured():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, text="ok")

    client = _client(handler)
    port = JinaReaderPort(client, api_key="secret")

    asyncio.run(port.fetch("https://example.com"))

    assert captured["headers"]["authorization"] == "Bearer secret"
    asyncio.run(client.aclose())


def test_jina_reader_server_error_is_retryable():
    client = _client(lambda r: httpx.Response(503, text="down"))
    port = JinaReaderPort(client, api_key=None)

    with pytest.raises(ToolExternalFailure) as exc_info:
        asyncio.run(port.fetch("https://example.com"))

    assert exc_info.value.retryable is True
    asyncio.run(client.aclose())
