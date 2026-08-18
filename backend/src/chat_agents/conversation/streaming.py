"""``persist``——业务事务的增量落库包装（issue #52，ADR-0008）。

每次模型调用完成即写一条助手消息，一轮工具结果全部到齐即写一条组合工具消息
——不攒到运行结束再一把写。写失败直接向上抛（业务事务，失败要报错），最终
由 ``transport.encode_sse`` 的外层 ``try/except`` 收敛成一条 ``RUN_ERROR``。
客户端断连时生成器被取消，已经落的部分保持完好——这正是「增量」买到的东西。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from ..agent.events import (
    IterationCompleted,
    RunEvent,
    TitleGenerated,
    ToolFinished,
    ToolStarted,
    tool_message_id,
)
from ..agent.events import assistant_message_id as _assistant_message_id
from ..llm.message import ModelMessage, ToolResultBlock
from .service import ConversationService


async def _append_message_in_short_transaction(
    *, session_factory: Any, session_id: UUID, message_id: UUID, message: ModelMessage
) -> None:
    """同 ``ConversationService.short_transaction_append`` 的事务写法。

    不直接调那个实例方法——它的实现完全不碰 ``self``，调它得先造一个可丢弃的
    ``ConversationService`` 占位实例，反而更绕；这里保持同样的「不借用请求级
    session」短事务写法，专供 ``persist`` 逐条增量写用。
    """

    async with session_factory() as session, session.begin():
        service = ConversationService(session)
        await service.append_model_message(
            session_id=session_id, message_id=message_id, message=message
        )


async def _set_generated_title_in_short_transaction(
    *, session_factory: Any, session_id: UUID, expected_title: str | None, title: str
) -> None:
    async with session_factory() as session, session.begin():
        service = ConversationService(session)
        await service.set_generated_title(session_id, expected_title=expected_title, title=title)


async def persist(
    events: AsyncIterator[RunEvent],
    *,
    session_id: UUID,
    session_factory: Any,
    expected_title: str | None = None,
    round_trip_message_ids: set[UUID] | None = None,
) -> AsyncIterator[RunEvent]:
    """透传每个 ``RunEvent``，旁路把消息增量写进 ``app.message``。"""

    tool_call_order: list[str] = []
    tool_results: dict[str, str] = {}

    async for event in events:
        if isinstance(event, TitleGenerated):
            await _set_generated_title_in_short_transaction(
                session_factory=session_factory,
                session_id=session_id,
                expected_title=expected_title,
                title=event.title,
            )

        elif isinstance(event, IterationCompleted):
            message_id = _assistant_message_id(event.run_id, event.iteration)
            await _append_message_in_short_transaction(
                session_factory=session_factory,
                session_id=session_id,
                message_id=message_id,
                message=event.message,
            )
            if round_trip_message_ids is not None:
                round_trip_message_ids.add(message_id)
            tool_call_order = []
            tool_results = {}

        elif isinstance(event, ToolStarted):
            tool_call_order.append(event.tool_call_id)

        elif isinstance(event, ToolFinished):
            tool_results[event.tool_call_id] = event.result
            if tool_call_order and set(tool_call_order) <= set(tool_results):
                message = ModelMessage(
                    role="tool",
                    content=tuple(
                        ToolResultBlock(tool_call_id=call_id, content=tool_results[call_id])
                        for call_id in tool_call_order
                    ),
                )
                message_id = tool_message_id(event.run_id, event.iteration)
                await _append_message_in_short_transaction(
                    session_factory=session_factory,
                    session_id=session_id,
                    message_id=message_id,
                    message=message,
                )
                if round_trip_message_ids is not None:
                    round_trip_message_ids.add(message_id)
                tool_call_order = []
                tool_results = {}

        yield event
