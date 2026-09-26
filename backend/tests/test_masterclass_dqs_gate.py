import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from sqlalchemy import select

from app.models import (
    DqsState,
    MasterclassDayProgress,
    MasterclassEvent,
    MasterclassStepProgress,
    Resource,
    User,
    UserAccess,
    UserEmail,
    UserLegalAcceptance,
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
        other_user = User(display_name="Other tutorial user")
        db.add(other_user)
        db.flush()
        db.add(MasterclassEvent(
            user_id=other_user.id, event_key="dqs_tutorial_completed",
            event_type="dqs_tutorial_completed",
        ))
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
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    revealed = client.post(
        "/api/masterclass/apps/dqs/reveal",
        json={
            "email": email,
            "day": 4,
            "step_index": 1,
            "placement": "day-04-dqs",
        },
    )
    assert revealed.status_code == 200

    opened = client.get(
        "/api/apps/dqs", params={"action": "openUser", "email": email}
    )
    assert opened.status_code == 200
    assert opened.json()["ok"] is True
    assert opened.json()["tutorialCompleted"] is False

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

    reopened = client.get(
        "/api/apps/dqs", params={"action": "openUser", "email": email}
    )
    assert reopened.json()["tutorialCompleted"] is True
    assert reopened.json()["days"] == opened.json()["days"]
    assert reopened.json()["startDate"] == opened.json()["startDate"]

    repeated = client.get(
        "/api/apps/dqs", params={"action": "completeTutorial", "email": email}
    )
    assert repeated.json() == {"ok": True, "completed": True}
    with factory() as db:
        events = list(db.scalars(select(MasterclassEvent).where(
            MasterclassEvent.user_id == user_id,
            MasterclassEvent.event_key == "dqs_tutorial_completed",
        )))
        assert len(events) == 1

    completed = client.post(
        "/api/masterclass/course/days/4/steps/1/complete",
        json={"email": email},
    )
    assert completed.status_code == 200
    assert 1 in completed.json()["days"][3]["completed_steps"]


def test_dqs_access_holder_accepts_current_legal_documents_before_entry():
    client, factory = setup()
    email = "member@example.test"

    with factory() as db:
        user_id = db.scalar(
            select(UserEmail.user_id).where(UserEmail.email_normalized == email)
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
        db.add(MasterclassEvent(
            user_id=user_id,
            event_key="app:dqs:revealed",
            event_type="app_revealed_dqs",
            placement="day-04-dqs",
            details={},
        ))
        db.query(UserLegalAcceptance).delete()
        db.add_all(
            [
                UserLegalAcceptance(
                    user_id=user_id,
                    document_code="educational_disclaimer",
                    document_version="2026-08-24-v1",
                    source="test-old-version",
                ),
                UserLegalAcceptance(
                    user_id=user_id,
                    document_code="personal_data_consent",
                    document_version="2026-08-23-v1",
                    source="test-old-version",
                ),
            ]
        )
        db.commit()

    status = client.get("/api/apps/dqs/access")
    assert status.status_code == 200
    assert status.json()["legal"]["required"] is True
    assert {
        item["code"] for item in status.json()["legal"]["documents"]
    } == {"educational_disclaimer", "personal_data_consent"}

    blocked = client.get(
        "/api/apps/dqs", params={"action": "openUser", "email": email}
    )
    assert blocked.status_code == 200
    assert blocked.json()["ok"] is False

    accepted = client.post(
        "/api/account-auth/legal-acceptances",
        json={
            "document_codes": [
                "educational_disclaimer",
                "personal_data_consent",
            ],
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["legal"]["required"] is False

    ready = client.get("/api/apps/dqs/access")
    assert ready.status_code == 200
    assert ready.json()["legal"]["required"] is False
    opened = client.get(
        "/api/apps/dqs", params={"action": "openUser", "email": email}
    )
    assert opened.status_code == 200
    assert opened.json()["ok"] is True

    with factory() as db:
        acceptances = list(db.scalars(select(UserLegalAcceptance)))
        assert len(acceptances) == 4
        assert sum(item.source == "native_account" for item in acceptances) == 2


def test_dqs_legal_status_is_not_exposed_without_dqs_access():
    client, factory = setup()
    email = "member@example.test"
    with factory() as db:
        db.query(UserLegalAcceptance).delete()
        db.commit()

    status = client.get("/api/apps/dqs/access")
    assert status.status_code == 403
    assert "нет доступа" in status.json()["detail"].lower()

    direct = client.get(
        "/api/apps/dqs", params={"action": "openUser", "email": email}
    )
    assert direct.status_code == 200
    assert direct.json()["ok"] is False
    assert "нет доступа" in direct.json()["error"].lower()
    assert "дисклеймер" not in direct.json()["error"].lower()


def test_existing_imported_dqs_state_keeps_access_but_empty_admin_state_does_not():
    client, factory = setup()
    email = "member@example.test"
    with factory() as db:
        user_id = db.scalar(
            select(UserEmail.user_id).where(UserEmail.email_normalized == email)
        )
        dqs_resource = Resource(code="dqs", name="DQS", status="active")
        db.add(dqs_resource)
        db.flush()
        db.add(UserAccess(
            user_id=user_id,
            resource_id=dqs_resource.id,
            source="test",
            granted_at=datetime.now(timezone.utc),
        ))
        db.add(DqsState(
            user_id=user_id,
            start_date="2026-08-01",
            days={},
            source="legacy_import",
        ))
        db.commit()

    assert client.get("/api/apps/dqs/access").status_code == 200

    with factory() as db:
        state = db.scalar(select(DqsState))
        state.days = {"1": {"p": [0] * 17, "d": [None] * 17}}
        state.start_date = "2026-08-01"
        state.source = "admin_open"
        db.commit()

    assert client.get("/api/apps/dqs/access").status_code == 403


def test_client_dqs_open_event_cannot_bypass_day_four_reveal():
    client, factory = setup()
    email = "member@example.test"
    with factory() as db:
        user_id = db.scalar(
            select(UserEmail.user_id).where(UserEmail.email_normalized == email)
        )
        dqs_resource = Resource(code="dqs", name="DQS", status="active")
        db.add(dqs_resource)
        db.flush()
        db.add(UserAccess(
            user_id=user_id,
            resource_id=dqs_resource.id,
            source="test",
            granted_at=datetime.now(timezone.utc),
        ))
        db.commit()

    forged = client.post(
        "/api/masterclass/events",
        json={
            "email": email,
            "event_key": "client:dqs-opened",
            "event_type": "dqs_opened",
            "placement": "forged",
        },
    )
    assert forged.status_code == 200
    assert client.get("/api/apps/dqs/access").status_code == 403
