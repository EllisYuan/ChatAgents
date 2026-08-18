"""``web_search`` 的胶水层：把契约、端口、编排三层接在一起，构成注册规格。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..types import ToolExecutionContext, ToolResult, ToolSpec
from .contract import DESCRIPTION, NAME, PARAMETERS
from .orchestration import assemble_result
from .port import SearchPort, TavilySearchPort

SearchPortFactory = Callable[[ToolExecutionContext], SearchPort]

DEFAULT_MAX_RESULTS = 5
TIMEOUT_SECONDS = 15.0


def _production_port(ctx: ToolExecutionContext) -> SearchPort:
    return TavilySearchPort(ctx.http_client)


async def _run_with_port(
    arguments: dict[str, Any], ctx: ToolExecutionContext, port_factory: SearchPortFactory
) -> ToolResult:
    query = arguments["query"]
    max_results = arguments.get("max_results", DEFAULT_MAX_RESULTS)
    hits = await port_factory(ctx).search(query, max_results=max_results)
    return assemble_result(query, hits)


async def run(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    return await _run_with_port(arguments, ctx, _production_port)


def make_spec(port_factory: SearchPortFactory = _production_port) -> ToolSpec:
    """以供应商 Port factory 构造工具规格；生产默认仍调用 Tavily。"""

    async def handler(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        return await _run_with_port(arguments, ctx, port_factory)

    return ToolSpec(
        name=NAME,
        description=DESCRIPTION,
        parameters=PARAMETERS,
        handler=handler,
        timeout_s=TIMEOUT_SECONDS,
        retryable=True,
        parallelizable=True,
    )


SPEC = make_spec()
