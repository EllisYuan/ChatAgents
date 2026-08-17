"""``web_reader`` 的胶水层：把契约、端口、编排三层接在一起，构成注册规格。

分节读取靠运行内记忆化（ADR-0005）：以 URL 为键存在 :class:`ToolExecutionContext`
的 memo 里，活在一次运行的生命周期内，避免同一 URL 被反复抓取。
"""

from __future__ import annotations

from typing import Any

from ..types import ToolExecutionContext, ToolResult, ToolSpec
from .contract import DESCRIPTION, NAME, PARAMETERS
from .orchestration import ReaderDocument, assemble_result, build_document
from .port import JinaReaderPort

TIMEOUT_SECONDS = 20.0
_MEMO_KEY_PREFIX = "web_reader:"


async def run(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    url = arguments["url"]
    section_arg = arguments.get("section")

    memo_key = f"{_MEMO_KEY_PREFIX}{url}"
    doc = ctx.memo_get(memo_key)
    if not isinstance(doc, ReaderDocument):
        port = JinaReaderPort(ctx.http_client)
        raw_markdown = await port.fetch(url)
        doc = build_document(url, raw_markdown)
        ctx.memo_set(memo_key, doc)

    return assemble_result(doc, section_arg)


SPEC = ToolSpec(
    name=NAME,
    description=DESCRIPTION,
    parameters=PARAMETERS,
    handler=run,
    timeout_s=TIMEOUT_SECONDS,
    retryable=True,
    parallelizable=True,
)
