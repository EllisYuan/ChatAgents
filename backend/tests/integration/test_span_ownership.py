"""真实 PostgreSQL 迁移链上的跨度归属约束。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from chat_agents.db.app import Message, Session
from chat_agents.db.obs import Run
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from ..db_helpers import migrated_engine, session_factory_for


@pytest.mark.db
def test_span_has_one_owner_and_session_spans_are_roots() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_span_owner") as engine:
            factory = session_factory_for(engine)
            session_id, message_id, run_id = uuid4(), uuid4(), uuid4()
            async with factory() as session, session.begin():
                session.add(Session(id=session_id))
                await session.flush()
                session.add(
                    Message(
                        id=message_id,
                        session_id=session_id,
                        seq=0,
                        role="user",
                        content=[{"type": "text", "text": "hi"}],
                    )
                )
                await session.flush()
                session.add(Run(id=run_id, session_id=session_id, trigger_message_id=message_id))

            async with engine.connect() as connection:
                columns = await connection.run_sync(
                    lambda sync: inspect(sync).get_columns("span", schema="obs")
                )
                constraints = await connection.run_sync(
                    lambda sync: inspect(sync).get_check_constraints("span", schema="obs")
                )
                foreign_keys = await connection.run_sync(
                    lambda sync: inspect(sync).get_foreign_keys("span", schema="obs")
                )
                indexes = await connection.run_sync(
                    lambda sync: inspect(sync).get_indexes("span", schema="obs")
                )
                assert {column["name"]: column["nullable"] for column in columns}["run_id"] is True
                assert {column["name"]: column["nullable"] for column in columns}[
                    "session_id"
                ] is True
                assert {item["name"] for item in constraints} >= {
                    "ck_obs_span_one_owner",
                    "ck_obs_span_session_root",
                }
                assert any(
                    item["constrained_columns"] == ["session_id"]
                    and item["referred_schema"] == "app"
                    for item in foreign_keys
                )
                assert any(item["column_names"] == ["session_id"] for item in indexes)

            async def insert(
                *, owner_run: bool = False, owner_session: bool = False, parent: bool = False
            ) -> None:
                async with factory() as session, session.begin():
                    await session.execute(
                        text(
                            "INSERT INTO obs.span (id, run_id, session_id, parent_span_id, name, kind) VALUES (:id, :run_id, :session_id, :parent, 'title_generation', 'llm')"
                        ),
                        {
                            "id": uuid4(),
                            "run_id": run_id if owner_run else None,
                            "session_id": session_id if owner_session else None,
                            "parent": uuid4() if parent else None,
                        },
                    )

            await insert(owner_run=True)
            await insert(owner_session=True)
            for owners in (
                {},
                {"owner_run": True, "owner_session": True},
                {"owner_session": True, "parent": True},
            ):
                with pytest.raises(IntegrityError):
                    await insert(**owners)

    asyncio.run(scenario())
