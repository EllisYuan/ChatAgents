"""端口层：Tavily Search 的最朴素调用——一个 POST，没有 answer、没有 raw content。"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from .._http import request_or_raise
from ..types import ToolExternalFailure
from .orchestration import SearchHit

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class SearchPort(Protocol):
    async def search(self, query: str, *, max_results: int) -> list[SearchHit]: ...


class TavilySearchPort:
    """Tavily Search 的 HTTP 端口。``include_answer`` 与 ``include_raw_content`` 常关。"""

    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None) -> None:
        key = api_key if api_key is not None else os.environ.get("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY 未配置")  # 程序错误：配置缺失
        self._api_key = key
        self._client = http_client

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        response = await request_or_raise(
            self._client,
            "POST",
            TAVILY_SEARCH_URL,
            json={
                "api_key": self._api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        try:
            payload = response.json()
            raw_results = payload["results"]
            return [
                SearchHit(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=item.get("score"),
                )
                for item in raw_results
            ]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            # 供应商返回的响应体不是预期形状：这是对方的问题，不是我们的 bug（ADR-0006）。
            raise ToolExternalFailure(
                f"Tavily 返回了无法解析的响应体: {exc}", retryable=False
            ) from exc
