"""三个自有 `Custom` 载荷（ADR-0009/0021）。

AG-UI 的 `CustomEvent` 只约束信封 `{name, value}`，`value` 是 `Any`——三个
载荷是整份契约里唯一无人替我们把关的部分，因此单独建 Pydantic 模型，供
`main.py` 注入进 `app.openapi()` 的 `components.schemas`（issue #59）。

**一律 snake_case，不随 AG-UI 信封走 camelCase**（ADR-0021）：这里不配
`alias_generator`，任何人「顺手」加上都是契约漂移，靠 `test_sse.py` 的
逐字段断言守住。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..llm.events import UsageState


class UsagePayload(BaseModel):
    """`chatagents.usage`——一次模型调用完成时发。"""

    role: Literal["main", "auxiliary"]
    model: str
    usage_status: UsageState
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None


class SpanPayload(BaseModel):
    """`chatagents.span`——模型调用跨度闭合时发；工具跨度不自己发这个事件。"""

    span_id: str
    parent_span_id: str | None
    kind: Literal["llm"]
    duration_ms: int


class ToolResultPayload(BaseModel):
    """`chatagents.tool_result`——渲染文本走 `TOOL_CALL_RESULT`，结构化走这里。

    `result` 与 `TOOL_CALL_RESULT.content` 同源（`ToolFinished.result`）——
    外部失败已由 `ToolExecutor` 编码进这段文本本身，这里不重复建错误标记。
    """

    tool_call_id: str
    result: str
