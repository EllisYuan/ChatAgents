"""httpx/httpx2 客户端按 base_url 缓存，LRU 上限 8（issue #45）。"""

import httpx
import httpx2
from chat_agents.llm.client_cache import HttpClientCache


def test_same_base_url_returns_same_httpx_client() -> None:
    cache = HttpClientCache()
    a = cache.get_httpx_client("https://api.anthropic.com")
    b = cache.get_httpx_client("https://api.anthropic.com")
    assert a is b
    assert isinstance(a, httpx.AsyncClient)


def test_same_base_url_returns_same_httpx2_client() -> None:
    cache = HttpClientCache()
    a = cache.get_httpx2_client("https://api.openai.com")
    b = cache.get_httpx2_client("https://api.openai.com")
    assert a is b
    assert isinstance(a, httpx2.AsyncClient)


def test_different_base_urls_get_different_clients() -> None:
    cache = HttpClientCache()
    a = cache.get_httpx_client("https://one.example.com")
    b = cache.get_httpx_client("https://two.example.com")
    assert a is not b


def test_lru_eviction_at_cap_eight() -> None:
    cache = HttpClientCache()
    clients = [cache.get_httpx_client(f"https://host-{i}.example.com") for i in range(8)]
    # A 9th distinct base_url evicts the least-recently-used entry (host-0).
    cache.get_httpx_client("https://host-8.example.com")
    evicted = cache.get_httpx_client("https://host-0.example.com")
    assert evicted is not clients[0]


def test_lru_touch_on_access_protects_from_eviction() -> None:
    cache = HttpClientCache()
    for i in range(8):
        cache.get_httpx_client(f"https://host-{i}.example.com")
    first = cache.get_httpx_client("https://host-0.example.com")  # touch: now most-recent
    cache.get_httpx_client("https://host-8.example.com")  # evicts host-1, not host-0
    assert cache.get_httpx_client("https://host-0.example.com") is first


def test_httpx_and_httpx2_caches_are_independent() -> None:
    cache = HttpClientCache()
    for i in range(8):
        cache.get_httpx_client(f"https://host-{i}.example.com")
    # Filling the httpx cache to capacity must not evict anything in the httpx2 cache.
    httpx2_client = cache.get_httpx2_client("https://openai.example.com")
    cache.get_httpx_client("https://host-8.example.com")
    assert cache.get_httpx2_client("https://openai.example.com") is httpx2_client
