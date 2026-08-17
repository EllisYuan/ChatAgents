"""``web_search`` 的胶水层：把契约、端口、编排三层接在一起，构成注册规格。"""

from __future__ import annotations

from typing import Any

from ..types import ToolExecutionContext, ToolResult, ToolSpec
from .contract import DESCRIPTION, NAME, PARAMETERS
from .orchestration import assemble_result
from .port import TavilySearchPort

DEFAULT_MAX_RESULTS = 5
TIMEOUT_SECONDS = 15.0


async def run(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    query = arguments["query"]
    max_results = arguments.get("max_results", DEFAULT_MAX_RESULTS)

    port = TavilySearchPort(ctx.http_client)
    hits = await port.search(query, max_results=max_results)
    return assemble_result(query, hits)


SPEC = ToolSpec(
    name=NAME,
    description=DESCRIPTION,
    parameters=PARAMETERS,
    handler=run,
    timeout_s=TIMEOUT_SECONDS,
    retryable=True,
    parallelizable=True,
)
