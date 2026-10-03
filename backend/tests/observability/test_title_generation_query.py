"""会话标题观测的 HTTP 行为、历史兼容与独立写入。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from chat_agents import main as main_module
from chat_agents.database import get_db
from chat_agents.db.app import Message, Session
from chat_agents.db.obs import Run, Span
from chat_agents.observability.writer import RunWriter
from sqlalchemy import select

from ..db_helpers import migrated_engine, session_factory_for
from .test_router import _override_db


@pytest.mark.db
def test_title_observation_reads_historical_and_session_spans_without_changing_runs() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_observation") as engine:
            factory = session_factory_for(engine)
            session_id, empty_id, other_id = uuid4(), uuid4(), uuid4()
            trigger_id, run_id, historic_id, direct_id = (uuid4() for _ in range(4))
            now = datetime.now(UTC)
            async with factory() as session, session.begin():
                session.add_all(
                    [
                        Session(id=session_id, title="人工标题"),
                        Session(id=empty_id),
                        Session(id=other_id),
                    ]
                )
                await session.flush()
                session.add(
                    Message(
                        id=trigger_id,
                        session_id=session_id,
                        seq=0,
                        role="user",
                        content=[{"type": "text", "text": "你好"}],
                    )
                )
                await session.flush()
                session.add(
                    Run(
                        id=run_id,
                        session_id=session_id,
                        trigger_message_id=trigger_id,
                        status="completed",
                        started_at=now,
                        ended_at=now + timedelta(seconds=7),
                    )
                )
                await session.flush()
                session.add_all(
                    [
                        Span(
                            id=historic_id,
                            run_id=run_id,
                            name="title_generation",
                            kind="llm",
                            status="error",
                            role="auxiliary",
                            model="real-aux",
                            usage_status="unavailable",
                            attributes={"key_source": "server_default", "api_key": "never-expose"},
                            started_at=now,
                            ended_at=now + timedelta(seconds=2),
                        ),
                        # 会话级归属的独立跨度：不进任何运行树或运行统计（ADR-0035）。
                        Span(
                            id=direct_id,
                            session_id=session_id,
                            name="title_generation",
                            kind="llm",
                            status="ok",
                            role="auxiliary",
                            model="later-model",
                            usage_status="complete",
                            input_tokens=5,
                            output_tokens=2,
                            attributes={
                                "effort": "low",
                                "key_source": "user_provided",
                                "application_result": "manual_not_applied",
                            },
                            started_at=now + timedelta(seconds=8),
                            ended_at=now + timedelta(seconds=9),
                        ),
                        Span(
                            id=uuid4(),
                            session_id=other_id,
                            name="title_generation",
                            kind="llm",
                            role="auxiliary",
                            model="other",
                            started_at=now,
                        ),
                        Span(
                            id=uuid4(),
                            run_id=run_id,
                            name="other_auxiliary",
                            kind="llm",
                            role="auxiliary",
                            started_at=now,
                        ),
                    ]
                )
            main_module.app.dependency_overrides[get_db] = _override_db(factory)
            try:
                transport = httpx.ASGITransport(app=main_module.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get(f"/api/sessions/{session_id}/title-generation")
                    empty = await client.get(f"/api/sessions/{empty_id}/title-generation")
                    repeated = await client.get(f"/api/sessions/{session_id}/title-generation")
                    run = await client.get(f"/api/runs/{run_id}")
                    runs = await client.get(f"/api/sessions/{session_id}/runs")
            finally:
                main_module.app.dependency_overrides.pop(get_db, None)
            assert response.status_code == 200
            assert repeated.json() == response.json()
            assert response.json()["session_id"] == str(session_id)
            spans = response.json()["spans"]
            assert [item["id"] for item in spans] == [str(direct_id), str(historic_id)]
            assert spans[0]["model"] == "later-model"
            assert spans[0]["effort"] == "low"
            assert spans[0]["input_tokens"] == 5
            assert spans[0]["duration_ms"] == 1000
            assert spans[0]["application_result"] == "manual_not_applied"
            assert spans[0]["status"] == "ok"
            assert spans[1]["model"] == "real-aux"
            assert spans[1]["status"] == "error"
            assert spans[1]["usage_status"] == "unavailable"
            assert spans[1]["input_tokens"] is None
            assert spans[1]["effort"] is None
            assert spans[1]["application_result"] is None
            assert spans[1]["failure_reason"] is None
            assert "key_source" not in response.text and "api_key" not in response.text
            assert "attributes" not in response.text and "人工标题" not in response.text
            assert empty.json() == {"session_id": str(empty_id), "spans": []}
            assert run.status_code == 200
            assert run.json()["ended_at"] == (now + timedelta(seconds=7)).isoformat().replace(
                "+00:00", "Z"
            )
            assert str(historic_id) in [span["id"] for span in run.json()["spans"]]
            assert str(direct_id) not in [span["id"] for span in run.json()["spans"]]
            # 历史标题跨度是 error/unavailable，不进完整用量汇总。
            assert run.json()["usage"] == []
            assert run.json()["status"] == "completed"
            # 详情不泄漏历史跨度属性里的 key_source 或 api_key。
            assert "key_source" not in run.text and "api_key" not in run.text
            assert runs.json() == [
                {"id": str(run_id), "trigger_message_id": str(trigger_id), "last_message_seq": None}
            ]
            async with factory() as session:
                stored = (
                    await session.execute(select(Span).where(Span.id == historic_id))
                ).scalar_one()
                assert stored.run_id == run_id and stored.session_id is None
                assert stored.ended_at == now + timedelta(seconds=2)

    asyncio.run(scenario())


@pytest.mark.db
def test_session_span_writer_uses_independent_transaction_and_swallows_failure() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_writer") as engine:
            factory = session_factory_for(engine)
            writer = RunWriter(session_factory=factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                session.add(Session(id=session_id))
            successful_id = uuid4()
            await writer.open_span(
                span_id=successful_id,
                run_id=None,
                session_id=session_id,
                parent_span_id=None,
                name="title_generation",
                kind="llm",
                role="auxiliary",
                model="real-model",
            )
            await writer.close_span(
                span_id=successful_id,
                run_id=None,
                status="ok",
                usage_status="complete",
                input_tokens=4,
                output_tokens=2,
                reasoning_tokens=None,
            )
            await writer.open_span(
                span_id=uuid4(),
                run_id=None,
                session_id=uuid4(),
                parent_span_id=None,
                name="title_generation",
                kind="llm",
                role="auxiliary",
                model="real-model",
            )
            async with factory() as session:
                spans = (await session.execute(select(Span))).scalars().all()
                assert len(spans) == 1
                assert spans[0].id == successful_id
                assert spans[0].run_id is None and spans[0].session_id == session_id
                assert spans[0].input_tokens == 4 and spans[0].ended_at is not None

    asyncio.run(scenario())
