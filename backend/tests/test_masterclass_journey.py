import os
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.auth import require_admin  # noqa: E402
from app.app_auth import create_app_session, create_placement_token  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.legal_service import LEGAL_DOCUMENTS  # noqa: E402
from app.models import (  # noqa: E402
    MasterclassDayProgress, MasterclassEvent, MasterclassNotification,
    MessengerLinkToken, OfferCheckout, OfferStage,
    QuestionnaireAnswer, Resource, User, UserAccess, UserEmail,
    UserLegalAcceptance, UserOffer,
)


TEST_SETTINGS = Settings(
    database_url="sqlite+pysqlite:///:memory:",
    admin_password="test-app-secret",
    app_auth_secret="test-client-session-secret",
    telegram_test_bot_username="EdabalansTestBot",
)


def placement_token(placement: str) -> str:
    return create_placement_token(placement, TEST_SETTINGS)


def placement_query(placement: str) -> str:
    return f"placement={placement}&placement_token={placement_token(placement)}"


def test_masterclass_migration_avoids_sqlalchemy_bind_like_json_literals():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260822_0015_masterclass_journey.py"
    ).read_text(encoding="utf-8")
    assert "json_build_object('single',2900" in migration
    assert '\":2900' not in migration


def test_messenger_link_migration_stores_only_token_hash():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260823_0016_messenger_link_tokens.py"
    ).read_text(encoding="utf-8")
    assert "token_hash varchar(64) NOT NULL UNIQUE" in migration
    assert "token varchar" not in migration


def setup(authenticated=True):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def override():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    app.dependency_overrides[get_settings] = lambda: TEST_SETTINGS
    with factory() as db:
        user = User(display_name="Участник", status="active")
        db.add(user); db.flush()
        db.add(UserEmail(user_id=user.id, email_original="member@example.test", email_normalized="member@example.test", is_primary=True, source="test"))
        resources = {}
        for code in ("ACCESS_MASTERCLASS", "ACCESS_RECIPES", "ACCESS_CONSULTATION"):
            resources[code] = Resource(code=code, name=code, status="active")
            db.add(resources[code])
        db.flush()
        db.add(UserAccess(user_id=user.id, resource_id=resources["ACCESS_MASTERCLASS"].id, source="test", granted_at=datetime.now(timezone.utc)))
        db.add_all([
            UserLegalAcceptance(
                user_id=user.id,
                document_code=item["code"],
                document_version=item["version"],
                source="test",
            )
            for item in LEGAL_DOCUMENTS
        ])
        stages = [
            ("early", 96, {"single": 2900, "bundle": {"4": 7900}}),
            ("second", 72, {"single": 3300, "bundle": {"4": 9900}}),
            ("review", 72, {"single": 3500, "consultation": 7500, "bundle": {"4": 11300}}),
            ("last_week", 168, {"single": 3800, "consultation": 8400, "bundle": {"4": 13800}}),
            ("standard", None, {"single": 3900, "consultation": 8900, "bundle": {"4": 15600}}),
        ]
        for code, hours, pricing in stages: db.add(OfferStage(code=code, name=code, duration_hours=hours, pricing=pricing, status="active"))
        db.commit()
    headers = {}
    if authenticated:
        headers["Authorization"] = f"Bearer {create_app_session('member@example.test', TEST_SETTINGS)}"
    return TestClient(app, headers=headers), factory


def test_masterclass_personal_data_uses_tilda_email_and_server_access():
    client, _ = setup(authenticated=False)
    response = client.get(
        "/api/masterclass/questionnaires/onboarding?email=member@example.test"
    )
    assert response.status_code == 200
    denied = client.get(
        "/api/masterclass/questionnaires/onboarding?email=other@example.test"
    )
    assert denied.status_code == 403


