"""观测查询端点的契约测试（issue #58）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from chat_agents import main as main_module
from chat_agents.database import get_db
from chat_agents.db.app import Message as MessageRow
from chat_agents.db.app import Session as SessionRow
from chat_agents.db.obs import Run, Span
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db_helpers import migrated_engine, session_factory_for


def _override_db(factory: async_sessionmaker[AsyncSession]):
    async def dependency() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return dependency


async def _seed_observation(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[Any, Any, Any, Any]:
    session_id = uuid4()
    trigger_id = uuid4()
    run_id = uuid4()
    root_id = uuid4()
    child_id = uuid4()
    tool_id = uuid4()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(SessionRow(id=session_id))
        session.add(
            MessageRow(
                id=trigger_id,
                session_id=session_id,
                seq=0,
                role="user",
                content=[{"type": "text", "text": "hi"}],
                round_trip_payload=None,
            )
        )
        session.add(
            Run(
                id=run_id,
                session_id=session_id,
                trigger_message_id=trigger_id,
                last_message_seq=2,
                status="completed",
                effort="high",
                prompt_version_id="prompt@1",
                tool_schema_version_id="tools@1",
                retention_window=2,
                attributes={"pruned_runs": ["old-run"]},
                started_at=now,
                ended_at=now + timedelta(seconds=4),
            )
        )
        session.add(
            Span(
                id=root_id,
                run_id=run_id,
                parent_span_id=None,
                name="model_call",
                kind="llm",
                status="ok",
                role="main",
                model="gpt-main",
                input_tokens=10,
                output_tokens=4,
                usage_status="complete",
                reasoning_tokens=2,
                attributes={
                    "protocol": "openai_responses",
                    "message_content": [{"type": "reasoning", "text": "先查资料"}],
                },
                started_at=now,
                ended_at=now + timedelta(seconds=2),
            )
        )
        session.add(
            Span(
                id=child_id,
                run_id=run_id,
                parent_span_id=root_id,
                name="auxiliary_call",
                kind="llm",
                status="ok",
                role="auxiliary",
                model="gpt-aux",
                input_tokens=3,
                output_tokens=1,
                usage_status="complete",
                reasoning_tokens=None,
                attributes={"protocol": "openai_chat_completions"},
                started_at=now + timedelta(seconds=1),
                ended_at=now + timedelta(seconds=3),
            )
        )
        session.add(
            Span(
                id=uuid4(),
                run_id=run_id,
                parent_span_id=None,
                name="partial_call",
                kind="llm",
                status="error",
                role="main",
                model="gpt-main",
                input_tokens=None,
                output_tokens=None,
                usage_status="partial",
                reasoning_tokens=None,
                attributes={"protocol": "openai_responses"},
                started_at=now + timedelta(seconds=3),
                ended_at=now + timedelta(seconds=4),
            )
        )
        session.add(
            Span(
                id=tool_id,
                run_id=run_id,
                parent_span_id=root_id,
                name="web_search",
                kind="tool",
                status="ok",
                role=None,
                model=None,
                input_tokens=None,
                output_tokens=None,
                usage_status=None,
                reasoning_tokens=None,
                attributes={
                    "tool_call_id": "call-1",
                    "arguments": {"query": "事实"},
                    "result": "找到了",
                    "structured": {"result_count": 1},
                },
                started_at=now + timedelta(seconds=1, milliseconds=500),
                ended_at=now + timedelta(seconds=2),
            )
        )
    return session_id, run_id, child_id, tool_id


@pytest.mark.db
def test_run_list_is_three_field_observation_skeleton() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_obs_list") as engine:
            factory = session_factory_for(engine)
            session_id, _, _, _ = await _seed_observation(factory)
            main_module.app.dependency_overrides[get_db] = _override_db(factory)
            try:
                transport = httpx.ASGITransport(app=main_module.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get(f"/api/sessions/{session_id}/runs")
            finally:
                main_module.app.dependency_overrides.pop(get_db, None)

            assert response.status_code == 200
            assert len(response.json()) == 1
            assert set(response.json()[0]) == {"id", "trigger_message_id", "last_message_seq"}

    asyncio.run(scenario())


@pytest.mark.db
def test_run_detail_returns_tree_aggregates_and_protocol_specific_fields() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_obs_detail") as engine:
            factory = session_factory_for(engine)
            _, run_id, child_id, tool_id = await _seed_observation(factory)
            main_module.app.dependency_overrides[get_db] = _override_db(factory)
            try:
                transport = httpx.ASGITransport(app=main_module.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get(f"/api/runs/{run_id}")
            finally:
                main_module.app.dependency_overrides.pop(get_db, None)

            assert response.status_code == 200
            body = response.json()
            assert body["prompt_version_id"] == "prompt@1"
            assert body["tool_schema_version_id"] == "tools@1"
            assert body["retention_window"] == 2
            assert body["effort"] == "high"
            assert body["pruned_run_count"] == 1
            assert body["usage"] == [
                {
                    "model": "gpt-aux",
                    "role": "auxiliary",
                    "input_tokens": 3,
                    "output_tokens": 1,
                    "reasoning_tokens": None,
                    "started_at": body["usage"][0]["started_at"],
                    "ended_at": body["usage"][0]["ended_at"],
                },
                {
                    "model": "gpt-main",
                    "role": "main",
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "reasoning_tokens": 2,
                    "started_at": body["usage"][1]["started_at"],
                    "ended_at": body["usage"][1]["ended_at"],
                },
            ]
            roots = body["spans"]
            assert len(roots) == 2
            main_span = next(span for span in roots if span["model"] == "gpt-main")
            assert main_span["display_summary"] == {
                "text": "先查资料",
                "status": "available",
            }
            child = main_span["children"][0]
            assert child["id"] == str(child_id)
            assert "reasoning_tokens" not in child
            assert "input_tokens" in child and child["input_tokens"] == 3
            assert "output_tokens" in child and child["output_tokens"] == 1
            assert all(
                item["model"] != "gpt-main" or item["input_tokens"] != 0 for item in body["usage"]
            )
            partial_span = next(span for span in roots if span["name"] == "partial_call")
            assert partial_span["usage_status"] == "partial"

            tool_span = next(span for span in main_span["children"] if span["kind"] == "tool")
            assert tool_span["id"] == str(tool_id)
            assert tool_span["status"] == "ok"
            assert tool_span["arguments"] == {"query": "事实"}
            assert tool_span["tool_result"] == {
                "result": "找到了",
                "structured": {"result_count": 1},
            }
            assert "arguments" not in main_span
            assert "tool_result" not in main_span

    asyncio.run(scenario())
