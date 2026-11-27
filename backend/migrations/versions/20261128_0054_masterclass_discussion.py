"""Store the owner-only masterclass discussion pilot."""
from alembic import op
import sqlalchemy as sa

revision = "20261128_0054"
down_revision = "20261126_0053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "masterclass_discussion_posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("client_nonce", sa.String(64), nullable=False, unique=True),
        sa.Column("source_label", sa.String(100)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("photo", sa.Boolean(), nullable=False),
        sa.Column("voice", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("reply_to_id", sa.Integer(), sa.ForeignKey("masterclass_discussion_posts.id", ondelete="SET NULL")),
        sa.Column("featured", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_masterclass_discussion_posts_day_number", "masterclass_discussion_posts", ["day_number"])
    op.create_table(
        "masterclass_discussion_reads",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("masterclass_discussion_posts.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "masterclass_discussion_profiles",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("about", sa.String(500), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("photo_key", sa.Uuid()),
    )
    op.create_table(
        "masterclass_discussion_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("subscription", sa.JSON(), nullable=False),
        sa.Column("replies", sa.Boolean(), nullable=False),
        sa.Column("new_posts", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_masterclass_discussion_subscriptions_user_id", "masterclass_discussion_subscriptions", ["user_id"])
    op.create_table(
        "masterclass_discussion_pushes",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("masterclass_discussion_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dedupe", sa.String(180), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_masterclass_discussion_pushes_subscription_id", "masterclass_discussion_pushes", ["subscription_id"])
    op.create_index("ix_masterclass_discussion_pushes_due_at", "masterclass_discussion_pushes", ["due_at"])
    posts = sa.table(
        "masterclass_discussion_posts", sa.column("day_number", sa.Integer),
        sa.column("client_nonce", sa.String), sa.column("source_label", sa.String),
        sa.column("body", sa.Text), sa.column("photo", sa.Boolean), sa.column("voice", sa.Boolean),
        sa.column("archived", sa.Boolean), sa.column("featured", sa.Boolean),
    )
    questions = (
        ("mixed", "Как учесть мясо и овощи, если они вместе в супе?"),
        ("portion", "Как выбрать мерку порции, если я ем из разных тарелок?"),
        ("vegetables", "К какой категории отнести овощи в готовом блюде, если там есть соус?"),
        ("grains", "Как отмечать крупу, если я знаю вес готовой порции?"),
    )
    op.bulk_insert(posts, [
        dict(day_number=4, client_nonce=f"dqs-example-{key}", source_label="Учебный пример",
             body=body, photo=False, voice=False, archived=True, featured=False)
        for key, body in questions
    ])


def downgrade():
    op.drop_table("masterclass_discussion_pushes")
    op.drop_table("masterclass_discussion_subscriptions")
    op.drop_table("masterclass_discussion_profiles")
    op.drop_table("masterclass_discussion_reads")
    op.drop_index("ix_masterclass_discussion_posts_day_number", table_name="masterclass_discussion_posts")
    op.drop_table("masterclass_discussion_posts")
