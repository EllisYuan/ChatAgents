"""端口层：Jina Reader 的最朴素调用——一个 ``GET r.jina.ai/{url}``。

专有 header（``x-markdown-chunking`` / ``x-max-tokens`` / ``x-target-selector``）
一个都不用；切分逻辑刻意留在编排层（ADR-0004）。
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from .._http import request_or_raise

JINA_READER_BASE_URL = "https://r.jina.ai/"


class ReaderPort(Protocol):
    async def fetch(self, url: str) -> str: ...


class JinaReaderPort:
    """Jina Reader 免鉴权也能用；配了 ``JINA_API_KEY`` 则带上更高配额。"""

    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("JINA_API_KEY")
        self._client = http_client

    async def fetch(self, url: str) -> str:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = await request_or_raise(
            self._client,
            "GET",
            f"{JINA_READER_BASE_URL}{url}",
            headers=headers,
        )
        return str(response.text)
