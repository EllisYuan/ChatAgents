"""Base.metadata 结构断言——不需要真实 Postgres，快速反馈（issue #48）。"""

from chat_agents import db  # noqa: F401  (registers app/obs models onto Base.metadata)
from chat_agents.database import Base
from sqlalchemy import Table


def _table(schema: str, name: str) -> Table:
    return Base.metadata.tables[f"{schema}.{name}"]


def test_app_and_obs_tables_registered() -> None:
    names = {t.fullname for t in Base.metadata.tables.values()}
    assert names == {
        "app.session",
        "app.message",
        "app.prompt_versions",
        "app.tool_schema_versions",
        "app.discovered_model",
        "app.discovered_model_refresh",
        "obs.run",
        "obs.span",
    }


def test_message_table_has_no_run_id_column() -> None:
    message = _table("app", "message")
    assert "run_id" not in message.columns


def test_message_primary_key_is_not_autoincrement() -> None:
    message = _table("app", "message")
    (pk_col,) = message.primary_key.columns
    assert pk_col.name == "id"
    assert pk_col.autoincrement is False


def test_span_table_has_six_materialized_usage_columns() -> None:
    span = _table("obs", "span")
    assert {
        "role",
        "model",
        "input_tokens",
        "output_tokens",
        "usage_status",
        "reasoning_tokens",
    } <= set(span.columns.keys())


def test_session_table_has_pruned_run_count() -> None:
    session = _table("app", "session")
    assert "pruned_run_count" in session.columns


def test_no_cost_columns_anywhere() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert "cost" not in column.name.lower()


def test_all_foreign_keys_point_obs_to_app_only() -> None:
    for table in Base.metadata.tables.values():
        table_schema = table.schema
        for fk in table.foreign_keys:
            target_schema = fk.column.table.schema
            assert not (table_schema == "app" and target_schema == "obs")
