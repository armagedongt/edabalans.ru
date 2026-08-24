import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from sqlalchemy import select

from app.models import (
    MasterclassDayProgress,
    MasterclassStepProgress,
    Resource,
    UserAccess,
    UserEmail,
)
from test_masterclass_journey import setup


def test_day_four_dqs_step_waits_for_completed_tutorial():
    client, factory = setup()
    email = "member@example.test"

    assert client.post(
        "/api/masterclass/course/days/1/open", json={"email": email}
    ).status_code == 200

    # This focused contract test prepares the earlier course progress directly;
    # the day-order and timer behavior is covered in test_masterclass_journey.py.
    with factory() as db:
        user_id = db.scalar(
            select(UserEmail.user_id).where(
                UserEmail.email_normalized == email
            )
        )
        dqs_resource = Resource(code="dqs", name="DQS", status="active")
        db.add(dqs_resource)
        db.flush()
        db.add(
            UserAccess(
                user_id=user_id,
                resource_id=dqs_resource.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            )
        )
        db.add(MasterclassDayProgress(user_id=user_id, day_number=4))
        db.add(
            MasterclassStepProgress(
                user_id=user_id,
                day_number=4,
                step_index=0,
                step_kind="article",
            )
        )
        db.commit()

    opened = client.get(
        "/api/apps/dqs", params={"action": "openUser", "email": email}
    )
    assert opened.status_code == 200
    assert opened.json()["ok"] is True

    not_completed = client.post(
        "/api/masterclass/course/days/4/steps/1/complete",
        json={"email": email},
    )
    assert not_completed.status_code == 200
    assert 1 not in not_completed.json()["days"][3]["completed_steps"]

    tutorial = client.get(
        "/api/apps/dqs",
        params={
            "action": "completeTutorial",
            "email": email,
        },
    )
    assert tutorial.status_code == 200
    assert tutorial.json() == {"ok": True, "completed": True}

    completed = client.post(
        "/api/masterclass/course/days/4/steps/1/complete",
        json={"email": email},
    )
    assert completed.status_code == 200
    assert 1 in completed.json()["days"][3]["completed_steps"]
