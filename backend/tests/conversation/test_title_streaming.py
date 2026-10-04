"""标题生成脱离主运行后的会话级业务边界（issue #93，ADR-0036）。

主运行不再持有标题生命周期：``persist`` 只落助手消息，标题事实只经由会话级的
独立调用产生。本模块用真实 PostgreSQL 覆盖会话命名空间里那两条短事务入口
（认领 / 终态）与「主运行统计不含标题」这条分离约束——HTTP 契约在
``tests/test_main.py`` 里验证。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from chat_agents.agent.events import IterationCompleted, RunCompleted
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.conversation.service import (
    ConversationService,
    TitleClaim,
    TitleOutcome,
)
from chat_agents.conversation.streaming import persist
from chat_agents.db.app import Session
from chat_agents.db.obs import Span
from chat_agents.llm.events import Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.observability.repository import ObservabilityRepository
from chat_agents.observability.writer import RunWriter
from sqlalchemy import select

from ..db_helpers import migrated_engine, session_factory_for

_USAGE = Usage(state="complete", input_tokens=1, output_tokens=1, reasoning_tokens=None)


def _service() -> ConversationService:
    """短事务入口不碰 ``self.repository``——照 ``main.py`` 的写法造占位实例。"""

    return object.__new__(ConversationService)


async def _first_message(factory: object, *, text: str = "首条用户消息") -> UUID:
    """建一个随首条用户消息诞生的会话，返回其标识（fallback 已就地写入）。"""

    session_id = uuid4()
    async with factory() as session, session.begin():  # type: ignore[operator]
        _, candidate = await ConversationService(session).append_user_message_with_title_candidate(
            session_id=session_id, message_id=uuid4(), text=text
        )
        assert candidate
    return session_id


def test_persist_writes_the_assistant_message_and_leaves_the_title_alone() -> None:
    session_id = uuid4()

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_no_event") as engine:
            factory = session_factory_for(engine)
            async with factory() as session, session.begin():
                _, candidate = await ConversationService(
                    session
                ).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="你好"
                )
                assert candidate

            run_id = str(uuid4())
            assistant = ModelMessage(role="assistant", content=(TextBlock(text="答复"),))

            async def source() -> AsyncIterator[IterationCompleted | RunCompleted]:
                yield IterationCompleted(
                    run_id=run_id,
                    iteration=1,
                    message=assistant,
                    usage=_USAGE,
                    stop_reason="end_turn",
                )
                yield RunCompleted(run_id=run_id, iteration=1, message=assistant)

            forwarded = [
                event
                async for event in persist(source(), session_id=session_id, session_factory=factory)
            ]
            assert len(forwarded) == 2

            async with factory() as session:
                repository = ConversationRepository(session)
                session_row = await repository.get_session(session_id)
                assert session_row is not None
                # 主运行不认领、不落标题：fallback 保持原样，标题只能由独立
                # 会话调用改写（ADR-0037/0036）。
                assert session_row.title == "你好"
                assert session_row.title_generation_claimed_at is None
                assert session_row.title_generation_outcome is None
                rows = await repository.list_messages(session_id)
                assert [row.role for row in rows] == ["user", "assistant"]

    asyncio.run(scenario())


def test_claim_reads_the_first_user_message_and_only_wins_once() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_claim_once") as engine:
            factory = session_factory_for(engine)
            session_id = await _first_message(factory, text="请介绍 Python")

            first = await _service().short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert isinstance(first, TitleClaim)
            assert first.claimed is True
            assert first.source_text == "请介绍 Python"

            # 第二次调用不再认领——素材是服务端保存的那条消息，不重复消耗资格。
            second = await _service().short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert isinstance(second, TitleClaim)
            assert second.claimed is False
            assert second.status == "generating"

            assert (
                await _service().short_transaction_claim_title_generation(
                    session_factory=factory, session_id=uuid4()
                )
                is None
            )

    asyncio.run(scenario())


def test_finalize_applies_the_title_then_reports_the_recorded_outcome() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_finalize") as engine:
            factory = session_factory_for(engine)
            session_id = await _first_message(factory, text="首条消息")
            assert (
                await _service().short_transaction_claim_title_generation(
                    session_factory=factory, session_id=session_id
                )
            ).claimed

            outcome = await _service().short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title="模型标题"
            )
            assert isinstance(outcome, TitleOutcome)
            assert outcome.status == "applied"
            assert outcome.title == "模型标题"

            # 重复终态以已记录的事实为准，不覆盖、不重开资格（ADR-0037）。
            repeated = await _service().short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title="另一个标题"
            )
            assert repeated is not None and repeated.status == "applied"
            assert repeated.title == "模型标题"

            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                assert row.title == "模型标题"
                assert row.title_generation_outcome == "applied"
                assert row.title_generation_eligible is False
                rows = await ConversationRepository(session).list_messages(session_id)
                # auxiliary 输出永不写消息表（ADR-0012）。
                assert [r.role for r in rows] == ["user"]

    asyncio.run(scenario())


def test_failure_keeps_fallback_and_never_reopens_generation() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_fallback") as engine:
            factory = session_factory_for(engine)
            session_id = await _first_message(factory, text="首条消息")
            assert (
                await _service().short_transaction_claim_title_generation(
                    session_factory=factory, session_id=session_id
                )
            ).claimed

            outcome = await _service().short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title=None
            )
            assert isinstance(outcome, TitleOutcome)
            assert outcome.status == "fallback"
            assert outcome.title == "首条消息"

            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                assert row.title == "首条消息"
                assert row.title_generation_outcome == "fallback"
                assert row.title_generation_eligible is False

    asyncio.run(scenario())


def test_manual_rename_blocks_claim_and_late_application_without_reopening() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_manual") as engine:
            factory = session_factory_for(engine)

            # 调用前人工改名：跳过模型，直接报告已处理。
            pre = await _first_message(factory, text="首条消息")
            async with factory() as session, session.begin():
                await ConversationService(session).rename_session(pre, "人工标题")
            claim = await _service().short_transaction_claim_title_generation(
                session_factory=factory, session_id=pre
            )
            assert claim is not None and claim.claimed is False
            assert claim.status == "processed"
            assert claim.title == "人工标题"

            # 调用期间人工改名：模型可以完成，但迟到的结果条件应用失败。
            during = await _first_message(factory, text="首条消息")
            assert (
                await _service().short_transaction_claim_title_generation(
                    session_factory=factory, session_id=during
                )
            ).claimed
            async with factory() as session, session.begin():
                await ConversationService(session).rename_session(during, "人工标题")
            outcome = await _service().short_transaction_finalize_title_generation(
                session_factory=factory, session_id=during, generated_title="迟到的模型标题"
            )
            assert isinstance(outcome, TitleOutcome)
            assert outcome.status == "manual_not_applied"
            assert outcome.title == "人工标题"

            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == during))
                assert row is not None
                assert row.title == "人工标题"
                assert row.title_generation_outcome == "manual_not_applied"
                # 人工改名关闭资格，改名后既不再认领也不重新开放（ADR-0037）。
                assert row.title_generation_eligible is False

    asyncio.run(scenario())


def test_deleted_session_never_receives_a_late_title() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_deleted") as engine:
            factory = session_factory_for(engine)
            session_id = await _first_message(factory, text="首条消息")
            assert (
                await _service().short_transaction_claim_title_generation(
                    session_factory=factory, session_id=session_id
                )
            ).claimed
            async with factory() as session, session.begin():
                await ConversationService(session).delete_session(session_id)

            outcome = await _service().short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title="迟到的模型标题"
            )
            assert isinstance(outcome, TitleOutcome)
            assert outcome.title is None

            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                assert row.deleted_at is not None
                assert row.title != "迟到的模型标题"

    asyncio.run(scenario())


def test_a_session_owned_title_span_stays_out_of_the_run_statistics() -> None:
    """标题稍后完成不改写主运行统计（issue #93 的分离约束）。"""

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_stats") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            run_id = uuid4()
            writer = RunWriter(session_factory=factory)

            async with factory() as session, session.begin():
                _, candidate = await ConversationService(
                    session
                ).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
                assert candidate
                message_id = (await ConversationRepository(session).list_messages(session_id))[0].id

            await writer.start_run(
                run_id=str(run_id),
                session_id=session_id,
                trigger_message_id=message_id,
                effort="medium",
                prompt_version_id=None,
                tool_schema_version_id=None,
            )
            main_span_id = uuid4()
            await writer.open_span(
                span_id=main_span_id,
                run_id=str(run_id),
                parent_span_id=None,
                name="model_call",
                kind="llm",
                role="main",
                model="main-model",
                session_id=None,
            )
            await writer.close_span(
                span_id=main_span_id,
                run_id=str(run_id),
                status="ok",
                usage_status="complete",
                input_tokens=10,
                output_tokens=5,
                reasoning_tokens=None,
            )
            await writer.finish_run(run_id=str(run_id), status="completed")

            # 主运行结束后标题才完成——它独立归属会话，不挂在任何运行下。
            title_span_id = uuid4()
            await writer.open_span(
                span_id=title_span_id,
                run_id=None,
                session_id=session_id,
                parent_span_id=None,
                name="title_generation",
                kind="llm",
                role="auxiliary",
                model="aux-model",
                attributes={"effort": "low"},
            )
            await writer.close_span(
                span_id=title_span_id,
                run_id=None,
                status="ok",
                usage_status="complete",
                input_tokens=100,
                output_tokens=50,
                reasoning_tokens=None,
                attributes={"effort": "low", "application_result": "applied"},
            )

            async with factory() as session:
                detail = await ObservabilityRepository(session).get_run_detail(run_id)
                assert detail is not None
                assert detail.ended_at is not None
                # 运行统计只反映主运行：标题的 100/50 一个 token 都不混进来。
                assert [aggregate.model for aggregate in detail.usage] == ["main-model"]
                assert [span.name for span in detail.spans] == ["model_call"]
                title_span = (
                    await session.execute(select(Span).where(Span.name == "title_generation"))
                ).scalar_one()
                assert title_span.session_id == session_id
                assert title_span.run_id is None
                assert title_span.parent_span_id is None

    asyncio.run(scenario())
