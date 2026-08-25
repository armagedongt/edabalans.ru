import os
import hashlib
import json
import re
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
from app.app_auth import create_placement_token  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.legal_service import LEGAL_DOCUMENTS  # noqa: E402
from app.masterclass_offer_catalog import OFFER_PRODUCTS  # noqa: E402
from app.masterclass_routes import course_required_step_indexes  # noqa: E402
from app.models import (  # noqa: E402
    MasterclassDayProgress, MasterclassEvent, MasterclassNotification,
    MessengerAccount, MessengerLinkToken, OfferCheckout, OfferStage, Payment, Product,
    QuestionnaireAnswer, Resource, User, UserAccess, UserEmail,
    UserLegalAcceptance, UserOffer,
)
from scripts.generate_masterclass_offer_simulator import (  # noqa: E402
    course_offer_scenarios,
    render_simulator,
)


TEST_SETTINGS = Settings(
    database_url="sqlite+pysqlite:///:memory:",
    admin_password="test-app-secret",
    app_auth_secret="test-client-session-secret",
    telegram_test_bot_username="EdabalansTestBot",
)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def test_optional_course_steps_do_not_block_required_progression():
    assert course_required_step_indexes(7) == [0, 1]
    assert course_required_step_indexes(8) == [0]
    assert course_required_step_indexes(15) == [0, 1, 3]
    assert course_required_step_indexes(16) == [0]


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


def test_offer_window_migration_changes_only_future_early_duration():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260825_0023_masterclass_offer_windows.py"
    ).read_text(encoding="utf-8")
    assert "SET duration_hours = 72" in migration
    assert "duration_hours = 96" in migration
    assert "UPDATE user_offers" not in migration


def setup():
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
        product = Product(code="MASTERCLASS_RECIPES", name="Мастер-класс · Стандартный", status="active")
        db.add(product); db.flush()
        db.add(Payment(
            user_id=user.id,
            product_id=product.id,
            source="test",
            external_order_id="test-masterclass-order",
            email_at_purchase="member@example.test",
            product_name_raw="Сырой параметр оплаты",
            currency="RUB",
            payment_status="paid",
            paid_at=datetime.now(timezone.utc),
        ))
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
            ("early", 72, {"single": 2900, "bundle": {"4": 7900}}),
            ("second", 72, {"single": 3300, "bundle": {"4": 9900}}),
            ("review", 72, {"single": 3500, "consultation": 7500, "bundle": {"4": 11300}}),
            ("last_week", 168, {"single": 3800, "consultation": 8400, "bundle": {"4": 13800}}),
            ("standard", None, {"single": 3900, "consultation": 8900, "bundle": {"4": 15600}}),
        ]
        for code, hours, pricing in stages: db.add(OfferStage(code=code, name=code, duration_hours=hours, pricing=pricing, status="active"))
        db.commit()
    return TestClient(app), factory


def test_masterclass_personal_data_uses_tilda_email_and_server_access():
    client, _ = setup()
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
    status = client.get(
        "/api/masterclass/messenger-links/status?email=member@example.test&platform=telegram"
    )
    assert status.status_code == 200
    assert status.json()["linked"] is False
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
        user_id = db.scalar(select(User.id))
        db.add(MessengerAccount(
            user_id=user_id,
            platform="telegram",
            platform_user_id="42",
            username="member",
            linked_at=now,
            source="test",
        ))
        db.commit()

    linked = client.get(
        "/api/masterclass/messenger-links/status?email=member@example.test&platform=telegram"
    )
    assert linked.status_code == 200
    assert linked.json()["linked"] is True
    assert "username" not in linked.json()


