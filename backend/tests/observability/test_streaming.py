"""``observe``：独立事务、增量落跨度、断连收尾（issue #52）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from uuid import UUID, uuid4

import pytest
from chat_agents.agent.events import (
    IterationCompleted,
    IterationStarted,
    RunCompleted,
    RunEvent,
    RunFailed,
    llm_span_id,
)
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.db.obs import Run, Span
from chat_agents.llm.events import Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.observability.streaming import observe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db_helpers import migrated_engine, session_factory_for

_USAGE = Usage(state="complete", input_tokens=3, output_tokens=4, reasoning_tokens=None)


async def _events(items: Iterable[RunEvent]) -> AsyncIterator[RunEvent]:
    for item in items:
        yield item


async def _seed_session_and_trigger(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    session_id = uuid4()
    trigger_id = uuid4()
    async with factory() as session, session.begin():
        repo = ConversationRepository(session)
        await repo.upsert_session(session_id)
        await repo.insert_message(
            message_id=trigger_id,
            session_id=session_id,
            seq=0,
            role="user",
            content=[{"type": "text", "text": "hi"}],
            round_trip_payload=None,
        )
    return session_id, trigger_id


@pytest.mark.db
def test_observe_writes_run_and_span_incrementally_on_completion() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_observe") as engine:
            factory = session_factory_for(engine)
            session_id, trigger_id = await _seed_session_and_trigger(factory)
            run_id = str(uuid4())
            message = ModelMessage(role="assistant", content=(TextBlock(text="ok"),))

            source = _events(
                [
                    IterationStarted(run_id=run_id, iteration=1),
                    IterationCompleted(
                        run_id=run_id,
                        iteration=1,
                        message=message,
                        usage=_USAGE,
                        stop_reason="stop",
                    ),
                    RunCompleted(run_id=run_id, iteration=1, message=message),
                ]
            )

            forwarded = [
                event
                async for event in observe(
                    source,
                    session_id=session_id,
                    trigger_message_id=trigger_id,
                    effort="medium",
                    model="gpt",
                    session_factory=factory,
                )
            ]
            assert len(forwarded) == 3

            async with factory() as session:
                run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
                assert run.status == "completed"
                assert run.session_id == session_id
                assert run.trigger_message_id == trigger_id

                span = (
                    await session.execute(select(Span).where(Span.id == llm_span_id(run_id, 1)))
                ).scalar_one()
                assert span.status == "ok"
                assert span.role == "main"
                assert span.model == "gpt"
                assert span.input_tokens == 3
                assert span.output_tokens == 4
                assert span.usage_status == "complete"
                assert span.ended_at is not None

    asyncio.run(scenario())


@pytest.mark.db
def test_observe_marks_aborted_and_partial_on_client_disconnect() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_observe_cancel") as engine:
            factory = session_factory_for(engine)
            session_id, trigger_id = await _seed_session_and_trigger(factory)
            run_id = str(uuid4())

            source = _events(
                [
                    IterationStarted(run_id=run_id, iteration=1),
                    RunFailed(run_id=run_id, iteration=99, reason="never reached"),
                ]
            )

            wrapped = observe(
                source,
                session_id=session_id,
                trigger_message_id=trigger_id,
                effort="medium",
                model="gpt",
                session_factory=factory,
            )
            first = await anext(wrapped)
            assert type(first).__name__ == "IterationStarted"
            await wrapped.aclose()

            async with factory() as session:
                run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
                assert run.status == "aborted"

                span = (
                    await session.execute(select(Span).where(Span.id == llm_span_id(run_id, 1)))
                ).scalar_one()
                assert span.status == "error"
                assert span.usage_status == "partial"
                assert span.ended_at is not None

    asyncio.run(scenario())


@pytest.mark.db
def test_observe_marks_failed_not_aborted_when_upstream_raises() -> None:
    """上游（比如 persist）真的抛异常时记 failed，不能和断连一起混进 aborted。"""

    async def scenario() -> None:
        async with migrated_engine("chat_agents_observe_upstream_error") as engine:
            factory = session_factory_for(engine)
            session_id, trigger_id = await _seed_session_and_trigger(factory)
            run_id = str(uuid4())

            async def failing() -> AsyncIterator[RunEvent]:
                yield IterationStarted(run_id=run_id, iteration=1)
                raise RuntimeError("db write failed")

            wrapped = observe(
                failing(),
                session_id=session_id,
                trigger_message_id=trigger_id,
                effort="medium",
                model="gpt",
                session_factory=factory,
            )
            with pytest.raises(RuntimeError, match="db write failed"):
                async for _ in wrapped:
                    pass

            async with factory() as session:
                run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
                assert run.status == "failed"

    asyncio.run(scenario())


@pytest.mark.db
def test_observe_write_failure_does_not_propagate_to_the_stream() -> None:
    """独立事务，失败只记日志——``observe`` 遇到写入异常不得向上抛。"""

    async def scenario() -> None:
        async with migrated_engine("chat_agents_observe_swallow") as engine:
            factory = session_factory_for(engine)
            # 不建会话/触发消息：``obs.run`` 的外键校验会让 start_run 失败，
            # 但 observe 必须照常透传事件，不得因此中断流。
            run_id = str(uuid4())
            message = ModelMessage(role="assistant", content=(TextBlock(text="ok"),))
            source = _events(
                [
                    IterationStarted(run_id=run_id, iteration=1),
                    IterationCompleted(
                        run_id=run_id,
                        iteration=1,
                        message=message,
                        usage=_USAGE,
                        stop_reason="stop",
                    ),
                    RunCompleted(run_id=run_id, iteration=1, message=message),
                ]
            )
            forwarded = [
                event
                async for event in observe(
                    source,
                    session_id=uuid4(),
                    trigger_message_id=uuid4(),
                    effort="medium",
                    model="gpt",
                    session_factory=factory,
                )
            ]
            assert len(forwarded) == 3

    asyncio.run(scenario())
