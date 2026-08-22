import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.auth import require_admin  # noqa: E402
from app.app_auth import create_app_session, create_placement_token  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    MasterclassEvent, MasterclassNotification, OfferCheckout, OfferStage, QuestionnaireAnswer, Resource,
    User, UserAccess, UserEmail, UserOffer,
)


TEST_SETTINGS = Settings(
    database_url="sqlite+pysqlite:///:memory:",
    admin_password="test-app-secret",
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


def test_masterclass_personal_data_requires_confirmed_email_session():
    client, _ = setup(authenticated=False)
    response = client.get(
        "/api/masterclass/questionnaires/onboarding?email=member@example.test"
    )
    assert response.status_code == 401


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


def test_admin_can_generate_signed_tokens_for_tilda_placements():
    client, _ = setup()
    response = client.get("/api/masterclass/admin/embed-tokens")
    assert response.status_code == 200
    placements = response.json()["placements"]
    assert set(placements) >= {
        "day-2-offer",
        "recipes-part-1-gate",
        "recipes-part-2-gate",
        "closing-review",
        "offers-hub",
    }
    assert all(len(token) > 20 for token in placements.values())


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
    assert allowed["state"] == "technical_error"
    assert allowed["contact"] == "@FitnessSergey"
    with factory() as db:
        assert db.scalar(select(func.count(MasterclassEvent.id))) == 1
        assert db.scalar(select(func.count(MasterclassNotification.id))) == 1
    queue = client.get("/api/masterclass/admin/notifications")
    assert queue.status_code == 200
    assert queue.json()["notifications"][0]["email"] == "member@example.test"


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


def test_offers_hub_starts_final_week_from_review_expiry_without_extending_it():
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
        expected_start = review.expires_at

    first = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert first.status_code == 200
    assert first.json()["stage"] == "last_week"

    with factory() as db:
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert final is not None
        assert final.started_at.replace(tzinfo=timezone.utc) == expected_start
        first_expiry = final.expires_at

    second = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert second.status_code == 200
    assert second.json()["stage"] == "last_week"
    with factory() as db:
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert final.expires_at == first_expiry


def test_offers_hub_does_not_resurrect_final_discount_after_week_has_elapsed():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(UserOffer(
            user_id=user.id,
            stage_code="review",
            started_at=now - timedelta(days=12),
            expires_at=now - timedelta(days=9),
            snapshot={},
        ))
        db.commit()

    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "standard"
    assert response.json()["expires_at"] is None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "last_week")) == 0


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