def test_offer_excludes_owned_product_and_checkout_rechecks_server_price():
    client, factory = setup()
    offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-1-gate")
    )
    assert offer.status_code == 200
    data = offer.json()
    assert data["stage"] == "early"
    assert data["expires_at"]
    assert data["offers"][0]["price"] == 2900
    checkout = client.post("/api/masterclass/checkout", json={
        "email": "member@example.test",
        "placement": "recipes-part-1-gate",
        "placement_token": placement_token("recipes-part-1-gate"),
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
        + placement_query("recipes-part-1-gate")
    )
    reopened = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    assert triggered.json()["expires_at"] is not None
    assert reopened.json()["expires_at"] is None
    assert reopened.json()["offers"][0]["composition"] == "single"
    assert reopened.json()["offers"][0]["details"] == []
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 1

    for later_placement in ("recipes-part-2-gate", "day-19-offer"):
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


def test_single_offers_stay_concise_and_bundles_list_their_products():
    def assert_composition(payload):
        single_cards = [
            card for card in payload["offers"] if card["code"].startswith("single:")
        ]
        assert single_cards
        for card in single_cards:
            assert card["composition"] == "single"
            assert card["details"] == []

        for card in payload["offers"]:
            if card["code"].startswith("bundle:"):
                assert card["composition"] == "bundle"
                assert card["details"]

    client, _ = setup()
    standard = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert standard.status_code == 200
    assert_composition(standard.json())

    early = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    bundle = next(
        card for card in early.json()["offers"]
        if card["code"] == "bundle:digital"
    )
    assert bundle["composition"] == "bundle"
    assert bundle["details"]

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
    owned_names = {
        product["name"] for product in remaining.json()["owned_products"]
    }
    assert "Мастер-класс по изменению питания и пищевых привычек" in owned_names
    assert "Система рецептов" in owned_names
    assert "Мини-курс «Калорийный»" in owned_names


def test_bundle_rows_use_the_same_catalog_fields_as_single_cards():
    client, _ = setup()
    early = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    ).json()
    digital_bundle = next(
        card for card in early["offers"] if card["code"] == "bundle:digital"
    )
    assert digital_bundle["details"] == [
        {
            "name": OFFER_PRODUCTS[code]["name"],
            "description": OFFER_PRODUCTS[code]["description"],
        }
        for code in digital_bundle["items"]
    ]

    review = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    ).json()
    consultation_bundle = next(
        card for card in review["offers"] if card["code"] == "bundle:consultation"
    )
    assert consultation_bundle["details"] == [
        {
            "name": OFFER_PRODUCTS[code]["name"],
            "description": OFFER_PRODUCTS[code]["description"],
        }
        for code in consultation_bundle["items"]
    ]

    single_cards = [
        *[card for card in early["offers"] if card["composition"] == "single"],
        *[card for card in review["offers"] if card["composition"] == "single"],
    ]
    assert single_cards
    for card in single_cards:
        code = card["items"][0]
        assert card["title"] == OFFER_PRODUCTS[code]["name"]
        assert card["description"] == OFFER_PRODUCTS[code]["description"]
        assert card["long_description"] == OFFER_PRODUCTS[code]["long_description"]


def test_offer_product_catalog_has_one_complete_card_contract():
    required_fields = {
        "name",
        "description",
        "long_description",
        "resource",
        "standard",
        "status",
        "features",
    }
    assert OFFER_PRODUCTS
    assert all(set(product) == required_fields for product in OFFER_PRODUCTS.values())
    assert all(product["name"] for product in OFFER_PRODUCTS.values())
    assert all(product["description"] for product in OFFER_PRODUCTS.values())
    assert all(product["resource"] for product in OFFER_PRODUCTS.values())
    assert all(product["standard"] > 0 for product in OFFER_PRODUCTS.values())


