"""Record the terminal outcome of a session's one-shot title generation (issue #93)."""

import sqlalchemy as sa
from alembic import op

revision = "0009_title_generation_outcome"
down_revision = "0008_session_span_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session",
        sa.Column("title_generation_outcome", sa.Text(), nullable=True),
        schema="app",
    )
    op.execute(
        "COMMENT ON COLUMN app.session.title_generation_outcome IS "
        "'标题生成唯一尝试的终态：applied / fallback / manual_not_applied；"
        "NULL 表示已认领但尚未终态（issue #93）。'"
    )


def downgrade() -> None:
    # 部署回滚使用旧代码和新 schema，不删除已记录的业务事实（ADR-0031）。
    pass
