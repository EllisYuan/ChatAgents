"""工具执行器：调用工具的唯一入口。

超时、重试、错误分类、跨度记录、结果渲染全部集中在这里——工具本身只是一个干净的
异步函数（ADR-0004）。新加的工具只要挂进 ``tools.registry.TOOL_SPECS`` 就自动获得
这一整套横切能力，结构上不可能漏掉。
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from chat_agents.tools import ToolExternalFailure, ToolSpec
from chat_agents.tools.registry import TOOL_SPECS, tool_definitions

from .tool_execution import RunToolContext

MAX_ATTEMPTS_WHEN_RETRYABLE = 3
BACKOFF_BASE_SECONDS = 0.5


class ToolProgramError(RuntimeError):
    """程序错误：本项目自身的缺陷或配置缺失，中止运行（ADR-0006）。"""


def _backoff_seconds(attempt: int) -> float:
    jitter: float = random.uniform(0, BACKOFF_BASE_SECONDS)
    result: float = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + jitter
    return result


class ToolExecutor:
    def __init__(self, specs: dict[str, ToolSpec] | None = None) -> None:
        self._specs = specs if specs is not None else TOOL_SPECS

    def tool_definitions(self) -> list[dict[str, Any]]:
        if self._specs is TOOL_SPECS:
            defs: list[dict[str, Any]] = tool_definitions()
            return defs
        return [
            {"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in self._specs.values()
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: RunToolContext,
    ) -> str:
        """执行一次工具调用，返回渲染给模型的文本。

        外部失败（含重试耗尽）不抛异常，文本本身就是交回模型的结果。
        程序错误抛出 :class:`ToolProgramError`，由调用方中止运行。
        """
        spec = self._specs.get(name)
        if spec is None:
            raise ToolProgramError(f"未注册的工具: {name}")

        attempts = MAX_ATTEMPTS_WHEN_RETRYABLE if spec.retryable else 1
        last_failure: ToolExternalFailure | None = None

        for attempt in range(1, attempts + 1):
            span = ctx.span_recorder.start_span(tool_name=name, attempt=attempt)
            try:
                result = await asyncio.wait_for(
                    spec.handler(arguments, ctx), timeout=spec.timeout_s
                )
            except TimeoutError:
                last_failure = ToolExternalFailure(
                    f"{name} 超时（>{spec.timeout_s}s）", retryable=True
                )
                span.finish_error(reason=last_failure.reason, retryable=True)
            except ToolExternalFailure as exc:
                last_failure = exc
                span.finish_error(reason=exc.reason, retryable=exc.retryable)
                if not exc.retryable:
                    break
            except Exception as exc:
                span.finish_error(reason=str(exc), retryable=False)
                raise ToolProgramError(f"{name} 执行失败: {exc}") from exc
            else:
                span.finish_ok(result.structured)
                return str(result.model_text)

            if attempt < attempts:
                await asyncio.sleep(_backoff_seconds(attempt))

        assert last_failure is not None
        return str(last_failure.model_text)
