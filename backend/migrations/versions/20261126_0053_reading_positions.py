"""Save a short-lived reading position outside course completion state."""
from alembic import op
import sqlalchemy as sa

revision = "20261126_0053"
down_revision = "20261010_0052"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reading_positions",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("target", sa.String(180), primary_key=True),
        sa.Column("position", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("reading_positions")
