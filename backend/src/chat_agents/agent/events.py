"""RunEvent——一次运行对外产出的事件（ADR-0008，与 ``llm/events.py`` 的
``ModelEvent`` 是两级：那是一次模型调用内部的事件，这是一次运行的事件）。

不含任何线格式（不带 JSON 序列化、不带 SSE 帧头）。层级标识（``run_id`` /
``iteration``）随事件带出，供 observability 把它映射成跨度树——「跨度记录归
工具执行器」（ADR-0004）与此不冲突，执行器仍是发出工具事件的唯一入口，只是
发出的是事件而非跨度。

刻意不对 ``ModelEvent`` 做 1:1 机械转发：``ToolStarted`` / ``ToolFinished`` /
``RunCompleted`` / ``RunFailed`` 在模型调用层面根本不存在；``llm/`` 的
``ToolCallStarted`` / ``ToolCallArgsDelta`` / ``ToolCallCompleted`` 是模型侧
「正在流式吐出一次工具调用意图」的增量，与这里「执行器真的在跑这个工具」的
``ToolStarted`` / ``ToolFinished`` 是两件事，本票不转发前者。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..llm.events import Usage
from ..llm.message import ModelMessage


@dataclass(frozen=True, slots=True)
class IterationStarted:
    """一次迭代（一次模型调用 + 它触发的工具调用）的边界起点。"""

    run_id: str
    iteration: int


@dataclass(frozen=True, slots=True)
class TextDelta:
    run_id: str
    iteration: int
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    """显示摘要的增量（ADR-0017）。"""

    run_id: str
    iteration: int
    text: str


@dataclass(frozen=True, slots=True)
class IterationCompleted:
    """一次迭代的边界终点——本次模型调用的用量与终止原因。"""

    run_id: str
    iteration: int
    usage: Usage
    stop_reason: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    run_id: str
    iteration: int
    tool_call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolFinished:
    run_id: str
    iteration: int
    tool_call_id: str
    name: str
    result: str


@dataclass(frozen=True, slots=True)
class RunCompleted:
    """运行正常收尾——最终回答所在的那条助手消息。"""

    run_id: str
    iteration: int
    message: ModelMessage


@dataclass(frozen=True, slots=True)
class RunFailed:
    run_id: str
    iteration: int
    reason: str


RunEvent = (
    IterationStarted
    | TextDelta
    | ReasoningDelta
    | IterationCompleted
    | ToolStarted
    | ToolFinished
    | RunCompleted
    | RunFailed
)
