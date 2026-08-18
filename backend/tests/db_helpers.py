"""为需要真库的测试提供一次性 Postgres 数据库（同 ``tests/integration`` 的手法）。"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/chat_agents"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _database_url() -> URL:
    return make_url(os.environ.get("DATABASE_URL", _DATABASE_URL))


def _alembic_config() -> Config:
    return Config(str(_BACKEND_ROOT / "alembic.ini"))


@contextmanager
def _temp_database(prefix: str) -> Iterator[URL]:
    base_url = _database_url()
    admin_url = base_url.set(database="postgres")
    database_name = f"{prefix}_{uuid.uuid4().hex}"
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
        sync_url = base_url.set(database=database_name)
        config = _alembic_config()
        sync_engine = create_engine(sync_url)
        try:
            with sync_engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        finally:
            sync_engine.dispose()
        yield sync_url
    finally:
        admin_engine.dispose()
        _drop_database(admin_url, database_name)


def _drop_database(admin_url: URL, database_name: str) -> None:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        engine.dispose()


@asynccontextmanager
async def migrated_engine(prefix: str = "chat_agents_test") -> AsyncIterator[AsyncEngine]:
    """起一个跑完全部迁移的一次性数据库，产出可用的异步引擎，退出时清理。"""

    with _temp_database(prefix) as sync_url:
        async_url = sync_url.set(drivername="postgresql+psycopg")
        engine = create_async_engine(async_url)
        try:
            yield engine
        finally:
            await engine.dispose()


def session_factory_for(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
