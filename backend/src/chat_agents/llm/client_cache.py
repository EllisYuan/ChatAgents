"""httpx/httpx2 客户端按 base_url 缓存，LRU 上限 8。

两库并存是预期状态（ADR-0025）：anthropic SDK 用 ``httpx``，openai SDK（两个协议
共用同一个 SDK）用 ``httpx2``。两个 LRU 各自独立，互不挤占对方的淘汰名额。
"""

from collections import OrderedDict
from collections.abc import Callable
from typing import Final, TypeVar

import httpx
import httpx2

_CAPACITY: Final[int] = 8

_ClientT = TypeVar("_ClientT")


def _get_or_create(
    cache: OrderedDict[str, _ClientT], base_url: str, make: Callable[[], _ClientT]
) -> _ClientT:
    if base_url in cache:
        cache.move_to_end(base_url)
        return cache[base_url]
    client = make()
    cache[base_url] = client
    if len(cache) > _CAPACITY:
        cache.popitem(last=False)
    return client


class HttpClientCache:
    def __init__(self) -> None:
        self._httpx_clients: OrderedDict[str, httpx.AsyncClient] = OrderedDict()
        self._httpx2_clients: OrderedDict[str, httpx2.AsyncClient] = OrderedDict()

    def get_httpx_client(self, base_url: str) -> httpx.AsyncClient:
        return _get_or_create(
            self._httpx_clients, base_url, lambda: httpx.AsyncClient(base_url=base_url)
        )

    def get_httpx2_client(self, base_url: str) -> httpx2.AsyncClient:
        return _get_or_create(
            self._httpx2_clients, base_url, lambda: httpx2.AsyncClient(base_url=base_url)
        )