def test_offer_simulator_is_generated_from_runtime_css_and_product_catalog():
    rendered = render_simulator()
    runtime_css = (
        Path(__file__).parents[1] / "app" / "static" / "masterclass.css"
    ).read_text(encoding="utf-8")
    runtime_js = (
        Path(__file__).parents[1] / "app" / "static" / "masterclass.js"
    ).read_text(encoding="utf-8")
    assert runtime_css in rendered
    assert runtime_js in rendered
    assert "class=\"mc-offer-card\"" in rendered
    assert "__COURSE_CSS__" not in rendered
    assert "__COURSE_JS__" not in rendered
    assert "__PRODUCTS_JSON__" not in rendered
    catalog_json = json.dumps(
        OFFER_PRODUCTS, ensure_ascii=False, separators=(",", ":")
    )
    assert rendered.count(catalog_json) == 1
    assert "/api/masterclass/admin/offer-preview" in rendered
    assert "EdabalansMasterclassOfferView.markup(data)" in rendered


def test_offer_simulator_lists_every_current_course_checkpoint_in_order():
    manifest = json.loads(
        (
            Path(__file__).parents[2]
            / "content"
            / "masterclass"
            / "course"
            / "course.json"
        ).read_text(encoding="utf-8")
    )
    checkpoints = [
        (day["number"], step["placement"], step["event"])
        for day in manifest["days"]
        for step in day["steps"]
        if step["kind"] == "offer"
    ]
    assert checkpoints == [
        (1, "day-1-offer", "day_1_offer_opened"),
        (6, "recipes-part-1-gate", "recipes_part_1_offer_opened"),
        (7, "recipes-part-1-gate", "recipes_part_1_offer_reopened"),
        (8, "recipes-part-1-gate", "recipes_part_1_last_day_opened"),
        (14, "recipes-part-2-gate", "recipes_part_2_offer_opened"),
        (15, "recipes-part-2-gate", "recipes_part_2_offer_reopened"),
        (16, "recipes-part-2-gate", "recipes_part_2_last_day_opened"),
        (19, "day-19-offer", "day_19_offer_opened"),
        (21, "day-21-offer", "day_21_offer_opened"),
    ]
    rendered = render_simulator()
    for _, placement, event in checkpoints:
        assert placement in rendered
    for event in {
        "day_1_offer_opened", "day_19_offer_opened", "day_21_offer_opened",
    }:
        assert event in rendered
    scenarios = course_offer_scenarios()
    assert list(scenarios) == [
        "day1", "day6", "day7", "day8", "day14", "day15", "day16",
        "day19", "day21Review", "day21LastWeek", "standard",
    ]
    for day_number, placement, event in checkpoints:
        matching = [
            item for item in scenarios.values()
            if item["placement"] == placement and item["event"] == event
        ]
        assert matching, f"day {day_number} is absent from simulator scenarios"
    assert 'const stages={"day1"' in rendered


def test_admin_offer_preview_uses_production_offer_builder() -> None:
    client, _ = setup()
    response = client.post(
        "/api/masterclass/admin/offer-preview",
        json={
            "stage_code": "early",
            "placement": "recipes-part-1-gate",
            "owned_product_codes": ["recipes"],
            "tariff_name": "С рецептами",
            "remaining_hours": 48,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "early"
    assert payload["owned_products"][0]["tariff"] == "С рецептами"
    assert payload["owned_products"][1]["code"] == "recipes"
    assert payload["offers"][0]["code"] == "single:calories"
    assert payload["offers"][1]["code"] == "bundle:digital"
    assert payload["expires_at"] is not None


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


def test_recipe_windows_start_once_and_repeat_without_moving_due_time():
    client, factory = setup()
    for placement, stage_code in (
        ("recipes-part-1-gate", "early"),
        ("recipes-part-2-gate", "second"),
    ):
        first = client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(placement)
        )
        assert first.status_code == 200
        with factory() as db:
            window = db.scalar(
                select(UserOffer).where(UserOffer.stage_code == stage_code)
            )
            due = db.scalar(
                select(MasterclassNotification)
                .join(MasterclassEvent, MasterclassEvent.id == MasterclassNotification.event_id)
                .where(
                    MasterclassNotification.notification_kind == "sales_last_chance_due",
                    MasterclassEvent.event_key == f"offer:{stage_code}:started",
                )
            )
            original = (aware(window.started_at), aware(window.expires_at), aware(due.due_at))
            assert original[1] - original[0] == timedelta(hours=72)
            assert original[1] - original[2] == timedelta(hours=24)

        repeated = client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(placement)
        )
        assert repeated.status_code == 200
        with factory() as db:
            window = db.scalar(
                select(UserOffer).where(UserOffer.stage_code == stage_code)
            )
            due = db.scalar(
                select(MasterclassNotification)
                .join(MasterclassEvent, MasterclassEvent.id == MasterclassNotification.event_id)
                .where(
                    MasterclassNotification.notification_kind == "sales_last_chance_due",
                    MasterclassEvent.event_key == f"offer:{stage_code}:started",
                )
            )
            assert (aware(window.started_at), aware(window.expires_at), aware(due.due_at)) == original
            assert db.scalar(
                select(func.count(UserOffer.id)).where(UserOffer.stage_code == stage_code)
            ) == 1


