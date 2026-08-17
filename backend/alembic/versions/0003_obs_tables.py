"""Create obs schema tables (issue #48)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_obs_tables"
down_revision = "0002_app_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.session.id"),
            nullable=False,
        ),
        sa.Column(
            "trigger_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.message.id"),
            nullable=False,
        ),
        sa.Column("last_message_seq", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("effort", sa.String(length=16), nullable=True),
        sa.Column(
            "prompt_version_id",
            sa.String(),
            sa.ForeignKey("app.prompt_versions.version_id"),
            nullable=True,
        ),
        sa.Column(
            "tool_schema_version_id",
            sa.String(),
            sa.ForeignKey("app.tool_schema_versions.version_id"),
            nullable=True,
        ),
        sa.Column("retention_window", sa.Integer(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        schema="obs",
    )
    op.create_index("ix_obs_run_session_id", "run", ["session_id"], schema="obs")

    op.create_table(
        "span",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obs.run.id"),
            nullable=False,
        ),
        sa.Column(
            "parent_span_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obs.span.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_status", sa.String(length=16), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        schema="obs",
    )
    op.create_index("ix_obs_span_run_id", "span", ["run_id"], schema="obs")


def downgrade() -> None:
    # 不做反向迁移——`downgrade` 不进部署流程，回滚靠切旧镜像对着新 schema 跑
    # （ADR-0031：加性变更，删除留到确认不再回滚之后的下一个版本）。
    pass
