"""Prevent duplicate model-input versions during repeated or concurrent startup."""

from alembic import op

revision = "0005_version_uniqueness"
down_revision = "0004_model_refresh_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_prompt_versions_name_hash",
        "prompt_versions",
        ["name", "content_hash"],
        schema="app",
    )
    op.create_unique_constraint(
        "uq_tool_schema_versions_name_effort_hash",
        "tool_schema_versions",
        ["name", "effort_tier", "content_hash"],
        schema="app",
    )


def downgrade() -> None:
    # 不做反向迁移——回滚靠切旧镜像对着新 schema 跑（ADR-0031）。
    pass