def test_questionnaire_autosaves_each_answer_and_submit_is_idempotent():
    client, factory = setup()
    opened = client.get("/api/masterclass/questionnaires/onboarding?email=member@example.test")
    assert opened.status_code == 200
    assert len(opened.json()["questions"]) == 15
    payload = {"email": "member@example.test", "question_code": "main_request", "answer_text": "Хочу наладить питание"}
    assert client.put("/api/masterclass/questionnaires/onboarding/answer", json=payload).status_code == 200
    assert client.put("/api/masterclass/questionnaires/onboarding/answer", json={**payload, "answer_text": "Обновлённый ответ"}).status_code == 200
    assert client.post("/api/masterclass/questionnaires/onboarding/submit", json={"email": "member@example.test"}).status_code == 200
    assert client.post("/api/masterclass/questionnaires/onboarding/submit", json={"email": "member@example.test"}).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count(QuestionnaireAnswer.id))) == 1
        assert db.scalar(select(QuestionnaireAnswer.answer_text)) == "Обновлённый ответ"
        assert db.scalar(select(func.count(MasterclassEvent.id))) == 1


def test_onboarding_can_generate_only_one_active_short_lived_telegram_link():
    client, factory = setup()
    first = client.post("/api/masterclass/messenger-links", json={
        "email": "member@example.test",
        "platform": "telegram",
    })
    assert first.status_code == 200
    first_payload = first.json()["deep_link"].split("?start=", 1)[1]
    assert first.json()["deep_link"].startswith("https://t.me/EdabalansTestBot?start=M")
    assert len(first_payload) <= 32
    assert "=" not in first_payload

    second = client.post("/api/masterclass/messenger-links", json={
        "email": "member@example.test",
        "platform": "telegram",
    })
    assert second.status_code == 200
    second_payload = second.json()["deep_link"].split("?start=", 1)[1]
    assert second_payload != first_payload

    with factory() as db:
        rows = list(db.scalars(select(MessengerLinkToken).order_by(MessengerLinkToken.created_at)))
        assert len(rows) == 2
        assert rows[0].token_hash == hashlib.sha256(first_payload.encode("ascii")).hexdigest()
        assert rows[1].token_hash == hashlib.sha256(second_payload.encode("ascii")).hexdigest()
        assert first_payload not in {row.token_hash for row in rows}
        now = datetime.now(timezone.utc)
        first_expiry = rows[0].expires_at.replace(tzinfo=timezone.utc) if rows[0].expires_at.tzinfo is None else rows[0].expires_at
        second_expiry = rows[1].expires_at.replace(tzinfo=timezone.utc) if rows[1].expires_at.tzinfo is None else rows[1].expires_at
        assert first_expiry <= now
        assert second_expiry > now


def test_offer_excludes_owned_product_and_checkout_rechecks_server_price():
    client, factory = setup()
    offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-2-offer")
    )
    assert offer.status_code == 200
    data = offer.json()
    assert data["stage"] == "early"
    assert data["expires_at"]
    assert data["offers"][0]["price"] == 2900
    checkout = client.post("/api/masterclass/checkout", json={
        "email": "member@example.test",
        "placement": "day-2-offer",
        "placement_token": placement_token("day-2-offer"),
        "offer_code": data["offers"][0]["code"],
    })
    assert checkout.status_code == 200
    assert checkout.json()["cart_command"].startswith("#order:EB-")
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 1
        assert db.scalar(select(func.count(OfferCheckout.id))) == 1


def test_day_one_offer_shows_early_price_without_starting_countdown():
    client, factory = setup()
    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "early"
    assert response.json()["expires_at"] is None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 0

    triggered = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-2-offer")
    )
    reopened = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    assert triggered.json()["expires_at"] is not None
    assert reopened.json()["expires_at"] is None
    assert reopened.json()["offers"][0]["details"][0]["name"] != reopened.json()["offers"][0]["title"]
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 1

    for later_placement in ("day-17-offer", "day-19-offer", "day-21-offer"):
        later_client, _ = setup()
        later = later_client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(later_placement)
        )
        day_one = later_client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query("day-1-offer")
        )
        assert later.json()["expires_at"] is not None
        assert day_one.json()["expires_at"] is None


