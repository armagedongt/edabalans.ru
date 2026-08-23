from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.customer_lifecycle import reconcile_masterclass_presale_runs, stop_presale_runs_from_purchase_events
from app.database import Base, make_engine
from app.models import BotInstance, Contact, CrmUser, Sequence, SequenceRun, SequenceVersion


def test_masterclass_access_stops_presale_without_per_message_purchase_checks(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'lifecycle.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(text(
            "CREATE TABLE resources (id TEXT PRIMARY KEY, code TEXT NOT NULL)"
        ))
        session.execute(text(
            "CREATE TABLE user_accesses ("
            "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, resource_id TEXT NOT NULL, "
            "revoked_at DATETIME, expires_at DATETIME)"
        ))
        session.execute(text(
            "CREATE TABLE masterclass_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, event_type TEXT NOT NULL)"
        ))
        user = CrmUser(display_name="Покупатель", status="active", data_origin="native")
        bot = BotInstance(code="test", username="test", display_name="test", token_env_name="TOKEN", is_active=True)
        sequence = Sequence(code="prepurchase_nurture", name="До покупки", status="published")
        session.add_all([user, bot, sequence]); session.flush()
        version = SequenceVersion(sequence_id=sequence.id, version_no=1, status="published")
        session.add(version); session.flush()
        contact = Contact(
            bot_instance_id=bot.id,
            user_id=user.id,
            telegram_user_id="42",
            chat_id="42",
            status="active",
        )
        session.add(contact); session.flush()
        run = SequenceRun(contact_id=contact.id, sequence_version_id=version.id, status="active")
        session.add(run)
        session.execute(text(
            "INSERT INTO resources (id, code) VALUES ('masterclass', 'ACCESS_MASTERCLASS')"
        ))
        session.execute(
            text(
                "INSERT INTO user_accesses (id, user_id, resource_id) "
                "VALUES ('access', :user_id, 'masterclass')"
            ),
            {"user_id": user.id.replace("-", "")},
        )
        session.execute(
            text(
                "INSERT INTO masterclass_events (id, user_id, event_type) "
                "VALUES ('event', :user_id, 'masterclass_purchase_confirmed')"
            ),
            {"user_id": user.id.replace("-", "")},
        )
        session.commit()

        assert stop_presale_runs_from_purchase_events(session) == 1
        session.commit()

        stopped = session.scalar(select(SequenceRun).where(SequenceRun.id == run.id))
        assert stopped.status == "completed"
        assert stopped.context["stopped_reason"] == "masterclass_purchase_confirmed"
        assert reconcile_masterclass_presale_runs(session) == 0
