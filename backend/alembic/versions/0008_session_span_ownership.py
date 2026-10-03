"""Allow root spans owned directly by a session (issue #92)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_session_span_ownership"
down_revision = "0007_title_generation_claim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "span",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="obs",
    )
    op.create_foreign_key(
        "fk_obs_span_session_id",
        "span",
        "session",
        ["session_id"],
        ["id"],
        source_schema="obs",
        referent_schema="app",
    )
    op.create_index("ix_obs_span_session_id", "span", ["session_id"], schema="obs")
    op.alter_column(
        "span", "run_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True, schema="obs"
    )
    op.create_check_constraint(
        "ck_obs_span_one_owner",
        "span",
        "(run_id IS NULL) <> (session_id IS NULL)",
        schema="obs",
    )
    op.create_check_constraint(
        "ck_obs_span_session_root",
        "span",
        "session_id IS NULL OR parent_span_id IS NULL",
        schema="obs",
    )
    op.execute(
        "COMMENT ON COLUMN obs.span.session_id IS "
        "'独立会话跨度的归属；历史运行跨度只保留 run_id（issue #92）。'"
    )
    op.execute(
        "COMMENT ON COLUMN obs.span.run_id IS '运行跨度的归属；独立会话根跨度为空（issue #92）。'"
    )


def downgrade() -> None:
    pass