def test_every_single_offer_lists_features_instead_of_repeating_its_title():
    def assert_composition(payload):
        single_cards = [
            card for card in payload["offers"] if card["code"].startswith("single:")
        ]
        assert single_cards
        for card in single_cards:
            assert card["details"]
            assert all(detail["name"] != card["title"] for detail in card["details"])

    client, _ = setup()
    standard = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert standard.status_code == 200
    assert_composition(standard.json())

    remaining_client, factory = setup()
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        for code in ("ACCESS_RECIPES", "ACCESS_CALORIES"):
            resource = db.scalar(select(Resource).where(Resource.code == code))
            if resource is None:
                resource = Resource(code=code, name=code, status="active")
                db.add(resource)
                db.flush()
            db.add(UserAccess(
                user_id=user.id,
                resource_id=resource.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            ))
        db.commit()
    remaining = remaining_client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert remaining.status_code == 200
    assert {card["code"] for card in remaining.json()["offers"]} >= {
        "single:training", "single:recordings"
    }
    assert_composition(remaining.json())


def test_offer_placement_cannot_be_forged_by_tilda_client():
    client, factory = setup()
    forged = client.get(
        "/api/masterclass/offers?email=member@example.test&placement=closing-review"
        "&placement_token=" + placement_token("day-2-offer")
    )
    assert forged.status_code == 403

    unknown = client.get(
        "/api/masterclass/offers?email=member@example.test&placement=made-up"
        "&placement_token=" + placement_token("made-up")
    )
    assert unknown.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 0


def test_checkout_rejects_token_from_another_offer_stage():
    client, factory = setup()
    response = client.post("/api/masterclass/checkout", json={
        "email": "member@example.test",
        "placement": "closing-review",
        "placement_token": placement_token("day-2-offer"),
        "offer_code": "single:recipes",
    })
    assert response.status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count(OfferCheckout.id))) == 0


def test_old_tilda_lecture_never_returns_an_earlier_discount_stage():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add_all([
            UserOffer(
                user_id=user.id,
                stage_code="early",
                started_at=now - timedelta(hours=12),
                expires_at=now + timedelta(hours=84),
                snapshot={},
            ),
            UserOffer(
                user_id=user.id,
                stage_code="review",
                started_at=now - timedelta(hours=1),
                expires_at=now + timedelta(hours=71),
                snapshot={},
            ),
        ])
        db.commit()

    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-2-offer")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "review"
    assert response.json()["expires_at"] is not None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "second")) == 0


def test_expired_price_advances_but_next_timer_waits_for_real_checkpoint():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(UserOffer(
            user_id=user.id,
            stage_code="early",
            started_at=now - timedelta(days=5),
            expires_at=now - timedelta(hours=1),
            snapshot={},
        ))
        db.commit()

    passive = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert passive.status_code == 200
    assert passive.json()["stage"] == "second"
    assert passive.json()["expires_at"] is None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "second")) == 0

    checkpoint = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-2-gate")
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["stage"] == "second"
    assert checkpoint.json()["expires_at"] is not None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "second")) == 1


def test_admin_can_generate_signed_tokens_for_tilda_placements():
    client, _ = setup()
    response = client.get("/api/masterclass/admin/embed-tokens")
    assert response.status_code == 200
    placements = response.json()["placements"]
    assert set(placements) >= {
        "day-1-offer",
        "day-2-offer",
        "day-15-offer",
        "day-17-offer",
        "day-19-offer",
        "day-21-offer",
        "recipes-part-1-gate",
        "recipes-part-2-gate",
        "closing-review",
        "offers-hub",
    }
    assert all(len(token) > 20 for token in placements.values())


def test_current_21_day_offer_placements_select_expected_stages():
    expected = {
        "day-1-offer": "early",
        "day-15-offer": "early",
        "day-17-offer": "second",
        "day-19-offer": "review",
        "day-21-offer": "last_week",
    }
    for placement, stage in expected.items():
        client, _ = setup()
        response = client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(placement)
        )
        assert response.status_code == 200
        assert response.json()["stage"] == stage


