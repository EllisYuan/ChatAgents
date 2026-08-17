"""ModelEvent——一次模型调用内部事件（ADR-0008：与 ``agent/`` 的 RunEvent 是两级）。

不含任何线格式，`llm/` 之外没人知道 SSE 存在。上游错误按 ADR-0015 原样向上抛
出 SDK 自身异常，这里不定义失败事件类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .message import ModelMessage

UsageState = Literal["complete", "partial", "unavailable"]


@dataclass(frozen=True, slots=True)
class Usage:
    """用量三态（CONTEXT.md）：缺失一律不以 0 表示。"""

    state: UsageState
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    """显示摘要的增量（ADR-0017）。"""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCallStarted:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ToolCallArgsDelta:
    """原始 JSON 字符串增量，与 AG-UI ``TOOL_CALL_ARGS`` 同构。"""

    id: str
    args_delta: str


@dataclass(frozen=True, slots=True)
class ToolCallCompleted:
    id: str


@dataclass(frozen=True, slots=True)
class ModelCallCompleted:
    """一次模型调用的终态——正常结束或被中断，由 ``stop_reason``/``usage.state`` 区分。"""

    message: ModelMessage
    usage: Usage
    stop_reason: str


ModelEvent = (
    TextDelta
    | ReasoningDelta
    | ToolCallStarted
    | ToolCallArgsDelta
    | ToolCallCompleted
    | ModelCallCompleted
)