def test_late_repeat_uses_the_original_course_checkpoint_time():
    client, factory = setup()
    opened_at = datetime.now(timezone.utc) - timedelta(hours=24)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(MasterclassEvent(
            user_id=user.id,
            event_key="course:day:6:step:2:completed",
            event_type="recipes_part_1_offer_opened",
            placement="recipes-part-1-gate",
            occurred_at=opened_at,
            details={"day": 6, "step_index": 2},
        ))
        db.commit()

    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-1-gate")
    )
    assert response.status_code == 200
    with factory() as db:
        window = db.scalar(select(UserOffer).where(UserOffer.stage_code == "early"))
        assert abs((aware(window.started_at) - opened_at).total_seconds()) < 1
        assert aware(window.expires_at) == aware(window.started_at) + timedelta(hours=72)


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


def test_admin_offer_stages_explain_the_runtime_window_rules():
    client, _ = setup()
    response = client.get("/api/masterclass/admin/offer-stages")
    assert response.status_code == 200
    rules = {row["code"]: row["runtime_rule"] for row in response.json()["stages"]}
    assert "День 6" in rules["early"] and "дни 7–8" in rules["early"]
    assert "День 14" in rules["second"] and "дни 15–16" in rules["second"]
    assert "review.expires_at" in rules["last_week"]
    assert "день 21" in rules["last_week"]

    rejected = client.put("/api/masterclass/admin/offer-stages/early", json={
        "duration_hours": 96,
        "single": 2900,
        "consultation": None,
        "bundle": {"1": 1900, "2": 3900, "3": 5900, "4": 7900},
    })
    assert rejected.status_code == 422


