"""Add masterclass journey, questionnaires and offer windows.

Revision ID: 20260822_0015
Revises: 20260822_0014
"""

from alembic import op

revision = "20260822_0015"
down_revision = "20260822_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE masterclass_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_key varchar(160) NOT NULL,
            event_type varchar(80) NOT NULL,
            placement varchar(80),
            details json NOT NULL DEFAULT '{}',
            occurred_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_masterclass_user_event_key UNIQUE(user_id, event_key)
        );
        CREATE INDEX ix_masterclass_events_user_id ON masterclass_events(user_id);
        CREATE INDEX ix_masterclass_event_user_type ON masterclass_events(user_id, event_type);

        CREATE TABLE questionnaire_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind varchar(40) NOT NULL,
            version integer NOT NULL DEFAULT 1,
            status varchar(32) NOT NULL DEFAULT 'draft',
            submitted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_questionnaire_user_kind UNIQUE(user_id, kind)
        );
        CREATE INDEX ix_questionnaire_runs_user_id ON questionnaire_runs(user_id);

        CREATE TABLE questionnaire_answers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id uuid NOT NULL REFERENCES questionnaire_runs(id) ON DELETE CASCADE,
            question_code varchar(80) NOT NULL,
            answer_text text NOT NULL DEFAULT '',
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_questionnaire_run_question UNIQUE(run_id, question_code)
        );
        CREATE INDEX ix_questionnaire_answers_run_id ON questionnaire_answers(run_id);

        CREATE TABLE offer_stages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(40) NOT NULL UNIQUE,
            name varchar(160) NOT NULL,
            duration_hours integer,
            pricing json NOT NULL DEFAULT '{}',
            status varchar(32) NOT NULL DEFAULT 'active',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE user_offers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stage_code varchar(40) NOT NULL,
            started_at timestamptz NOT NULL,
            expires_at timestamptz,
            status varchar(32) NOT NULL DEFAULT 'active',
            trigger_event_id uuid REFERENCES masterclass_events(id) ON DELETE SET NULL,
            snapshot json NOT NULL DEFAULT '{}',
            CONSTRAINT uq_user_offer_stage UNIQUE(user_id, stage_code)
        );
        CREATE INDEX ix_user_offers_user_id ON user_offers(user_id);

        CREATE TABLE offer_checkouts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            offer_code varchar(120) NOT NULL,
            title varchar(255) NOT NULL,
            items json NOT NULL DEFAULT '[]',
            amount numeric(14,2) NOT NULL,
            expires_at timestamptz NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'pending',
            payment_id uuid REFERENCES payments(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_offer_checkouts_user_id ON offer_checkouts(user_id);

        CREATE TABLE masterclass_notifications (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_id uuid REFERENCES masterclass_events(id) ON DELETE SET NULL,
            notification_kind varchar(80) NOT NULL,
            content_code varchar(120),
            deduplication_key varchar(180) NOT NULL,
            due_at timestamptz NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'pending',
            payload json NOT NULL DEFAULT '{}',
            sent_at timestamptz,
            error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_masterclass_notification_dedup UNIQUE(user_id, deduplication_key)
        );
        CREATE INDEX ix_masterclass_notifications_user_id ON masterclass_notifications(user_id);
        CREATE INDEX ix_masterclass_notification_due ON masterclass_notifications(status, due_at);

        INSERT INTO offer_stages(code,name,duration_hours,pricing) VALUES
          ('early','Максимальная ранняя выгода',96,json_build_object('single',2900,'bundle',json_build_object('1',1900,'2',3900,'3',5900,'4',7900))),
          ('second','Второе предложение',72,json_build_object('single',3300,'bundle',json_build_object('1',2500,'2',4900,'3',7400,'4',9900))),
          ('review','Саморевью',72,json_build_object('single',3500,'consultation',7500,'bundle',json_build_object('1',2900,'2',5700,'3',8500,'4',11300))),
          ('last_week','Последняя неделя',168,json_build_object('single',3800,'consultation',8400,'bundle',json_build_object('1',3600,'2',7000,'3',10400,'4',13800))),
          ('standard','Стандартные цены',NULL,json_build_object('single',3900,'consultation',8900,'bundle',json_build_object('1',3900,'2',7800,'3',11700,'4',15600)));

        INSERT INTO resources(code,name,status) VALUES
          ('ACCESS_RECIPES','Система рецептов','active'),
          ('ACCESS_CALORIES','Мини-курс «Калорийный»','active'),
          ('ACCESS_STRENGTH','Мини-курс «С дивана до тренировок»','active'),
          ('ACCESS_CONSULTATION_RECORDINGS','Записи консультаций других участников','active'),
          ('ACCESS_CONSULTATION','Индивидуальная консультация','active')
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS masterclass_notifications;
        DROP TABLE IF EXISTS offer_checkouts;
        DROP TABLE IF EXISTS user_offers;
        DROP TABLE IF EXISTS offer_stages;
        DROP TABLE IF EXISTS questionnaire_answers;
        DROP TABLE IF EXISTS questionnaire_runs;
        DROP TABLE IF EXISTS masterclass_events;
    """)
