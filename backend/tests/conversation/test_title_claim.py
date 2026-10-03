"""真实 PostgreSQL 连接上一次性的标题认领、终态与人工改名保护（issue #91/#93）。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from chat_agents.conversation.repository import ConversationRepository
from chat_agents.conversation.service import ConversationService
from chat_agents.db.app import Session
from sqlalchemy import select, text

from ..db_helpers import migrated_engine, session_factory_for


def _ephemeral() -> ConversationService:
    """短事务方法不碰实例状态，用占位实例即可（同 main.py 的 round_trip 写法）。"""

    return object.__new__(ConversationService)


def test_concurrent_claims_use_distinct_connections_and_only_one_generates() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_claim") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                service = ConversationService(session)
                _, candidate = await service.append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
                assert candidate

            ready = asyncio.Event()
            release = asyncio.Event()
            model_calls = 0
            pids: set[int] = set()

            async def compete() -> bool:
                nonlocal model_calls
                async with factory() as session, session.begin():
                    connection = await session.connection()
                    pid = await connection.scalar(text("SELECT pg_backend_pid()"))
                    assert isinstance(pid, int)
                    pids.add(pid)
                    ready.set()
                claim = await _ephemeral().short_transaction_claim_title_generation(
                    session_factory=factory, session_id=session_id
                )
                assert claim is not None
                if not claim.claimed:
                    # 输家不得看到陈旧状态，必须能区分已在生成。
                    assert claim.status in {"generating", "processed"}
                    return False
                model_calls += 1
                assert claim.source_text == "首条消息"
                await release.wait()
                outcome = await _ephemeral().short_transaction_finalize_title_generation(
                    session_factory=factory, session_id=session_id, generated_title="生成标题"
                )
                assert outcome is not None
                assert outcome.status == "applied"
                assert outcome.title == "生成标题"
                return True

            first = asyncio.create_task(compete())
            await ready.wait()
            second = asyncio.create_task(compete())
            try:
                second_result = await second
            finally:
                release.set()
            first_result = await first
            assert sorted([first_result, second_result]) == [False, True]
            assert len(pids) == 2
            assert model_calls == 1
            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                assert row.title == "生成标题"
                assert row.title_generation_claimed_at is not None
                assert row.title_generation_outcome == "applied"

    asyncio.run(scenario())


def test_repeated_claim_reports_state_without_calling_the_model_again() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_repeat") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                service = ConversationService(session)
                await service.append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="第一条"
                )

            service = _ephemeral()
            first = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert first is not None and first.claimed
            # 认领后、未终态：重复调用报告接续生成，不再调用模型。
            during = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert during is not None and not during.claimed
            assert during.status == "generating"
            outcome = await service.short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title="模型标题"
            )
            assert outcome is not None and outcome.status == "applied"
            after = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert after is not None and not after.claimed
            assert after.status == "applied"
            assert after.title == "模型标题"

    asyncio.run(scenario())


def test_failed_generation_records_fallback_terminal_and_reports_no_retry() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_fallback") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="第一条"
                )
            service = _ephemeral()
            claim = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert claim is not None and claim.claimed
            # 上游失败 / 空输出 / 超时 / 取消统一折算为 None。
            outcome = await service.short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title=None
            )
            assert outcome is not None
            assert outcome.status == "fallback"
            assert outcome.title == "第一条"
            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                assert row.title == "第一条"
                assert row.title_generation_outcome == "fallback"
                assert not row.title_generation_eligible
            again = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert again is not None and not again.claimed
            assert again.status == "fallback"

    asyncio.run(scenario())


def test_late_edit_after_claim_blocks_result_even_with_same_text() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_manual_block") as engine:
            factory = session_factory_for(engine)
            for operation in ("same", "clear_return"):
                session_id = uuid4()
                async with factory() as session, session.begin():
                    service = ConversationService(session)
                    _, candidate = await service.append_user_message_with_title_candidate(
                        session_id=session_id, message_id=uuid4(), text="第一条"
                    )
                    assert candidate
                service = _ephemeral()
                # 先认领，再人工改名——迟到的模型结果不得覆盖（ADR-0037）。
                claim = await service.short_transaction_claim_title_generation(
                    session_factory=factory, session_id=session_id
                )
                assert claim is not None and claim.claimed
                async with factory() as session, session.begin():
                    editor = ConversationService(session)
                    if operation == "same":
                        # 改成与 fallback 完全相同的文字也必须受保护。
                        await editor.rename_session(session_id, "第一条")
                    elif operation == "clear_return":
                        await editor.rename_session(session_id, None)
                        await editor.rename_session(session_id, "第一条")
                outcome = await service.short_transaction_finalize_title_generation(
                    session_factory=factory, session_id=session_id, generated_title="迟到的模型标题"
                )
                assert outcome is not None
                assert outcome.status == "manual_not_applied"
                assert outcome.title == "第一条"
                async with factory() as session:
                    row = await session.scalar(select(Session).where(Session.id == session_id))
                    assert row is not None
                    assert row.title == "第一条"
                    assert row.title_generation_outcome == "manual_not_applied"

    asyncio.run(scenario())


def test_failed_generation_returns_committed_title_after_concurrent_rename() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_fallback_race") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="第一条"
                )
            service = _ephemeral()
            claim = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert claim is not None and claim.claimed
            # 模型失败期间人工改名：fallback 终态必须报告提交后的实际标题，而非旧行。
            async with factory() as session, session.begin():
                await ConversationService(session).rename_session(session_id, "人工标题")
            outcome = await service.short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title=None
            )
            assert outcome is not None
            assert outcome.status == "fallback"
            assert outcome.title == "人工标题"
            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                assert row.title == "人工标题"
                assert row.title_generation_outcome == "fallback"
                assert row.title_manually_edited

    asyncio.run(scenario())


def test_pre_claim_manual_rename_skips_the_model_entirely() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_pre_rename") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                service = ConversationService(session)
                await service.append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="第一条"
                )
                await service.rename_session(session_id, "人工标题")
            claim = await _ephemeral().short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert claim is not None
            assert not claim.claimed
            assert claim.status == "processed"
            assert claim.title == "人工标题"
            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                # 未认领：资格随人工改名关闭，但没有生成尝试的终态。
                assert row.title_generation_claimed_at is None
                assert row.title_generation_outcome is None

    asyncio.run(scenario())


def test_deleted_session_rejects_generation_and_late_result_does_not_revive() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_deleted") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                service = ConversationService(session)
                await service.append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="第一条"
                )
            # 删除后认领：会话不存在（HTTP 404 路径）。
            async with factory() as session, session.begin():
                assert await ConversationService(session).delete_session(session_id)
            service = _ephemeral()
            gone = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert gone is None
            # 迟到的终态不得恢复已删除会话，也不得写业务标题。
            outcome = await service.short_transaction_finalize_title_generation(
                session_factory=factory, session_id=session_id, generated_title="迟到标题"
            )
            assert outcome is not None
            assert outcome.status == "processed"
            assert outcome.title is None
            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                assert row.deleted_at is not None
                assert row.title == "第一条"

    asyncio.run(scenario())


def test_two_first_messages_claim_once_and_preserve_first_fallback() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_first_messages") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()

            async def append(text_value: str) -> bool:
                async with factory() as session, session.begin():
                    _, candidate = await ConversationService(
                        session
                    ).append_user_message_with_title_candidate(
                        session_id=session_id, message_id=uuid4(), text=text_value
                    )
                    return bool(candidate)

            results = await asyncio.gather(append("第一条"), append("第二条"))
            assert results.count(True) == 1
            service = _ephemeral()
            claim = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert claim is not None and claim.claimed
            second_claim = await service.short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert second_claim is not None and not second_claim.claimed
            async with factory() as session:
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title in {"第一条", "第二条"}
                assert row.title_generation_claimed_at is not None
                messages = await ConversationRepository(session).list_messages(session_id)
                assert len(messages) == 2
                assert row.title == messages[0].content[0]["text"]

    asyncio.run(scenario())


def test_missing_source_text_does_not_consume_eligibility() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_no_source") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                repository = ConversationRepository(session)
                await repository.upsert_session(session_id, title_eligible=True)
                await repository.set_fallback_title(session_id, "回退")
            claim = await _ephemeral().short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert claim is not None
            assert not claim.claimed
            assert claim.status == "processed"
            async with factory() as session:
                row = await session.scalar(select(Session).where(Session.id == session_id))
                assert row is not None
                # 没有素材就不认领，资格保持开放，也不写终态。
                assert row.title_generation_claimed_at is None
                assert row.title_generation_outcome is None

    asyncio.run(scenario())


def test_legacy_session_cannot_be_claimed_even_without_a_title() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_legacy") as engine:
            factory = session_factory_for(engine)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await session.execute(
                    text("INSERT INTO app.session (id) VALUES (:session_id)"),
                    {"session_id": session_id},
                )
                repository = ConversationRepository(session)
                await repository.insert_message(
                    message_id=uuid4(),
                    session_id=session_id,
                    seq=0,
                    role="user",
                    content=[{"type": "text", "text": "历史消息"}],
                    round_trip_payload=None,
                )
            async with factory() as session, session.begin():
                service = ConversationService(session)
                _, claimed = await service.append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="后续消息"
                )
                assert not claimed
            claim = await _ephemeral().short_transaction_claim_title_generation(
                session_factory=factory, session_id=session_id
            )
            assert claim is not None
            assert not claim.claimed
            assert claim.status == "processed"
            async with factory() as session:
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title is None

    asyncio.run(scenario())
