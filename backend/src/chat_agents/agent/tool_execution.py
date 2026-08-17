"""工具执行上下文与跨度记录接口。

这里的 HTTP 客户端是工具侧的、按运行生命周期持有的客户端，与 ``llm/`` 的适配器
LRU 客户端池是两回事，不合并（issue #40）。跨度记录的真实实现落在
``observability/``（尚未建成）；这里只定义结构接口与一个空实现，避免 ``agent/``
在这个工具层切缝完成之前就去依赖一个不存在的模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class SpanHandle(Protocol):
    def finish_ok(self, structured: dict[str, Any]) -> None: ...

    def finish_error(self, *, reason: str, retryable: bool) -> None: ...


class SpanRecorder(Protocol):
    def start_span(self, *, tool_name: str, attempt: int) -> SpanHandle: ...


class NullSpanHandle:
    def finish_ok(self, structured: dict[str, Any]) -> None:
        pass

    def finish_error(self, *, reason: str, retryable: bool) -> None:
        pass


class NullSpanRecorder:
    """跨度记录尚未落地前的占位实现——不落任何东西，不报错。"""

    def start_span(self, *, tool_name: str, attempt: int) -> SpanHandle:
        return NullSpanHandle()


@dataclass(slots=True)
class RunToolContext:
    """满足 ``tools.types.ToolExecutionContext`` 结构接口的具体实现。"""

    run_id: str
    http_client: httpx.AsyncClient
    span_recorder: SpanRecorder = field(default_factory=NullSpanRecorder)
    _memo: dict[str, Any] = field(default_factory=dict)

    def memo_get(self, key: str) -> Any | None:
        return self._memo.get(key)

    def memo_set(self, key: str, value: Any) -> None:
        self._memo[key] = value