def test_current_21_day_offer_placements_select_expected_stages():
    expected = {
        "day-1-offer": "early",
        "recipes-part-1-gate": "early",
        "recipes-part-2-gate": "second",
        "day-19-offer": "review",
        "day-21-offer": "standard",
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

    account = client.get("/api/account?email=member@example.test")
    assert account.status_code == 200
    assert account.json()["courses"][0]["tariff"] == "Стандартный"
    assert account.json()["purchased_products"][0]["product_code"] == "MASTERCLASS_RECIPES"

    state = client.get("/api/masterclass/course?email=member@example.test")
    assert state.status_code == 200
    assert state.json()["masterclass_tariff"] == "Стандартный"
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

    with factory() as db:
        reminder = db.scalar(select(MasterclassNotification).where(
            MasterclassNotification.notification_kind == "course_day_unopened_18h"
        ))
        assert reminder is not None
        assert reminder.payload["day"] == 2
        assert reminder.payload["day_title"]

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
        pending_stall = next(row for row in stalled if row.status == "pending")
        due = pending_stall.due_at.replace(tzinfo=timezone.utc) if pending_stall.due_at.tzinfo is None else pending_stall.due_at
        assert timedelta(hours=71, minutes=59) < due - datetime.now(timezone.utc) <= timedelta(hours=72)
        assert db.scalar(
            select(func.count(MasterclassEvent.id)).where(
                MasterclassEvent.event_key == "course:day:2:opened"
            )
        ) == 1


def test_course_api_uses_tilda_email_but_still_requires_server_access():
    client, factory = setup()
    opened = client.get(
        "/api/masterclass/course?email=member@example.test",
        headers={},
    )
    assert opened.status_code == 200
    with factory() as db:
        without_access = User(display_name="Участник без покупки", status="active")
        db.add(without_access)
        db.flush()
        db.add(UserEmail(
            user_id=without_access.id,
            email_original="known-without-access@example.test",
            email_normalized="known-without-access@example.test",
            is_primary=True,
            source="test",
        ))
        db.add_all([
            UserLegalAcceptance(
                user_id=without_access.id,
                document_code=item["code"],
                document_version=item["version"],
                source="test",
            )
            for item in LEGAL_DOCUMENTS
        ])
        db.commit()
    denied = client.get(
        "/api/masterclass/course?email=known-without-access@example.test"
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
        "/api/masterclass/course/content/31-satiety-habits.txt"
        "?email=member@example.test"
    )
    assert response.status_code == 200
    assert response.text.strip()
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


def test_review_expiry_automatically_starts_final_week_before_day_21():
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
    assert passive.json()["expires_at"] is not None
    assert [card["code"] for card in passive.json()["offers"]] == [
        "single:consultation",
        "bundle:digital",
        "single:recipes",
    ]
    with factory() as db:
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert final is not None
        final_started = aware(final.started_at)
        final_expires = aware(final.expires_at)
        assert final_started == aware(review.expires_at)
        assert final_expires - final_started == timedelta(hours=168)
        original_times = (final_started, final_expires)

    checkpoint = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-21-offer")
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["stage"] == "last_week"
    assert checkpoint.json()["expires_at"] is not None
    with factory() as db:
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert (aware(final.started_at), aware(final.expires_at)) == original_times
        due = db.scalar(select(MasterclassNotification).where(
            MasterclassNotification.notification_kind == "sales_last_chance_due"
        ))
        assert due is not None
        assert due.payload["stage"] == "last_week"


def test_day_19_fixes_review_and_last_week_timeline_once():
    client, factory = setup()
    first = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    )
    repeated = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    )
    assert first.status_code == repeated.status_code == 200
    with factory() as db:
        review = db.scalar(select(UserOffer).where(UserOffer.stage_code == "review"))
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert aware(review.expires_at) - aware(review.started_at) == timedelta(hours=72)
        assert aware(final.started_at) == aware(review.expires_at)
        assert aware(final.expires_at) - aware(final.started_at) == timedelta(days=7)
        assert db.scalar(select(func.count(UserOffer.id))) == 2
        assert db.scalar(
            select(func.count(MasterclassNotification.id)).where(
                MasterclassNotification.notification_kind == "sales_last_chance_due"
            )
        ) == 2


def test_day_21_during_review_only_shows_its_existing_remainder():
    client, factory = setup()
    started = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    )
    assert started.status_code == 200
    with factory() as db:
        review = db.scalar(select(UserOffer).where(UserOffer.stage_code == "review"))
        original = (aware(review.started_at), aware(review.expires_at))

    day_21 = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-21-offer")
    )
    assert day_21.status_code == 200
    assert day_21.json()["stage"] == "review"
    assert datetime.fromisoformat(day_21.json()["expires_at"]) == original[1]
    with factory() as db:
        review = db.scalar(select(UserOffer).where(UserOffer.stage_code == "review"))
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert (aware(review.started_at), aware(review.expires_at)) == original
        assert aware(final.started_at) == original[1]
        assert db.scalar(select(func.count(UserOffer.id))) == 2


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