def test_course_progress_is_server_side_and_steps_are_strictly_sequential():
    client, factory = setup()
    manifest = client.get(
        "/api/masterclass/course/manifest?email=member@example.test"
    )
    assert manifest.status_code == 200
    manifest_data = manifest.json()
    assert len(manifest_data["days"]) == 21
    assert manifest_data["title"] == (
        "Мастер-класс по изменению питания и пищевых привычек"
    )
    assert manifest_data["days"][0]["title"] == "Начинаем с наблюдения"
    durations = [
        step.get("durationMinutes") for step in manifest_data["days"][0]["steps"]
    ]
    assert all(isinstance(minutes, int) and minutes > 0 for minutes in durations)
    day_steps = manifest_data["days"][0]["steps"]
    offer_index = next(
        index for index, step in enumerate(day_steps) if step["id"] == "day-01-offer"
    )
    assert offer_index == len(day_steps) - 1

    state = client.get("/api/masterclass/course?email=member@example.test")
    assert state.status_code == 200
    day = state.json()["days"][0]
    assert day["opened"] is True
    assert day["steps_total"] == len(day_steps)
    assert day["completed_steps"] == []
    assert day["task_unlocked"] is False
    assert day["offer"] is None

    skipped = client.post(
        "/api/masterclass/course/days/1/steps/1/complete",
        json={"email": "member@example.test"},
    )
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["reason"] == "previous_step_not_completed"

    for index in range(offer_index):
        completed = client.post(
            f"/api/masterclass/course/days/1/steps/{index}/complete",
            json={"email": "member@example.test"},
        )
        assert completed.status_code == 200
    before_offer = completed.json()["days"][0]
    assert before_offer["next_step"] == offer_index
    assert before_offer["offer"]["placement"] == "day-1-offer"
    assert len(before_offer["offer"]["placement_token"]) > 20
    assert before_offer["task_unlocked"] is False
    task_before_offer = client.post(
        "/api/masterclass/course/days/1/task/open",
        json={"email": "member@example.test"},
    )
    assert task_before_offer.status_code == 409
    assert task_before_offer.json()["detail"]["reason"] == "materials_not_completed"

    offer = client.post(
        f"/api/masterclass/course/days/1/steps/{offer_index}/complete",
        json={"email": "member@example.test"},
    )
    assert offer.status_code == 200
    assert offer.json()["days"][0]["task_unlocked"] is True
    assert client.post(
        "/api/masterclass/course/days/1/task/open",
        json={"email": "member@example.test"},
    ).status_code == 200

    for index in range(4):
        checked = client.put(
            f"/api/masterclass/course/days/1/checks/{index}",
            json={"email": "member@example.test", "checked": True},
        )
        assert checked.status_code == 200
    assert checked.json()["days"][0]["completed"] is True

    too_early = client.post(
        "/api/masterclass/course/days/2/open",
        json={"email": "member@example.test"},
    )
    assert too_early.status_code == 409
    assert too_early.json()["detail"]["reason"] == "timer"

    with factory() as db:
        progress = db.scalar(
            select(MasterclassDayProgress).where(
                MasterclassDayProgress.day_number == 1
            )
        )
        progress.first_opened_at = datetime.now(timezone.utc) - timedelta(days=2)
        progress.completed_at = datetime.now(timezone.utc) - timedelta(days=2)
        db.commit()
    opened = client.post(
        "/api/masterclass/course/days/2/open",
        json={"email": "member@example.test"},
    )
    assert opened.status_code == 200
    assert opened.json()["days"][1]["opened"] is True

    repeated = client.post(
        "/api/masterclass/course/days/2/open",
        json={"email": "member@example.test"},
    )
    assert repeated.status_code == 200
    with factory() as db:
        stalled = list(db.scalars(
            select(MasterclassNotification).where(
                MasterclassNotification.notification_kind == "course_stalled_72h"
            )
        ))
        assert stalled
        assert all(row.content_code == "tpl_postpurchase_tempo_late" for row in stalled)
        assert db.scalar(
            select(func.count(MasterclassEvent.id)).where(
                MasterclassEvent.event_key == "course:day:2:opened"
            )
        ) == 1


def test_course_api_uses_tilda_email_but_still_requires_server_access():
    client, _ = setup(authenticated=False)
    opened = client.get(
        "/api/masterclass/course?email=member@example.test",
        headers={},
    )
    assert opened.status_code == 200
    denied = client.get(
        "/api/masterclass/course?email=other@example.test"
    )
    assert denied.status_code == 403


def test_admin_can_enable_isolated_accelerated_course_profile():
    client, _ = setup()
    enabled = client.put(
        "/api/masterclass/admin/test-profile",
        json={
            "email": "member@example.test",
            "enabled": True,
            "day_interval_seconds": 20,
            "notification_delay_seconds": 10,
        },
    )
    assert enabled.status_code == 200
    state = client.get("/api/masterclass/course?email=member@example.test")
    assert state.status_code == 200
    payload = state.json()
    opened = datetime.fromisoformat(payload["days"][0]["first_opened_at"])
    unlock = datetime.fromisoformat(payload["days"][0]["next_day_unlock_at"])
    assert payload["accelerated_test"] is True
    assert (unlock - opened).total_seconds() == 20


