"""Alembic migration environment for the app and obs schemas."""

from __future__ import annotations

import os
from typing import Any

from alembic import context
from chat_agents import db  # noqa: F401  (registers app/obs models onto Base.metadata)
from chat_agents.database import MANAGED_SCHEMAS, Base
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

config = context.config

target_metadata = Base.metadata
_DEFAULT_DATABASE_URL = "postgresql+psycopg://root:Agent%40Dev_1@127.0.0.1:5432/chat_agents"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)


def include_name(name: str | None, type_: Any, parent_names: Any) -> bool:
    if type_ == "schema":
        return name is None or name in MANAGED_SCHEMAS
    if type_ == "table":
        return parent_names.get("schema_name") in MANAGED_SCHEMAS
    return True


def configure_context(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        configure_context(connectable)
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    engine = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        configure_context(connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
