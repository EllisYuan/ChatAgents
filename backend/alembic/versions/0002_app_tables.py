"""Create app schema tables (issue #48)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_app_tables"
down_revision = "0001_schemas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pruned_run_count", sa.Integer(), nullable=False, server_default="0"),
        schema="app",
    )

    op.create_table(
        "prompt_versions",
        sa.Column("version_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=12), nullable=False),
        sa.Column("variables", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )

    op.create_table(
        "tool_schema_versions",
        sa.Column("version_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=12), nullable=False),
        sa.Column("effort_tier", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )

    op.create_table(
        "discovered_model",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("endpoint_profile", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("owned_by", sa.String(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "endpoint_profile",
            "model_id",
            name="uq_discovered_model_profile_model",
        ),
        schema="app",
    )

    op.create_table(
        "message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.session.id"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("round_trip_payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("session_id", "seq", name="uq_message_session_seq"),
        schema="app",
    )
    op.create_index("ix_app_message_session_id", "message", ["session_id"], schema="app")


def downgrade() -> None:
    # 不做反向迁移——`downgrade` 不进部署流程，回滚靠切旧镜像对着新 schema 跑
    # （ADR-0031：加性变更，删除留到确认不再回滚之后的下一个版本）。
    pass