def test_closing_review_queues_three_review_week_messages_once():
    client, factory = setup()
    enabled = client.put(
        "/api/masterclass/admin/test-profile",
        json={
            "email": "member@example.test",
            "enabled": True,
            "day_interval_seconds": 20,
            "notification_delay_seconds": 10,
        },
    )
    assert enabled.status_code == 200
    first = client.get("/api/masterclass/questionnaires/closing-review?email=member@example.test")
    second = client.get("/api/masterclass/questionnaires/closing-review?email=member@example.test")
    assert first.status_code == second.status_code == 200
    with factory() as db:
        rows = list(db.scalars(
            select(MasterclassNotification)
            .where(MasterclassNotification.notification_kind.like("post_review_day_%"))
            .order_by(MasterclassNotification.due_at)
        ))
        assert [row.notification_kind for row in rows] == [
            "post_review_day_2", "post_review_day_4", "post_review_day_7"
        ]
        assert [row.content_code for row in rows] == [
            "tpl_postpurchase_review_week_1",
            "tpl_postpurchase_review_week_2",
            "tpl_postpurchase_review_week_3",
        ]
        assert [row.payload["day"] for row in rows] == [2, 4, 7]


def test_course_content_uses_the_same_member_session():
    client, _ = setup()
    imported = client.get(
        "/api/masterclass/course/content/extracted-2026-08-23.json"
        "?email=member@example.test"
    )
    assert imported.status_code == 200
    assert imported.json()["pages"]
    response = client.get(
        "/api/masterclass/course/content/40-introduction-to-satiety-habits.md"
        "?email=member@example.test"
    )
    assert response.status_code == 200
    assert "пищев" in response.text.lower()
    assert response.headers["cache-control"] == "private, max-age=300"
    assert client.get(
        "/api/masterclass/course/content/not-allowed.txt?email=member@example.test"
    ).status_code == 404


def test_recipe_gate_uses_access_and_records_open_once():
    client, factory = setup()
    denied = client.get(
        "/api/masterclass/gate/1?email=member@example.test&placement_token="
        + placement_token("recipes-part-1-gate")
    ).json()
    assert denied["allowed"] is False
    assert denied["state"] == "offer"
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        recipes = db.scalar(select(Resource).where(Resource.code == "ACCESS_RECIPES"))
        db.add(UserAccess(user_id=user.id, resource_id=recipes.id, source="test", granted_at=datetime.now(timezone.utc)))
        db.commit()
    allowed = client.get(
        "/api/masterclass/gate/1?email=member@example.test&placement_token="
        + placement_token("recipes-part-1-gate")
    ).json()
    assert allowed["allowed"] is True
    assert allowed["state"] == "content"
    assert allowed["title"] == "Рецепты · часть 1"
    with factory() as db:
        assert db.scalar(select(func.count(MasterclassEvent.id)).where(
            MasterclassEvent.event_type == "recipes_part_1_opened"
        )) == 1
        assert db.scalar(select(func.count(MasterclassNotification.id)).where(
            MasterclassNotification.notification_kind == "recipes_followup"
        )) == 0
        assert db.scalar(select(func.count(MasterclassNotification.id)).where(
            MasterclassNotification.notification_kind == "sales_last_chance_due"
        )) == 1
    queue = client.get("/api/masterclass/admin/notifications")
    assert queue.status_code == 200
    assert queue.json()["notifications"][0]["kind"] == "sales_last_chance_due"


def test_admin_preview_lists_only_masterclass_users_with_primary_email():
    client, _ = setup()
    response = client.get("/api/masterclass/admin/users")
    assert response.status_code == 200
    assert response.json()["users"] == [{
        "id": response.json()["users"][0]["id"],
        "display_name": "Участник",
        "email": "member@example.test",
    }]


