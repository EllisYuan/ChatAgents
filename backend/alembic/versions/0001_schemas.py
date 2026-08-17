"""Create the schemas managed by the application."""

from alembic import op

revision = "0001_schemas"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS obs")


def downgrade() -> None:
    pass
