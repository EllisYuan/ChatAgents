"""Persist the last successful model-catalog refresh (issue #49)."""

import sqlalchemy as sa
from alembic import op

revision = "0004_model_refresh_state"
down_revision = "0003_obs_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovered_model_refresh",
        sa.Column("endpoint_profile", sa.String(), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=False),
        schema="app",
    )


def downgrade() -> None:
    # 不做反向迁移——回滚靠切旧镜像对着新 schema 跑（ADR-0031）。
    pass
