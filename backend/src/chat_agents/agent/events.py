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
from uuid import NAMESPACE_URL, UUID, uuid5

from ..llm.events import Usage
from ..llm.message import ModelMessage


def _run_namespace(run_id: str) -> UUID:
    try:
        return UUID(run_id)
    except ValueError:
        # 回放测试可使用非 UUID 的运行标识，先把它稳定映射到 UUID 命名空间。
        return uuid5(NAMESPACE_URL, run_id)


def reasoning_message_id(run_id: str, iteration: int) -> UUID:
    """为一次迭代的显示摘要派生独立且稳定的消息标识。"""

    return uuid5(_run_namespace(run_id), f"{iteration}:reasoning")


def assistant_message_id(run_id: str, iteration: int) -> UUID:
    """为一次迭代产出的助手消息派生稳定标识（ADR-0009：``uuid5`` 确定性派生）。"""

    return uuid5(_run_namespace(run_id), f"{iteration}:assistant")


def tool_message_id(run_id: str, iteration: int) -> UUID:
    """为一次迭代的工具结果组合消息派生稳定标识（同一轮全部工具结果落一行）。"""

    return uuid5(_run_namespace(run_id), f"{iteration}:tool")


def llm_span_id(run_id: str, iteration: int) -> UUID:
    """为一次迭代的模型调用跨度派生稳定标识（线上 ``chatagents.span`` 载荷用）。"""

    return uuid5(_run_namespace(run_id), f"{iteration}:span")


def title_span_id(run_id: str) -> UUID:
    """为一次运行的标题模型调用派生稳定的兄弟跨度标识。"""

    return uuid5(_run_namespace(run_id), "title:span")


def tool_span_id(run_id: str, tool_call_id: str) -> UUID:
    """为一次工具调用派生稳定的跨度标识（issue #69：工具跨度持久化）。"""

    return uuid5(_run_namespace(run_id), f"tool:{tool_call_id}")


@dataclass(frozen=True, slots=True)
class IterationStarted:
    """一次迭代边界及本次运行采用的输入配置版本指代。"""

    run_id: str
    iteration: int
    prompt_version_id: str | None = None
    tool_schema_version_id: str | None = None


@dataclass(frozen=True, slots=True)
class TitleGenerationStarted:
    """标题 auxiliary 调用开始，供观测层打开兄弟跨度。"""

    run_id: str
    model: str


@dataclass(frozen=True, slots=True)
class TitleGenerated:
    """标题调用完成；失败时携带回落标题与错误原因。"""

    run_id: str
    session_id: UUID
    title: str
    usage: Usage | None = None
    error: str | None = None


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

    @property
    def message_id(self) -> UUID:
        """返回本次迭代共享的摘要消息标识，不复用助手消息标识。"""

        return reasoning_message_id(self.run_id, self.iteration)


@dataclass(frozen=True, slots=True)
class IterationCompleted:
    """一次迭代的边界终点——本次模型调用产出的完整助手消息、用量与终止原因。

    ``message`` 是这一轮追加进历史之前的那条助手消息（issue #52）：调用工具的
    中间轮次不会再产出 ``RunCompleted``，只有这个事件承载它们的完整内容，是
    ``persist`` 包装器逐轮落库消息表的唯一入口。
    """

    run_id: str
    iteration: int
    message: ModelMessage
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
    """``structured`` 与 ``chatagents.tool_result`` 的 ``structured`` 字段同源
    （issue #69）：真正跑通的工具调用才会产出它，耗尽重试的外部失败恒为
    ``None``——不是缺失标记，是结构性事实，观测层据此判定跨度 ``status``。
    """

    run_id: str
    iteration: int
    tool_call_id: str
    name: str
    result: str
    structured: dict[str, Any] | None


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
    | TitleGenerationStarted
    | TitleGenerated
    | TextDelta
    | ReasoningDelta
    | IterationCompleted
    | ToolStarted
    | ToolFinished
    | RunCompleted
    | RunFailed
)
