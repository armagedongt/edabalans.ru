"""Store direct recipe yield and portion instead of shrinkage.

Revision ID: 20261003_0050
Revises: 20260926_0049
"""

from alembic import op
import sqlalchemy as sa


revision = "20261003_0050"
down_revision = "20260926_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # Freeze both the legacy mass and composition until the atomic backfill completes.
        op.execute("LOCK TABLE recipe_books, recipe_ingredients IN ACCESS EXCLUSIVE MODE")
    invalid = connection.scalar(sa.text("""
        SELECT count(*) FROM (
          SELECT b.id, b.shrinkage_g, coalesce(sum(i.weight_g), 0) AS weight,
                 count(i.id) AS rows, max(i.weight_g) AS max_weight
          FROM recipe_books b LEFT JOIN recipe_ingredients i ON i.recipe_id = b.id
          GROUP BY b.id, b.shrinkage_g
        ) legacy
        WHERE weight - shrinkage_g NOT BETWEEN 1 AND 99999
           OR weight > 99999 OR rows NOT BETWEEN 1 AND 100 OR max_weight > 99999
    """))
    if invalid:
        raise RuntimeError(f"Recipe migration stopped: {invalid} invalid legacy recipes; data was not corrected")

    with op.batch_alter_table("recipe_books") as batch:
        batch.add_column(sa.Column("yield_g", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("portion_g", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE recipe_books
        SET yield_g = (SELECT coalesce(sum(weight_g), 0) FROM recipe_ingredients
                       WHERE recipe_id = recipe_books.id) - shrinkage_g
    """)
    op.execute("UPDATE recipe_books SET portion_g = yield_g")
    with op.batch_alter_table("recipe_books") as batch:
        batch.alter_column("yield_g", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("portion_g", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("ck_recipe_book_shrinkage_nonnegative", type_="check")
        batch.drop_column("shrinkage_g")
        batch.create_check_constraint("ck_recipe_book_yield_bounds", "yield_g BETWEEN 1 AND 99999")
        batch.create_check_constraint("ck_recipe_book_portion_bounds", "portion_g BETWEEN 1 AND 99999 AND portion_g <= yield_g")
    with op.batch_alter_table("recipe_ingredients") as batch:
        batch.drop_constraint("ck_recipe_ingredient_weight_positive", type_="check")
        batch.create_check_constraint("ck_recipe_ingredient_weight_bounds", "weight_g BETWEEN 1 AND 99999")


def downgrade() -> None:
    raise RuntimeError("Direct yield/portion cannot be downgraded losslessly; restore the verified pre-migration backup")
