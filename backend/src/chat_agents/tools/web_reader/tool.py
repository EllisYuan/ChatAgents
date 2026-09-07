"""``web_reader`` 的胶水层：把契约、端口、编排三层接在一起，构成注册规格。

分节读取靠运行内记忆化（ADR-0005）：以 URL 为键存在 :class:`ToolExecutionContext`
的 memo 里，活在一次运行的生命周期内，避免同一 URL 被反复抓取。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..types import ToolExecutionContext, ToolResult, ToolSpec
from .contract import DESCRIPTION, NAME, PARAMETERS
from .orchestration import ReaderDocument, assemble_result, build_document
from .port import JinaReaderPort, ReaderPort

ReaderPortFactory = Callable[[ToolExecutionContext], ReaderPort]

TIMEOUT_SECONDS = 20.0
_MEMO_KEY_PREFIX = "web_reader:"


def _production_port(ctx: ToolExecutionContext) -> ReaderPort:
    return JinaReaderPort(ctx.http_client)


async def _run_with_port(
    arguments: dict[str, Any], ctx: ToolExecutionContext, port_factory: ReaderPortFactory
) -> ToolResult:
    url = arguments["url"]
    section_arg = arguments.get("section")

    memo_key = f"{_MEMO_KEY_PREFIX}{url}"
    doc = ctx.memo_get(memo_key)
    if not isinstance(doc, ReaderDocument):
        raw_markdown = await port_factory(ctx).fetch(url)
        doc = build_document(url, raw_markdown, calibration=ctx.token_calibration)
        ctx.memo_set(memo_key, doc)

    return assemble_result(doc, section_arg)


async def run(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    return await _run_with_port(arguments, ctx, _production_port)


def make_spec(port_factory: ReaderPortFactory = _production_port) -> ToolSpec:
    """以供应商 Port factory 构造工具规格；生产默认仍调用 Jina Reader。"""

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
