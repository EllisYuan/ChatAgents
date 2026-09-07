"""标题事件的业务持久化边界。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from chat_agents.agent.events import RunCompleted, TitleGenerated
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.conversation.streaming import persist
from chat_agents.llm.message import ModelMessage, TextBlock

from ..db_helpers import migrated_engine, session_factory_for


async def _events() -> AsyncIterator[TitleGenerated | RunCompleted]:
    yield TitleGenerated(run_id=str(uuid4()), session_id=uuid4(), title="生成的标题")


def test_persist_writes_title_but_not_an_auxiliary_message() -> None:
    session_id = uuid4()

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_persist") as engine:
            factory = session_factory_for(engine)
            async with factory() as session, session.begin():
                repository = ConversationRepository(session)
                await repository.upsert_session(session_id)
                await repository.insert_message(
                    message_id=uuid4(),
                    session_id=session_id,
                    seq=0,
                    role="user",
                    content=[{"type": "text", "text": "你好"}],
                    round_trip_payload=None,
                )

            async def source() -> AsyncIterator[TitleGenerated | RunCompleted]:
                yield TitleGenerated(run_id=str(uuid4()), session_id=session_id, title="生成的标题")
                yield RunCompleted(
                    run_id=str(uuid4()),
                    iteration=1,
                    message=ModelMessage(role="assistant", content=(TextBlock(text="答复"),)),
                )

            forwarded = [
                event
                async for event in persist(source(), session_id=session_id, session_factory=factory)
            ]
            assert len(forwarded) == 2

            async with factory() as session:
                session_row = await ConversationRepository(session).get_session(session_id)
                assert session_row is not None
                assert session_row.title == "生成的标题"
                rows = await ConversationRepository(session).list_messages(session_id)
                assert [row.role for row in rows] == ["user"]

    asyncio.run(scenario())
