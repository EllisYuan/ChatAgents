"""Shared database metadata, engine, and session lifecycles."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

APP_SCHEMA = "app"
OBSERVABILITY_SCHEMA = "obs"
MANAGED_SCHEMAS = frozenset({APP_SCHEMA, OBSERVABILITY_SCHEMA})
_DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/chat_agents"


class Base(DeclarativeBase):
    metadata = MetaData()


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


engine = create_async_engine(database_url(), pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """Request-scoped session dependency for non-streaming endpoints."""

    async with session_factory() as session:
        yield session
