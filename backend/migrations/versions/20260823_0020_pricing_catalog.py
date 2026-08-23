"""Add versioned pricing catalog and staged public checkout metadata.

Revision ID: 20260823_0020
Revises: 20260823_0019
"""

from alembic import op


revision = "20260823_0020"
down_revision = "20260823_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pricing_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            version_number integer NOT NULL UNIQUE,
            name varchar(160) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'draft',
            effective_from timestamptz,
            activated_at timestamptz,
            created_by varchar(255) NOT NULL,
            activated_by varchar(255),
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_pricing_version_status CHECK (status IN ('draft','active','archived'))
        );

        CREATE UNIQUE INDEX uq_pricing_one_draft
          ON pricing_versions(status) WHERE status = 'draft';
        CREATE UNIQUE INDEX uq_pricing_one_active
          ON pricing_versions(status) WHERE status = 'active';

        CREATE TABLE price_entries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            version_id uuid NOT NULL REFERENCES pricing_versions(id) ON DELETE CASCADE,
            code varchar(120) NOT NULL,
            section varchar(40) NOT NULL,
            name varchar(255) NOT NULL,
            product_code varchar(80),
            stage_code varchar(40),
            resource_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
            item_count integer,
            regular_amount numeric(14,2),
            compare_at_amount numeric(14,2),
            sale_amount numeric(14,2) NOT NULL,
            currency varchar(3) NOT NULL DEFAULT 'RUB',
            enabled boolean NOT NULL DEFAULT true,
            sort_order integer NOT NULL DEFAULT 0,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_price_entry_version_code UNIQUE(version_id, code),
            CONSTRAINT ck_price_entry_amounts CHECK (
                sale_amount >= 0
                AND (regular_amount IS NULL OR regular_amount >= 0)
                AND (compare_at_amount IS NULL OR compare_at_amount >= 0)
            )
        );
        CREATE INDEX ix_price_entries_version ON price_entries(version_id);
        CREATE INDEX ix_price_entries_section ON price_entries(section);

        ALTER TABLE offer_checkouts ALTER COLUMN user_id DROP NOT NULL;
        ALTER TABLE offer_checkouts ADD COLUMN checkout_kind varchar(32) NOT NULL DEFAULT 'member_offer';
        ALTER TABLE offer_checkouts ADD COLUMN pricing_version_id uuid REFERENCES pricing_versions(id) ON DELETE SET NULL;
        ALTER TABLE offer_checkouts ADD COLUMN price_entry_code varchar(120);
        CREATE INDEX ix_offer_checkouts_pricing_version ON offer_checkouts(pricing_version_id);

        ALTER TABLE payments ADD COLUMN pricing_version_id uuid REFERENCES pricing_versions(id) ON DELETE SET NULL;
        ALTER TABLE payments ADD COLUMN price_entry_code varchar(120);
        CREATE INDEX ix_payments_pricing_version ON payments(pricing_version_id);

        INSERT INTO pricing_versions(version_number,name,status,created_by,note)
        VALUES (1,'Стартовый каталог перед новым сайтом','draft','system',
                'Подготовлен из канонической продуктовой карты; не активирован');

        INSERT INTO price_entries(
            version_id,code,section,name,product_code,stage_code,resource_codes,item_count,
            regular_amount,compare_at_amount,sale_amount,enabled,sort_order
        )
        SELECT v.id,x.code,x.section,x.name,x.product_code,x.stage_code,x.resource_codes,
               x.item_count,x.regular_amount,x.compare_at_amount,x.sale_amount,x.enabled,x.sort_order
        FROM pricing_versions v
        CROSS JOIN (VALUES
          ('site.masterclass.basic','site_tariffs','Базовый','MASTERCLASS_BASIC',NULL,'["ACCESS_MASTERCLASS"]'::jsonb,NULL,6900,6900,6900,true,10),
          ('site.masterclass.recipes','site_tariffs','С рецептами','MASTERCLASS_RECIPES',NULL,'["ACCESS_MASTERCLASS","ACCESS_RECIPES"]'::jsonb,NULL,10800,10800,8900,true,20),
          ('site.masterclass.consult','site_tariffs','С консультацией','MASTERCLASS_CONSULT',NULL,'["ACCESS_MASTERCLASS","ACCESS_RECIPES","ACCESS_CONSULTATION"]'::jsonb,NULL,17700,17700,15900,true,30),
          ('product.recipes','products','Система рецептов','RECIPES',NULL,'["ACCESS_RECIPES"]'::jsonb,NULL,3900,3900,3900,true,100),
          ('product.calories','products','Мини-курс «Калорийный»','CALORIES',NULL,'["ACCESS_CALORIES"]'::jsonb,NULL,3900,3900,3900,true,110),
          ('product.training','products','Мини-курс «С дивана до тренировок»','TRAINING',NULL,'["ACCESS_STRENGTH"]'::jsonb,NULL,3900,3900,3900,false,120),
          ('product.recordings','products','Записи консультаций','CONSULTATION_RECORDINGS',NULL,'["ACCESS_CONSULTATION_RECORDINGS"]'::jsonb,NULL,3900,3900,3900,false,130),
          ('product.consultation','products','Индивидуальная консультация','CONSULTATION',NULL,'["ACCESS_CONSULTATION"]'::jsonb,NULL,8900,8900,8900,true,140),
          ('upsell.early.single','upsells','Один продукт — ранняя цена',NULL,'early','[]'::jsonb,1,3900,3900,2900,true,200),
          ('upsell.second.single','upsells','Один продукт — второе предложение',NULL,'second','[]'::jsonb,1,3900,3900,3300,true,210),
          ('upsell.review.single','upsells','Один продукт — саморевью',NULL,'review','[]'::jsonb,1,3900,3900,3500,true,220),
          ('upsell.last_week.single','upsells','Один продукт — последняя неделя',NULL,'last_week','[]'::jsonb,1,3900,3900,3800,true,230),
          ('upsell.standard.single','upsells','Один продукт — стандартная цена',NULL,'standard','[]'::jsonb,1,3900,3900,3900,true,240),
          ('upsell.review.consultation','upsells','Консультация — саморевью',NULL,'review','["ACCESS_CONSULTATION"]'::jsonb,NULL,8900,8900,7500,true,250),
          ('upsell.last_week.consultation','upsells','Консультация — последняя неделя',NULL,'last_week','["ACCESS_CONSULTATION"]'::jsonb,NULL,8900,8900,8400,true,260),
          ('upsell.standard.consultation','upsells','Консультация — стандартная цена',NULL,'standard','["ACCESS_CONSULTATION"]'::jsonb,NULL,8900,8900,8900,true,270),
          ('upsell.early.bundle.1','upsells','Комплект 1 продукта — ранний',NULL,'early','[]'::jsonb,1,3900,3900,1900,true,301),
          ('upsell.early.bundle.2','upsells','Комплект 2 продуктов — ранний',NULL,'early','[]'::jsonb,2,7800,7800,3900,true,302),
          ('upsell.early.bundle.3','upsells','Комплект 3 продуктов — ранний',NULL,'early','[]'::jsonb,3,11700,11700,5900,true,303),
          ('upsell.early.bundle.4','upsells','Комплект 4 продуктов — ранний',NULL,'early','[]'::jsonb,4,15600,15600,7900,true,304),
          ('upsell.second.bundle.1','upsells','Комплект 1 продукта — второй',NULL,'second','[]'::jsonb,1,3900,3900,2500,true,311),
          ('upsell.second.bundle.2','upsells','Комплект 2 продуктов — второй',NULL,'second','[]'::jsonb,2,7800,7800,4900,true,312),
          ('upsell.second.bundle.3','upsells','Комплект 3 продуктов — второй',NULL,'second','[]'::jsonb,3,11700,11700,7400,true,313),
          ('upsell.second.bundle.4','upsells','Комплект 4 продуктов — второй',NULL,'second','[]'::jsonb,4,15600,15600,9900,true,314),
          ('upsell.review.bundle.1','upsells','Комплект 1 продукта — саморевью',NULL,'review','[]'::jsonb,1,3900,3900,2900,true,321),
          ('upsell.review.bundle.2','upsells','Комплект 2 продуктов — саморевью',NULL,'review','[]'::jsonb,2,7800,7800,5700,true,322),
          ('upsell.review.bundle.3','upsells','Комплект 3 продуктов — саморевью',NULL,'review','[]'::jsonb,3,11700,11700,8500,true,323),
          ('upsell.review.bundle.4','upsells','Комплект 4 продуктов — саморевью',NULL,'review','[]'::jsonb,4,15600,15600,11300,true,324),
          ('upsell.last_week.bundle.1','upsells','Комплект 1 продукта — последняя неделя',NULL,'last_week','[]'::jsonb,1,3900,3900,3600,true,331),
          ('upsell.last_week.bundle.2','upsells','Комплект 2 продуктов — последняя неделя',NULL,'last_week','[]'::jsonb,2,7800,7800,7000,true,332),
          ('upsell.last_week.bundle.3','upsells','Комплект 3 продуктов — последняя неделя',NULL,'last_week','[]'::jsonb,3,11700,11700,10400,true,333),
          ('upsell.last_week.bundle.4','upsells','Комплект 4 продуктов — последняя неделя',NULL,'last_week','[]'::jsonb,4,15600,15600,13800,true,334),
          ('upsell.standard.bundle.1','upsells','Комплект 1 продукта — стандарт',NULL,'standard','[]'::jsonb,1,3900,3900,3900,true,341),
          ('upsell.standard.bundle.2','upsells','Комплект 2 продуктов — стандарт',NULL,'standard','[]'::jsonb,2,7800,7800,7800,true,342),
          ('upsell.standard.bundle.3','upsells','Комплект 3 продуктов — стандарт',NULL,'standard','[]'::jsonb,3,11700,11700,11700,true,343),
          ('upsell.standard.bundle.4','upsells','Комплект 4 продуктов — стандарт',NULL,'standard','[]'::jsonb,4,15600,15600,15600,true,344)
        ) AS x(code,section,name,product_code,stage_code,resource_codes,item_count,
               regular_amount,compare_at_amount,sale_amount,enabled,sort_order)
        WHERE v.version_number = 1;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM offer_checkouts WHERE user_id IS NULL;
        ALTER TABLE payments DROP COLUMN IF EXISTS price_entry_code;
        ALTER TABLE payments DROP COLUMN IF EXISTS pricing_version_id;
        ALTER TABLE offer_checkouts DROP COLUMN IF EXISTS price_entry_code;
        ALTER TABLE offer_checkouts DROP COLUMN IF EXISTS pricing_version_id;
        ALTER TABLE offer_checkouts DROP COLUMN IF EXISTS checkout_kind;
        ALTER TABLE offer_checkouts ALTER COLUMN user_id SET NOT NULL;
        DROP TABLE IF EXISTS price_entries;
        DROP TABLE IF EXISTS pricing_versions;
    """)
