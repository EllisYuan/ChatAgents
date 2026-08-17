import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/chat_agents"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> URL:
    return make_url(os.environ.get("DATABASE_URL", _DATABASE_URL))


def _alembic_config() -> Config:
    return Config(str(_BACKEND_ROOT / "alembic.ini"))


def _database_name() -> str:
    return f"chat_agents_test_{uuid.uuid4().hex}"


def _drop_database(admin_url: URL, database_name: str) -> None:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        engine.dispose()


@pytest.mark.db
def test_upgrade_head_creates_application_and_observability_schemas() -> None:
    base_url = _database_url()
    admin_url = base_url.set(database="postgres")
    database_name = _database_name()
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        try:
            with admin_engine.connect():
                pass
        except OperationalError:
            pytest.fail(
                "PostgreSQL is required for integration tests. "
                "Start it with `docker compose up -d postgres`."
            )

        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        admin_engine.dispose()

    engine = create_engine(base_url.set(database=database_name))
    try:
        config = _alembic_config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        with engine.connect() as connection:
            schemas = set(
                connection.execute(
                    text(
                        "SELECT schema_name FROM information_schema.schemata "
                        "WHERE schema_name IN ('app', 'obs')"
                    )
                ).scalars()
            )
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()

        assert schemas == {"app", "obs"}
        assert revision == "0001_schemas"
    finally:
        engine.dispose()
        _drop_database(admin_url, database_name)
