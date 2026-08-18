"""AgentRunner——纯 Async ReAct Loop（ADR-0008，issue #51）。

收一份消息序列与端点档案，吐一串运行事件——不碰数据库、不碰 HTTP、不知道 SSE
存在（本文件不 import 任何 HTTP 客户端库；连接工具用的 httpx 客户端由调用方
按运行生命周期创建、通过 ``http_client`` 参数递入，见 :meth:`AgentRunner.run`
的参数说明）。它触碰的唯一 I/O 经由两个抽象边界：``ModelPort``（ADR-0025 的
回放注入点）与 ``ToolExecutor``——后者是发出工具事件的唯一入口（ADR-0008），
本类只负责把两边吐出的事件翻译成运行事件，不自己编排并发、不自己算重试。

落库、落跨度、编码 SSE 由更外层的三重包装负责（``main.py``，见 issue #52），
Runner 完全不知道它们存在。

系统提示词作为独立运行配置传给 ``ModelPort``（见 ADR-0010、issue #54）。
``messages`` 仍是对话记忆序列，Runner 原样喂给 ``ModelPort``，不在中间插入任何
system 消息。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID, uuid4

from ..llm.effort import EffortTier
from ..llm.events import ModelCallCompleted
from ..llm.events import ReasoningDelta as ModelReasoningDelta
from ..llm.events import TextDelta as ModelTextDelta
from ..llm.message import ContentBlock, ModelMessage, TextBlock, ToolCallBlock, ToolResultBlock
from ..llm.port import ModelPort, get_model_port
from ..llm.profile import EndpointProfile
from ..validation import MAX_TITLE_LENGTH
from .events import (
    IterationCompleted,
    IterationStarted,
    ReasoningDelta,
    RunCompleted,
    RunEvent,
    RunFailed,
    TextDelta,
    TitleGenerated,
    TitleGenerationStarted,
    ToolFinished,
    ToolStarted,
)
from .step_budget import STEP_BUDGETS
from .tool_execution import RunToolContext
from .tool_executor import ToolCallFinished, ToolCallStarted, ToolExecutor, ToolProgramError

ModelPortFactory = Callable[[EndpointProfile], ModelPort]
_TITLE_TIMEOUT_SECONDS = 5.0


def _fallback_title(text: str) -> str:
    """把首条用户消息压成公开列表可用的一行标题。"""

    normalized = " ".join(text.strip().split())
    if len(normalized) > MAX_TITLE_LENGTH:
        return f"{normalized[:MAX_TITLE_LENGTH]}..."
    return normalized or "新对话"


def _first_user_text(messages: list[ModelMessage]) -> str | None:
    for message in messages:
        if message.role == "user":
            text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
            if text:
                return text
    return None


class AgentRunner:
    """纯 ReAct Loop：喂消息序列吐运行事件（模块 docstring 有完整说明）。"""

    async def _generate_title(
        self,
        *,
        port: ModelPort,
        profile: EndpointProfile,
        model: str,
        effort: EffortTier,
        user_text: str,
        session_id: UUID,
        run_id: str,
    ) -> TitleGenerated:
        """调用 auxiliary 生成标题；任何运行时失败都转成回落结果。"""

        from .versioning import TITLE_PROMPT_TEMPLATE

        fallback = _fallback_title(user_text)
        usage = None
        try:
            completed: ModelCallCompleted | None = None
            async for event in port.stream(
                messages=[ModelMessage(role="user", content=(TextBlock(text=user_text),))],
                tools=[],
                model=model,
                effort=effort,
                profile=profile,
                system_prompt=TITLE_PROMPT_TEMPLATE,
            ):
                if isinstance(event, ModelCallCompleted):
                    completed = event
            if completed is None:
                raise RuntimeError("标题模型调用未产出终态事件")
            usage = completed.usage
            generated = "".join(
                block.text for block in completed.message.content if isinstance(block, TextBlock)
            )
            title = " ".join(generated.strip().split())
            if not title:
                raise RuntimeError("标题模型调用未产出文本")
            return TitleGenerated(
                run_id=run_id,
                session_id=session_id,
                title=title[:MAX_TITLE_LENGTH],
                usage=usage,
            )
        except Exception as exc:
            return TitleGenerated(
                run_id=run_id,
                session_id=session_id,
                title=fallback,
                usage=usage,
                error=str(exc),
            )

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
        session_id: UUID | None = None,
        generate_title: bool = False,
        system_prompt: str | None = None,
        prompt_version_id: str | None = None,
        tool_schema_version_id: str | None = None,
    ) -> AsyncIterator[RunEvent]:
        """跑一条完整运行：用户消息 → 模型调用 → （工具调用 → 模型调用）* → 最终回答。

        ``main`` / ``auxiliary`` 两个模型角色共用同一份端点档案、独立的只有模型
        标识（ADR-0012）——因此这里吃一份 ``profile`` 加两个模型标识，不吃两份
        ``EndpointProfile``。``generate_title`` 为真时，首条用户消息会在主模型
        调用开始的同时发起一次无工具的 auxiliary 调用；它的产出只走标题事件，
        永不进入消息历史。

        ``http_client`` 交给工具执行上下文使用，其生命周期由调用方绑定到本次
        运行（issue #40）；类型标注为 ``Any`` 而非 ``httpx.AsyncClient``，是
        「Runner 零 HTTP import」这条验收标准的直接后果，不是偷懒。
        """
        run_id = run_id if run_id is not None else str(uuid4())
        history: list[ModelMessage] = list(messages)
        port = self._model_port_factory(profile)
        title_task: asyncio.Task[TitleGenerated] | None = None
        title_emitted = False
        first_user_text = _first_user_text(history)
        if generate_title and session_id is None:
            raise ValueError("标题生成需要 session_id")
        if generate_title and session_id is not None and first_user_text is not None:
            title_task = asyncio.create_task(
                self._generate_title(
                    port=port,
                    profile=profile,
                    model=auxiliary_model,
                    effort=effort,
                    user_text=first_user_text,
                    session_id=session_id,
                    run_id=run_id,
                )
            )
            yield TitleGenerationStarted(run_id=run_id, model=auxiliary_model)

        async def await_title() -> TitleGenerated:
            """在有限时间内收束 auxiliary，避免拖住主运行终态。"""

            assert title_task is not None
            assert session_id is not None
            assert first_user_text is not None
            try:
                return await asyncio.wait_for(
                    asyncio.shield(title_task), timeout=_TITLE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                title_task.cancel()
                await asyncio.gather(title_task, return_exceptions=True)
                return TitleGenerated(
                    run_id=run_id,
                    session_id=session_id,
                    title=_fallback_title(first_user_text),
                    error="标题模型调用超时",
                )

        tool_defs = self._tool_executor.tool_definitions()
        hard_cap = STEP_BUDGETS[effort].hard_cap
        ctx = RunToolContext(run_id=run_id, http_client=http_client)

        iteration = 0
        while iteration < hard_cap:
            iteration += 1
            yield IterationStarted(
                run_id=run_id,
                iteration=iteration,
                prompt_version_id=prompt_version_id,
                tool_schema_version_id=tool_schema_version_id,
            )

            final_message: ModelMessage | None = None
            final_usage = None
            stop_reason = "unknown"
            try:
                stream_kwargs: dict[str, Any] = {
                    "messages": history,
                    "tools": tool_defs,
                    "model": main_model,
                    "effort": effort,
                    "profile": profile,
                }
                if system_prompt is not None:
                    stream_kwargs["system_prompt"] = system_prompt
                async for event in port.stream(**stream_kwargs):
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
                    if title_task is not None and not title_emitted and title_task.done():
                        yield title_task.result()
                        title_emitted = True
            except Exception as exc:
                # 上游错误原样透传（ADR-0015）——这里只做「运行失败」的事件化，
                # 不分类、不吞掉，reason 就是异常本身的文本。
                if title_task is not None and not title_emitted:
                    yield await await_title()
                    title_emitted = True
                yield RunFailed(run_id=run_id, iteration=iteration, reason=str(exc))
                return

            if final_message is None or final_usage is None:
                if title_task is not None and not title_emitted:
                    yield await await_title()
                    title_emitted = True
                yield RunFailed(run_id=run_id, iteration=iteration, reason="模型调用未产出终态事件")
                return

            history.append(final_message)
            yield IterationCompleted(
                run_id=run_id,
                iteration=iteration,
                message=final_message,
                usage=final_usage,
                stop_reason=stop_reason,
            )

            tool_calls = [
                block for block in final_message.content if isinstance(block, ToolCallBlock)
            ]
            if not tool_calls:
                if title_task is not None and not title_emitted:
                    yield await await_title()
                    title_emitted = True
                yield RunCompleted(run_id=run_id, iteration=iteration, message=final_message)
                return

            if iteration == hard_cap:
                # 这一轮的工具结果永远等不到下一次模型调用去读——执行它们纯属浪费，
                # 直接如实失败（CONTEXT.md「硬上限」：越限时截到上限，不静默截断）。
                if title_task is not None and not title_emitted:
                    yield await await_title()
                    title_emitted = True
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
                if title_task is not None and not title_emitted:
                    yield await await_title()
                    title_emitted = True
                yield RunFailed(run_id=run_id, iteration=iteration, reason=str(exc))
                return

            history.append(ModelMessage(role="tool", content=tuple(results)))
