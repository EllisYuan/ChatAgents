"""端口层共用的 HTTP 请求与错误分类（ADR-0006）。

超时、连接错误、429、5xx 归类为可重试的外部失败；其余 4xx 归类为不可重试的外部失败。
两个供应商端口都走这条路径，不各自维护一份分类逻辑。
"""

from __future__ import annotations

from typing import Any

import httpx

from .types import ToolExternalFailure


async def request_or_raise(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise ToolExternalFailure(f"请求超时: {url}", retryable=True) from exc
    except httpx.ConnectError as exc:
        raise ToolExternalFailure(f"无法连接: {url}", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise ToolExternalFailure(f"请求失败: {url} ({exc})", retryable=False) from exc

    if response.status_code == 429 or response.status_code >= 500:
        raise ToolExternalFailure(f"供应商返回 {response.status_code}: {url}", retryable=True)
    if response.status_code >= 400:
        raise ToolExternalFailure(f"供应商返回 {response.status_code}: {url}", retryable=False)
    return response
