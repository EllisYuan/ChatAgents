"""契约层的共享类型：工具规格、工具结果、外部失败。

零依赖——只认识 Python 标准库与 ``Protocol``，不认识任何供应商，也不认识执行器。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolExecutionContext(Protocol):
    """工具执行上下文的结构接口。

    具体实现落在 ``agent/``（见 ADR-0007）；这里只描述工具函数需要什么，
    不认识实现是谁。
    """

    run_id: str
    token_calibration: float  # 本次运行主模型的 token 校准系数，无实测数据时为 1.0（ADR-0020）

    @property
    def http_client(self) -> Any:  # httpx.AsyncClient，避免 tools/ 依赖具体类型来源
        ...

    def memo_get(self, key: str) -> Any | None: ...

    def memo_set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolResult:
    """一份结果两个出口：``structured`` 进跨度，``model_text`` 进模型。"""

    structured: dict[str, Any]
    model_text: str


class ToolExternalFailure(Exception):
    """外部失败：交回模型，不中止运行（ADR-0006）。"""

    def __init__(self, reason: str, *, retryable: bool, model_text: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.model_text = model_text if model_text is not None else reason


ToolHandler = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """工具的注册元数据：契约 + 差异化的横切参数（配置在工具身上，逻辑在执行器里）。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema，三种协议共用同一份
    handler: ToolHandler
    timeout_s: float
    retryable: bool
    parallelizable: bool = True
