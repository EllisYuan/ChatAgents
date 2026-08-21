import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

_DATABASE_URL = "postgresql+psycopg://root:Agent%40Dev_1@127.0.0.1:5432/chat_agents"
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
                "Start it with `docker compose up -d postgresql`."
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

            app_tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'app'"
                    )
                ).scalars()
            )
            obs_tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'obs'"
                    )
                ).scalars()
            )
            message_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'app' AND table_name = 'message'"
                    )
                ).scalars()
            )
            span_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'obs' AND table_name = 'span'"
                    )
                ).scalars()
            )
            session_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'app' AND table_name = 'session'"
                    )
                ).scalars()
            )
            all_columns = connection.execute(
                text(
                    "SELECT table_schema, table_name, column_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema IN ('app', 'obs')"
                )
            ).all()
            fk_directions = connection.execute(
                text(
                    """
                    SELECT tc.table_schema AS fk_schema, ccu.table_schema AS ref_schema
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage ccu
                        ON tc.constraint_name = ccu.constraint_name
                        AND tc.table_schema = ccu.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                        AND tc.table_schema IN ('app', 'obs')
                    """
                )
            ).all()

        script = ScriptDirectory.from_config(config)

        assert schemas == {"app", "obs"}
        assert revision == script.get_current_head()

        assert app_tables == {
            "session",
            "message",
            "prompt_versions",
            "tool_schema_versions",
            "discovered_model",
            "discovered_model_refresh",
        }
        assert obs_tables == {"run", "span"}

        assert "run_id" not in message_columns

        assert {
            "role",
            "model",
            "input_tokens",
            "output_tokens",
            "usage_status",
            "reasoning_tokens",
        } <= span_columns

        assert "pruned_run_count" in session_columns

        cost_like = {
            (schema_name, table_name, column_name)
            for schema_name, table_name, column_name in all_columns
            if "cost" in column_name.lower()
        }
        assert cost_like == set()

        for fk_schema, ref_schema in fk_directions:
            assert fk_schema == "obs" or ref_schema == "app"
            assert not (fk_schema == "app" and ref_schema == "obs")
    finally:
        engine.dispose()
        _drop_database(admin_url, database_name)
