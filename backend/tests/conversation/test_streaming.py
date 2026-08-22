"""``persist``：增量落库 + 失败传播（issue #52）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from uuid import uuid4

import pytest
from chat_agents.agent.events import (
    IterationCompleted,
    IterationStarted,
    RunCompleted,
    RunEvent,
    RunFailed,
    ToolFinished,
    ToolStarted,
    assistant_message_id,
    tool_message_id,
)
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.conversation.streaming import persist
from chat_agents.llm.events import Usage
from chat_agents.llm.message import ModelMessage, TextBlock, ToolCallBlock

from ..db_helpers import migrated_engine, session_factory_for

RUN_ID = str(uuid4())
_USAGE = Usage(state="complete", input_tokens=1, output_tokens=1, reasoning_tokens=None)


async def _events(items: Iterable[RunEvent]) -> AsyncIterator[RunEvent]:
    for item in items:
        yield item


@pytest.mark.db
def test_persist_writes_each_iteration_and_grouped_tool_message() -> None:
    session_id = uuid4()

    async def scenario() -> None:
        async with migrated_engine("chat_agents_persist") as engine:
            factory = session_factory_for(engine)
            async with factory() as session, session.begin():
                await ConversationRepository(session).upsert_session(session_id)
                await ConversationRepository(session).insert_message(
                    message_id=uuid4(),
                    session_id=session_id,
                    seq=0,
                    role="user",
                    content=[{"type": "text", "text": "hi"}],
                    round_trip_payload=None,
                )

            call_message = ModelMessage(
                role="assistant",
                content=(ToolCallBlock(id="call-1", name="search", arguments={"q": "x"}),),
            )
            final_message = ModelMessage(role="assistant", content=(TextBlock(text="done"),))

            source = _events(
                [
                    IterationStarted(run_id=RUN_ID, iteration=1),
                    IterationCompleted(
                        run_id=RUN_ID,
                        iteration=1,
                        message=call_message,
                        usage=_USAGE,
                        stop_reason="tool_use",
                    ),
                    ToolStarted(
                        run_id=RUN_ID,
                        iteration=1,
                        tool_call_id="call-1",
                        name="search",
                        arguments={"q": "x"},
                    ),
                    ToolFinished(
                        run_id=RUN_ID,
                        iteration=1,
                        tool_call_id="call-1",
                        name="search",
                        result="result text",
                        structured=None,
                    ),
                    IterationStarted(run_id=RUN_ID, iteration=2),
                    IterationCompleted(
                        run_id=RUN_ID,
                        iteration=2,
                        message=final_message,
                        usage=_USAGE,
                        stop_reason="stop",
                    ),
                    RunCompleted(run_id=RUN_ID, iteration=2, message=final_message),
                ]
            )

            forwarded = [
                event
                async for event in persist(source, session_id=session_id, session_factory=factory)
            ]
            assert len(forwarded) == 7  # 透传数量不变

            async with factory() as session:
                repository = ConversationRepository(session)
                rows = await repository.list_messages(session_id)
                by_id = {row.id: row for row in rows}

            assistant_1 = assistant_message_id(RUN_ID, 1)
            tool_1 = tool_message_id(RUN_ID, 1)
            assistant_2 = assistant_message_id(RUN_ID, 2)
            assert by_id[assistant_1].role == "assistant"
            assert by_id[assistant_1].content[0]["type"] == "tool_call"
            assert by_id[tool_1].role == "tool"
            assert by_id[tool_1].content[0]["tool_call_id"] == "call-1"
            assert by_id[tool_1].content[0]["content"] == "result text"
            assert by_id[assistant_2].role == "assistant"
            # user + assistant_1 + tool_1 + assistant_2 == 4 行
            assert len(rows) == 4

    asyncio.run(scenario())


@pytest.mark.db
def test_persist_survives_client_disconnect_leaving_written_parts_intact() -> None:
    """生成器被提前 ``aclose()`` 掐断时，已经落库的部分保持完好（就地停）。"""

    session_id = uuid4()

    async def scenario() -> None:
        async with migrated_engine("chat_agents_persist_cancel") as engine:
            factory = session_factory_for(engine)
            async with factory() as session, session.begin():
                await ConversationRepository(session).upsert_session(session_id)

            final_message = ModelMessage(role="assistant", content=(TextBlock(text="partial"),))
            source = _events(
                [
                    IterationStarted(run_id=RUN_ID, iteration=1),
                    IterationCompleted(
                        run_id=RUN_ID,
                        iteration=1,
                        message=final_message,
                        usage=_USAGE,
                        stop_reason="stop",
                    ),
                    RunFailed(run_id=RUN_ID, iteration=2, reason="never reached"),
                ]
            )

            wrapped = persist(source, session_id=session_id, session_factory=factory)
            first = await anext(wrapped)
            second = await anext(wrapped)
            assert type(first).__name__ == "IterationStarted"
            assert type(second).__name__ == "IterationCompleted"
            await wrapped.aclose()

            async with factory() as session:
                rows = await ConversationRepository(session).list_messages(session_id)
                assert len(rows) == 1
                assert rows[0].role == "assistant"

    asyncio.run(scenario())
