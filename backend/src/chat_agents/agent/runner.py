"""AgentRunner——纯 Async ReAct Loop（ADR-0008，issue #51）。

收一份消息序列与端点档案，吐一串运行事件——不碰数据库、不碰 HTTP、不知道 SSE
存在（本文件不 import 任何 HTTP 客户端库；连接工具用的 httpx 客户端由调用方
按运行生命周期创建、通过 ``http_client`` 参数递入，见 :meth:`AgentRunner.run`
的参数说明）。它触碰的唯一 I/O 经由两个抽象边界：``ModelPort``（ADR-0025 的
回放注入点）与 ``ToolExecutor``——后者是发出工具事件的唯一入口（ADR-0008），
本类只负责把两边吐出的事件翻译成运行事件，不自己编排并发、不自己算重试。

落库、落跨度、编码 SSE 由更外层的三重包装负责（``main.py``，见 issue #52），
Runner 完全不知道它们存在。

系统提示词的注入不在这一票范围内（见 ADR-0010、issue #54）——``messages``
即模型输入序列，Runner 原样喂给 ``ModelPort``，不在中间插入任何一条消息。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

from ..llm.effort import EffortTier
from ..llm.events import ModelCallCompleted
from ..llm.events import ReasoningDelta as ModelReasoningDelta
from ..llm.events import TextDelta as ModelTextDelta
from ..llm.message import ContentBlock, ModelMessage, ToolCallBlock, ToolResultBlock
from ..llm.port import ModelPort, get_model_port
from ..llm.profile import EndpointProfile
from .events import (
    IterationCompleted,
    IterationStarted,
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from .step_budget import STEP_BUDGETS
from .tool_execution import RunToolContext
from .tool_executor import ToolCallFinished, ToolCallStarted, ToolExecutor, ToolProgramError

ModelPortFactory = Callable[[EndpointProfile], ModelPort]


class AgentRunner:
    """纯 ReAct Loop：喂消息序列吐运行事件（模块 docstring 有完整说明）。"""

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor | None = None,
        model_port_factory: ModelPortFactory = get_model_port,
    ) -> None:
        self._tool_executor = tool_executor if tool_executor is not None else ToolExecutor()
        self._model_port_factory = model_port_factory

    async def run(
        self,
        messages: list[ModelMessage],
        *,
        profile: EndpointProfile,
        main_model: str,
        auxiliary_model: str,
        effort: EffortTier,
        http_client: Any,
        run_id: str | None = None,
    ) -> AsyncIterator[RunEvent]:
        """跑一条完整运行：用户消息 → 模型调用 → （工具调用 → 模型调用）* → 最终回答。

        ``main`` / ``auxiliary`` 两个模型角色共用同一份端点档案、独立的只有模型
        标识（ADR-0012）——因此这里吃一份 ``profile`` 加两个模型标识，不吃两份
        ``EndpointProfile``。``auxiliary_model`` 在本票的 ReAct Loop 里尚不发起
        任何调用（issue #57 会给它第一个调用者：标题生成），签名先把它接住，
        呼应 #57「Runner 收两份档案的签名不变」。

        ``http_client`` 交给工具执行上下文使用，其生命周期由调用方绑定到本次
        运行（issue #40）；类型标注为 ``Any`` 而非 ``httpx.AsyncClient``，是
        「Runner 零 HTTP import」这条验收标准的直接后果，不是偷懒。
        """
        del auxiliary_model  # 尚无调用者（issue #57），签名先留住见上方 docstring
        run_id = run_id if run_id is not None else str(uuid4())
        history: list[ModelMessage] = list(messages)
        port = self._model_port_factory(profile)
        tool_defs = self._tool_executor.tool_definitions()
        hard_cap = STEP_BUDGETS[effort].hard_cap
        ctx = RunToolContext(run_id=run_id, http_client=http_client)

        iteration = 0
        while iteration < hard_cap:
            iteration += 1
            yield IterationStarted(run_id=run_id, iteration=iteration)

            final_message: ModelMessage | None = None
            final_usage = None
            stop_reason = "unknown"
            try:
                async for event in port.stream(
                    messages=history,
                    tools=tool_defs,
                    model=main_model,
                    effort=effort,
                    profile=profile,
                ):
                    if isinstance(event, ModelTextDelta):
                        yield TextDelta(run_id=run_id, iteration=iteration, text=event.text)
                    elif isinstance(event, ModelReasoningDelta):
                        yield ReasoningDelta(run_id=run_id, iteration=iteration, text=event.text)
                    elif isinstance(event, ModelCallCompleted):
                        final_message = event.message
                        final_usage = event.usage
                        stop_reason = event.stop_reason
                    # ToolCallStarted/ToolCallArgsDelta/ToolCallCompleted：模型侧工具
                    # 调用意图的参数流式增量，不在这里转发（模块 docstring 已说明）。
            except Exception as exc:
                # 上游错误原样透传（ADR-0015）——这里只做「运行失败」的事件化，
                # 不分类、不吞掉，reason 就是异常本身的文本。
                yield RunFailed(run_id=run_id, iteration=iteration, reason=str(exc))
                return

            if final_message is None or final_usage is None:
                yield RunFailed(run_id=run_id, iteration=iteration, reason="模型调用未产出终态事件")
                return

            history.append(final_message)
            yield IterationCompleted(
                run_id=run_id,
                iteration=iteration,
                usage=final_usage,
                stop_reason=stop_reason,
            )

            tool_calls = [
                block for block in final_message.content if isinstance(block, ToolCallBlock)
            ]
            if not tool_calls:
                yield RunCompleted(run_id=run_id, iteration=iteration, message=final_message)
                return

            if iteration == hard_cap:
                # 这一轮的工具结果永远等不到下一次模型调用去读——执行它们纯属浪费，
                # 直接如实失败（CONTEXT.md「硬上限」：越限时截到上限，不静默截断）。
                yield RunFailed(
                    run_id=run_id,
                    iteration=iteration,
                    reason=f"达到步数硬上限（{hard_cap}），运行未能在预算内给出最终回答",
                )
                return

            results: list[ContentBlock] = []
            try:
                async for tool_event in self._tool_executor.run_calls(tool_calls, ctx):
                    if isinstance(tool_event, ToolCallStarted):
                        yield ToolStarted(
                            run_id=run_id,
                            iteration=iteration,
                            tool_call_id=tool_event.tool_call_id,
                            name=tool_event.name,
                            arguments=tool_event.arguments,
                        )
                    elif isinstance(tool_event, ToolCallFinished):
                        results.append(
                            ToolResultBlock(
                                tool_call_id=tool_event.tool_call_id, content=tool_event.result
                            )
                        )
                        yield ToolFinished(
                            run_id=run_id,
                            iteration=iteration,
                            tool_call_id=tool_event.tool_call_id,
                            name=tool_event.name,
                            result=tool_event.result,
                        )
            except ToolProgramError as exc:
                yield RunFailed(run_id=run_id, iteration=iteration, reason=str(exc))
                return

            history.append(ModelMessage(role="tool", content=tuple(results)))
