from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.models import Sequence, SequenceStep, SequenceVersion
from app.seed import POSTMASTERCLASS_CODE, POSTPURCHASE_CODE, PREPURCHASE_CODE, seed_defaults


def test_prepurchase_graph_has_no_repeated_purchase_conditions(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'seed-lifecycle.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "test_bot")
        sequence = session.scalar(select(Sequence).where(Sequence.code == PREPURCHASE_CODE))
        version = session.scalar(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == sequence.id, SequenceVersion.status == "published")
            .order_by(SequenceVersion.version_no.desc())
        )
        steps = list(session.scalars(
            select(SequenceStep).where(SequenceStep.sequence_version_id == version.id)
        ))

        assert not [step for step in steps if (step.configuration or {}).get("condition") == "has_product"]
        assert not [step for step in steps if step.step_key.startswith("nurture_paid_check_")]
        messages = [step for step in steps if step.kind == "MESSAGE"]
        assert len(messages) == 17
        assert messages[0].configuration["campaign_day"] == 1
        assert messages[-1].configuration["campaign_day"] == 24
        assert any(step.step_key == "nurture_finish_day25" for step in steps)


def test_postpurchase_has_review_week_and_postmasterclass_is_disabled(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'postpurchase-seed.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_defaults(session, "test_bot")
        postpurchase = session.scalar(select(Sequence).where(Sequence.code == POSTPURCHASE_CODE))
        post_version = session.scalar(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == postpurchase.id)
            .order_by(SequenceVersion.version_no.desc())
        )
        keys = set(session.scalars(
            select(SequenceStep.step_key).where(SequenceStep.sequence_version_id == post_version.id)
        ))
        assert {"pp_review_week_day2", "pp_review_week_day4", "pp_review_week_day7"} <= keys

        future = session.scalar(select(Sequence).where(Sequence.code == POSTMASTERCLASS_CODE))
        assert future.status == "disabled"
        future_version = session.scalar(select(SequenceVersion).where(SequenceVersion.sequence_id == future.id))
        future_steps = list(session.scalars(select(SequenceStep).where(SequenceStep.sequence_version_id == future_version.id)))
        assert [(step.kind, step.step_key) for step in future_steps] == [("STOP", "postmasterclass_not_configured")]
