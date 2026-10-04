"""Persist one-shot title eligibility and manual rename protection."""

import sqlalchemy as sa
from alembic import op

revision = "0007_title_generation_claim"
down_revision = "0006_schema_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session",
        sa.Column(
            "title_generation_eligible", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        schema="app",
    )
    op.add_column(
        "session",
        sa.Column("title_generation_claimed_at", sa.DateTime(timezone=True)),
        schema="app",
    )
    op.add_column(
        "session",
        sa.Column("title_manually_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )


def downgrade() -> None:
    # 部署回滚使用旧代码和新 schema，不删除已记录的业务事实（ADR-0031）。
    pass
