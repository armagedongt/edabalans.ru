"""Add recipe calculator data, access and future checkout grants.

Revision ID: 20260827_0027
Revises: 20260827_0026
"""

from alembic import op


revision = "20260827_0027"
down_revision = "20260827_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO resources(code, name, status)
        VALUES ('recipes', 'Калькулятор рецептов', 'active')
        ON CONFLICT (code) DO NOTHING;

        CREATE TABLE nutrition_products (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_user_id uuid REFERENCES users(id) ON DELETE CASCADE,
            name varchar(255) NOT NULL,
            name_normalized varchar(255) NOT NULL,
            protein_g numeric(10,3) NOT NULL,
            fat_g numeric(10,3) NOT NULL,
            carbohydrate_g numeric(10,3) NOT NULL,
            calories_kcal numeric(10,3) NOT NULL,
            source_url text UNIQUE,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_nutrition_product_nonnegative CHECK (
              protein_g >= 0 AND fat_g >= 0 AND carbohydrate_g >= 0 AND calories_kcal >= 0
            )
        );
        CREATE INDEX ix_nutrition_products_catalog_search
          ON nutrition_products(owner_user_id, is_active, name_normalized);

        CREATE TABLE recipe_books (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title varchar(255) NOT NULL,
            shrinkage_g integer NOT NULL DEFAULT 0,
            version integer NOT NULL DEFAULT 1,
            deleted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_recipe_book_shrinkage_nonnegative CHECK (shrinkage_g >= 0)
        );
        CREATE INDEX ix_recipe_books_owner_active
          ON recipe_books(owner_user_id, deleted_at, updated_at);

        CREATE TABLE recipe_ingredients (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            recipe_id uuid NOT NULL REFERENCES recipe_books(id) ON DELETE CASCADE,
            nutrition_product_id uuid REFERENCES nutrition_products(id) ON DELETE RESTRICT,
            nested_recipe_id uuid REFERENCES recipe_books(id) ON DELETE RESTRICT,
            weight_g integer NOT NULL,
            sort_order integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_recipe_ingredient_weight_positive CHECK (weight_g > 0),
            CONSTRAINT ck_recipe_ingredient_single_source CHECK (
              (nutrition_product_id IS NOT NULL) <> (nested_recipe_id IS NOT NULL)
            )
        );
        CREATE INDEX ix_recipe_ingredients_recipe_order ON recipe_ingredients(recipe_id, sort_order);
        CREATE INDEX ix_recipe_ingredients_nested_recipe ON recipe_ingredients(nested_recipe_id);

        INSERT INTO user_accesses(user_id, resource_id, source, granted_at)
        SELECT DISTINCT old_access.user_id, calculator.id, 'recipe_calculator_backfill', now()
        FROM user_accesses old_access
        JOIN resources old_resource ON old_resource.id = old_access.resource_id
        JOIN resources calculator ON calculator.code = 'recipes'
        WHERE old_resource.code IN ('ACCESS_RECIPES', 'ACCESS_CALORIES')
          AND old_access.revoked_at IS NULL
          AND (old_access.expires_at IS NULL OR old_access.expires_at > now());

        INSERT INTO product_access_rules(product_id, resource_id, effective_from)
        SELECT DISTINCT rule.product_id, calculator.id, NULL
        FROM product_access_rules rule
        JOIN resources old_resource ON old_resource.id = rule.resource_id
        JOIN resources calculator ON calculator.code = 'recipes'
        WHERE old_resource.code IN ('ACCESS_RECIPES', 'ACCESS_CALORIES')
          AND NOT EXISTS (
            SELECT 1 FROM product_access_rules existing
            WHERE existing.product_id = rule.product_id
              AND existing.resource_id = calculator.id
              AND existing.effective_from IS NULL
          );

        UPDATE price_entries
        SET resource_codes = (
          SELECT jsonb_agg(DISTINCT value)
          FROM jsonb_array_elements_text(resource_codes || '["recipes"]'::jsonb) AS values(value)
        )
        WHERE resource_codes ? 'ACCESS_RECIPES' OR resource_codes ? 'ACCESS_CALORIES';
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM user_accesses
        WHERE source = 'recipe_calculator_backfill';
        DELETE FROM product_access_rules
        WHERE resource_id = (SELECT id FROM resources WHERE code = 'recipes');
        DROP TABLE IF EXISTS recipe_ingredients;
        DROP TABLE IF EXISTS recipe_books;
        DROP TABLE IF EXISTS nutrition_products;
        DELETE FROM resources WHERE code = 'recipes';
    """)
