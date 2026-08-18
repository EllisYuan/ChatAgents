import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.conversation.service import ConversationService
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/chat_agents"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> URL:
    return make_url(os.environ.get("DATABASE_URL", _DATABASE_URL))


def _alembic_config() -> Config:
    return Config(str(_BACKEND_ROOT / "alembic.ini"))


def _database_name() -> str:
    return f"chat_agents_conversation_{uuid.uuid4().hex}"


def _drop_database(admin_url: URL, database_name: str) -> None:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        engine.dispose()


@pytest.mark.db
def test_read_projection_repairs_dangling_tool_call_from_postgres() -> None:
    base_url = _database_url()
    admin_url = base_url.set(database="postgres")
    database_name = _database_name()
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        try:
            with admin_engine.connect():
                pass
        except Exception as exc:  # pragma: no cover - depends on local service
            raise AssertionError(
                "PostgreSQL is required for integration tests. "
                "Start it with `docker compose up -d postgres`."
            ) from exc
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        admin_engine.dispose()

    sync_url = base_url.set(database=database_name)
    async_url = sync_url.set(drivername="postgresql+psycopg")
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    try:
        config = _alembic_config()
        sync_engine = create_engine(sync_url)
        try:
            with sync_engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        finally:
            sync_engine.dispose()

        async def scenario() -> None:
            async with factory() as session, session.begin():
                repository = ConversationRepository(session)
                await repository.upsert_session(session_id)
                await repository.insert_message(
                    message_id=user_id,
                    session_id=session_id,
                    seq=0,
                    role="user",
                    content=[{"type": "text", "text": "search"}],
                    round_trip_payload=None,
                )
                await repository.insert_message(
                    message_id=assistant_id,
                    session_id=session_id,
                    seq=1,
                    role="assistant",
                    content=[
                        {
                            "type": "tool_call",
                            "id": "call-1",
                            "name": "search",
                            "arguments": {"q": "x"},
                        }
                    ],
                    round_trip_payload=None,
                )

            async with factory() as session:
                projected = await ConversationService(session).rebuild_model_input(session_id)
                assert projected[-1].role == "tool"
                result = projected[-1].content[0]
                assert result.tool_call_id == "call-1"
                assert result.is_error is True
                assert result.content == "Tool call ended before a result was recorded."

            async with factory() as session, session.begin():
                repository = ConversationRepository(session)
                assert await repository.get_message(assistant_id) is not None
                assert await repository.soft_delete_session(session_id) is True

            async with factory() as session:
                repository = ConversationRepository(session)
                assert await repository.get_session(session_id) is None
                assert await repository.list_messages(session_id) == []
                assert await repository.get_message(assistant_id) is None

        asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())
        _drop_database(admin_url, database_name)