def test_consultation_is_only_shown_in_review_or_permanent_offer_placements():
    client, factory = setup()
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        now = datetime.now(timezone.utc)
        db.add(UserOffer(user_id=user.id, stage_code="second", started_at=now - timedelta(days=4), expires_at=now - timedelta(hours=1), snapshot={}))
        db.commit()

    recipe_offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-2-gate")
    ).json()
    assert recipe_offer["stage"] == "review"
    assert all(card["code"] != "single:consultation" for card in recipe_offer["offers"])

    review_offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("closing-review")
    ).json()
    assert any(card["code"] == "single:consultation" for card in review_offer["offers"])
    assert review_offer["offers"][1]["code"] == "bundle:consultation"
    assert "consultation" in review_offer["offers"][1]["items"]


def test_offers_hub_shows_next_price_without_starting_final_week_timer():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        review = UserOffer(
            user_id=user.id,
            stage_code="review",
            started_at=now - timedelta(hours=80),
            expires_at=now - timedelta(hours=8),
            snapshot={},
        )
        db.add(review)
        db.commit()
    passive = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert passive.status_code == 200
    assert passive.json()["stage"] == "last_week"
    assert passive.json()["expires_at"] is None
    assert [card["code"] for card in passive.json()["offers"]] == [
        "single:consultation",
        "bundle:digital",
        "single:recipes",
    ]
    with factory() as db:
        assert db.scalar(
            select(func.count(UserOffer.id)).where(UserOffer.stage_code == "last_week")
        ) == 0

    checkpoint = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-21-offer")
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["stage"] == "last_week"
    assert checkpoint.json()["expires_at"] is not None
    with factory() as db:
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert final is not None
        assert final.started_at.replace(tzinfo=timezone.utc) > now - timedelta(minutes=1)
        due = db.scalar(select(MasterclassNotification).where(
            MasterclassNotification.notification_kind == "sales_last_chance_due"
        ))
        assert due is not None
        assert due.payload["stage"] == "last_week"


def test_offers_hub_does_not_resurrect_final_discount_after_week_has_elapsed():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add_all([
            UserOffer(
                user_id=user.id,
                stage_code="review",
                started_at=now - timedelta(days=12),
                expires_at=now - timedelta(days=9),
                snapshot={},
            ),
            UserOffer(
                user_id=user.id,
                stage_code="last_week",
                started_at=now - timedelta(days=9),
                expires_at=now - timedelta(days=2),
                snapshot={},
            ),
        ])
        db.commit()

    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "standard"
    assert response.json()["expires_at"] is None
    assert len(response.json()["offers"]) == 3
    assert all(card["code"].startswith("single:") for card in response.json()["offers"])
    assert all(card["price"] == card["standard_price"] for card in response.json()["offers"])
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "last_week")) == 1


def test_admin_lists_personal_offer_window_with_effective_expired_status():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(UserOffer(
            user_id=user.id,
            stage_code="early",
            started_at=now - timedelta(days=5),
            expires_at=now - timedelta(days=1),
            status="active",
            snapshot={},
        ))
        db.commit()

    response = client.get("/api/masterclass/admin/user-offers")
    assert response.status_code == 200
    assert response.json()["offers"][0]["email"] == "member@example.test"
    assert response.json()["offers"][0]["stage_code"] == "early"
    assert response.json()["offers"][0]["status"] == "expired"


def test_crm_card_contains_masterclass_answers_events_and_offer_windows():
    client, factory = setup()
    payload = {
        "email": "member@example.test",
        "question_code": "main_request",
        "answer_text": "Хочу выстроить питание",
    }
    assert client.put("/api/masterclass/questionnaires/onboarding/answer", json=payload).status_code == 200
    assert client.get(
        "/api/masterclass/gate/1?email=member@example.test&placement_token="
        + placement_token("recipes-part-1-gate")
    ).status_code == 200
    with factory() as db:
        user_id = db.scalar(select(User.id).where(User.display_name == "Участник"))

    response = client.get(f"/admin/api/users/{user_id}")
    assert response.status_code == 200
    data = response.json()["masterclass"]
    assert data["questionnaires"][0]["answers"][0]["title"] == "Главный запрос"
    assert data["questionnaires"][0]["answers"][0]["answer"] == "Хочу выстроить питание"
    assert data["events"][0]["type"] == "recipes_part_1_opened"
    assert data["offers"][0]["stage"] == "early"
