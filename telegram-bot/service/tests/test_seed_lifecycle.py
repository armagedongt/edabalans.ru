from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.models import Sequence, SequenceStep, SequenceVersion
from app.seed import PREPURCHASE_CODE, seed_defaults


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
