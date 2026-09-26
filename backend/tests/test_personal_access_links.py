import os
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.auth import require_admin  # noqa: E402
from app.access_routes import account_applications  # noqa: E402
from app.account_security import password_hash  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    OfferCheckout,
    PersonalAccessLink,
    Resource,
    User,
    UserAccess,
    UserCoursePolicy,
    UserEmail,
    UserLegalAcceptance, AccountCredential,
    MasterclassEvent,
)

def setup():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        admin_username="admin@example.com",
        admin_password="test-admin-password",
        app_auth_secret="test-client-session-secret",
        smtp_host="smtp.example.test",
        smtp_from_email="noreply@example.test",
        account_public_url="https://example.test/lk",
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    # These tests exercise the temporary legacy email-bound adapter. The root
    # domain is covered by test_account_password_auth and requires a native
    # authenticated session.
    client = TestClient(app, base_url="https://app.edabalans.ru")
    with factory() as db:
        user = User(
            display_name="Исторический клиент",
            status="active",
            access_review_status="pending",
            access_review_note="Историческая покупка требует решения Сергея",
        )
        other = User(display_name="Другой", status="active")
        db.add_all([user, other])
        db.flush()
        db.add_all([
            UserEmail(user_id=user.id, email_original="client@example.test", email_normalized="client@example.test", is_primary=True, source="test"),
            UserEmail(user_id=other.id, email_original="other@example.test", email_normalized="other@example.test", is_primary=True, source="test"),
            Resource(code="ACCESS_MASTERCLASS", name="Новый Мастер-класс", status="active"),
            Resource(code="ACCESS_CALORIES", name="Курс о калориях", status="active"),
            Resource(code="dqs", name="DQS", status="active"),
            Resource(code="ACCESS_MASTERCLASS_LEGACY", name="Старый мастер-класс", status="active"),
            AccountCredential(user_id=user.id, password_hash=password_hash("Test-Password-9", "test-client-session-secret"), password_version=1, issued_via="test"),
            AccountCredential(user_id=other.id, password_hash=password_hash("Test-Password-9", "test-client-session-secret"), password_version=1, issued_via="test"),
        ])
        db.commit()
        user_id = user.id
    return client, factory, user_id


def teardown_function() -> None:
    app.dependency_overrides.clear()


def login_user(client, email):
    response = client.post("/api/account-auth/login", json={"email": email, "password": "Test-Password-9"})
    assert response.status_code == 200, response.text


def test_free_personal_link_is_bound_to_tilda_email_and_grants_once():
    client, factory, user_id = setup()
    created = client.post(
        f"/admin/api/users/{user_id}/personal-access-links",
        json={
            "resource_codes": ["ACCESS_MASTERCLASS", "ACCESS_CALORIES"],
            "final_amount": 0,
            "standard_amount": 10800,
            "expires_days": 14,
            "fully_unlocked": True,
        },
    )
    assert created.status_code == 200
    token = parse_qs(urlparse(created.json()["url"]).query)["access_token"][0]

    login_user(client, "other@example.test")
    wrong = client.get(f"/api/access-links/{token}")
    assert wrong.status_code == 403
    login_user(client, "client@example.test")
    opened = client.get(f"/api/access-links/{token}")
    assert opened.status_code == 200
    assert opened.json()["email"] == "client@example.test"
    assert opened.json()["mode"] == "free"

    first = client.post(
        f"/api/access-links/{token}/claim", json={"email": "client@example.test"}
    )
    second = client.post(
        f"/api/access-links/{token}/claim", json={"email": "client@example.test"}
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "claimed"
    with factory() as db:
        assert db.scalar(select(func.count(UserAccess.id))) == 2
        assert db.scalar(select(func.count(UserCoursePolicy.id))) == 2
        assert set(db.scalars(select(UserCoursePolicy.unlock_mode))) == {"fully_unlocked"}
        user = db.get(User, user_id)
        assert user.access_review_status == "completed"
        assert db.scalar(select(PersonalAccessLink.status)) == "claimed"
    app.dependency_overrides.clear()


def test_paid_personal_link_uses_shared_short_checkout_reference():
    client, factory, user_id = setup()
    created = client.post(
        f"/admin/api/users/{user_id}/personal-access-links",
        json={
            "resource_codes": ["ACCESS_MASTERCLASS"],
            "final_amount": 1500,
            "standard_amount": 6900,
            "expires_days": 14,
        },
    )
    assert created.status_code == 200
    token = parse_qs(urlparse(created.json()["url"]).query)["access_token"][0]
    login_user(client, "client@example.test")

    response = client.post(
        f"/api/access-links/{token}/checkout",
        json={"email": "client@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["cart_command"].startswith(
        "#order:Персональное предложение · №"
    )
    assert "EB-" not in response.json()["cart_command"]
    with factory() as db:
        assert db.scalar(select(func.count(OfferCheckout.id))) == 1
    app.dependency_overrides.clear()


def test_paid_personal_offer_keeps_email_until_payment_and_uses_direct_url():
    client, factory, _ = setup()

    created = client.post(
        "/admin/api/personal-access-links",
        json={
            "email": "new-client@example.test",
            "resource_codes": ["ACCESS_MASTERCLASS", "ACCESS_CALORIES"],
            "resource_settings": [
                {"resource_code": "ACCESS_MASTERCLASS", "start_open": True, "all_lessons_open": False},
                {"resource_code": "ACCESS_CALORIES", "start_open": False, "all_lessons_open": False},
            ],
            "standard_amount": 10800,
            "final_amount": 6900,
            "expires_days": 14,
        },
    )

    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["url"].startswith("https://edabalans.ru/access-links/")
    assert "new-client@example.test" not in payload["telegram_text"]
    with factory() as db:
        assert db.scalar(select(func.count(User.id))) == 2
        link = db.scalar(select(PersonalAccessLink))
        assert link is not None
        assert link.user_id is None
        assert link.target_email_normalized == "new-client@example.test"
        assert link.start_modes == {"ACCESS_MASTERCLASS": "open", "ACCESS_CALORIES": "auto"}
    app.dependency_overrides.clear()


def test_opening_account_page_moves_waiting_buyer_to_pending_without_granting_access():
    client, factory, user_id = setup()
    with factory() as db:
        user = db.get(User, user_id)
        user.access_review_status = "waiting_registration"
        user.tilda_access_status = "not_checked"
        db.commit()
    response = client.post(
        "/api/access/registration-seen",
        json={"email": "client@example.test"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "review_required"
    with factory() as db:
        user = db.get(User, user_id)
        assert user.access_review_status == "pending"
        assert user.tilda_access_status == "pending"
        assert db.scalar(select(func.count(UserAccess.id))) == 0
    app.dependency_overrides.clear()


def test_universal_account_blocks_review_and_uses_server_resources_for_catalog():
    client, factory, user_id = setup()
    blocked = client.get("/api/account?email=client@example.test")
    assert blocked.status_code == 200
    assert blocked.json()["state"] == "review_required"
    assert len(blocked.json()["courses"]) == 6
    assert all(item["owned"] is False for item in blocked.json()["courses"])
    assert all(item["app"] is None for item in blocked.json()["courses"])
    assert [item["title"] for item in blocked.json()["applications"]] == [
        "Система оценки качества питания",
        "Дневник силовых тренировок",
        "Калькулятор и каталог рецептов",
        "Калькулятор метаболизма",
    ]
    assert blocked.json()["legacy_portal"]["available"] is False

    unknown = client.get("/api/account?email=new@example.test")
    assert unknown.status_code == 200
    assert unknown.json()["state"] == "review_required"
    assert len(unknown.json()["courses"]) == 6
    assert len(unknown.json()["applications"]) == 4

    with factory() as db:
        user = db.get(User, user_id)
        user.access_review_status = "completed"
        masterclass = db.scalar(
            select(Resource).where(Resource.code == "ACCESS_MASTERCLASS")
        )
        db.add(
            UserAccess(
                user_id=user.id,
                resource_id=masterclass.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            )
        )
        dqs = db.scalar(select(Resource).where(Resource.code == "dqs"))
        legacy = db.scalar(
            select(Resource).where(Resource.code == "ACCESS_MASTERCLASS_LEGACY")
        )
        db.add_all([
            UserAccess(user_id=user.id, resource_id=dqs.id, source="test", granted_at=datetime.now(timezone.utc)),
            UserAccess(user_id=user.id, resource_id=legacy.id, source="test", granted_at=datetime.now(timezone.utc)),
        ])
        db.commit()

    ready = client.get("/api/account?email=client@example.test")
    assert ready.status_code == 200
    data = ready.json()
    assert data["state"] == "ready"
    assert data["legal"]["required"] is True
    masterclass_card = next(item for item in data["courses"] if item["code"] == "masterclass")
    assert masterclass_card["state"] == "available"
    assert masterclass_card["app"] is None
    recipes_card = next(item for item in data["courses"] if item["code"] == "recipes")
    assert recipes_card["state"] == "not_owned"
    assert recipes_card["owned"] is False
    assert recipes_card["app"] is None
    dqs_card = next(item for item in data["applications"] if item["code"] == "dqs")
    assert dqs_card["owned"] is True
    assert dqs_card["app"] is None
    assert data["legacy_portal"]["available"] is True

    accepted = client.post(
        "/api/account/legal-acceptances",
        json={
            "email": "client@example.test",
            "document_codes": [
                "educational_disclaimer",
                "personal_data_consent",
            ],
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["legal"]["required"] is False
    masterclass_card = next(
        item for item in accepted.json()["courses"] if item["code"] == "masterclass"
    )
    assert masterclass_card["app"] == "masterclass-course"
    dqs_card = next(item for item in accepted.json()["applications"] if item["code"] == "dqs")
    assert dqs_card["state"] == "entitled_locked"
    assert dqs_card["app"] is None
    assert dqs_card["action_app"] == "masterclass-course"
    repeated = client.post(
        "/api/account/legal-acceptances",
        json={
            "email": "client@example.test",
            "document_codes": [
                "educational_disclaimer",
                "personal_data_consent",
            ],
        },
    )
    assert repeated.status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count(UserLegalAcceptance.id))) == 2
    app.dependency_overrides.clear()


def test_application_preview_entitlement_opens_only_owned_unreleased_apps(monkeypatch):
    from app.product_catalog_service import PRODUCT_CONNECTIONS

    monkeypatch.setitem(PRODUCT_CONNECTIONS["recipes"], "maintenance", False)
    client, factory, user_id = setup()
    with factory() as db:
        user = db.get(User, user_id)
        user.access_review_status = "completed"
        resources = [
            Resource(code="ACCESS_APPLICATION_PREVIEW", name="Предпросмотр", status="active"),
            Resource(code="strength", name="Дневник силовых", status="active"),
            Resource(code="recipes", name="Калькулятор рецептов", status="active"),
            Resource(code="metabolism", name="Калькулятор метаболизма", status="active"),
        ]
        db.add_all(resources)
        db.flush()
        db.add_all(
            UserAccess(
                user_id=user.id,
                resource_id=resource.id,
                source="test-preview",
                granted_at=datetime.now(timezone.utc),
            )
            for resource in resources
        )
        db.commit()

    data = client.get("/api/account?email=client@example.test").json()
    applications = {item["code"]: item for item in data["applications"]}
    assert applications["strength"]["app"] is None
    assert applications["strength"]["ready"] is True
    assert applications["recipes"]["app"] is None
    assert applications["metabolism"]["app"] is None

    accepted = client.post(
        "/api/account/legal-acceptances",
        json={
            "email": "client@example.test",
            "document_codes": [
                "educational_disclaimer",
                "personal_data_consent",
            ],
        },
    ).json()
    applications = {item["code"]: item for item in accepted["applications"]}
    courses = {item["code"]: item for item in accepted["courses"]}
    assert applications["strength"]["app"] == "strength"
    assert applications["recipes"]["app"] == "recipes"
    # The calculator right is not the paid course "Система рецептов".
    assert courses["recipes"]["owned"] is False
    assert courses["recipes"]["app"] is None
    # A direct application right is visible as ownership, but does not bypass
    # the course checkpoint required to open metabolism.
    assert applications["metabolism"]["app"] is None
    assert applications["metabolism"]["owned"] is True
    app.dependency_overrides.clear()


def test_published_application_requires_only_its_concrete_resource(monkeypatch):
    from app.product_catalog_service import PRODUCT_CONNECTIONS

    monkeypatch.setitem(PRODUCT_CONNECTIONS["recipes"], "maintenance", False)
    preview_only = {
        item["code"]: item
        for item in account_applications({"ACCESS_APPLICATION_PREVIEW"}, False)
    }
    resource_only = {
        item["code"]: item
        for item in account_applications({"recipes"}, False)
    }
    both = {
        item["code"]: item
        for item in account_applications(
            {"ACCESS_APPLICATION_PREVIEW", "recipes"}, False
        )
    }

    assert preview_only["recipes"]["ready"] is True
    assert preview_only["recipes"]["owned"] is False
    assert preview_only["recipes"]["app"] is None
    assert resource_only["recipes"]["ready"] is True
    assert resource_only["recipes"]["owned"] is True
    assert resource_only["recipes"]["app"] == "recipes"
    assert both["recipes"]["ready"] is True
    assert both["recipes"]["owned"] is True
    assert both["recipes"]["app"] == "recipes"


def test_product_maintenance_preserves_entitlements_and_reopens_owned_products(monkeypatch):
    from app.product_catalog_service import PRODUCT_CONNECTIONS
    import app.calorie_course_material_service as calorie_materials

    for code in ("calories", "recipes"):
        monkeypatch.setitem(PRODUCT_CONNECTIONS[code], "maintenance", True)
    client, factory, user_id = setup()
    with factory() as db:
        db.get(User, user_id).access_review_status = "completed"
        recipe_resource = Resource(code="recipes", name="Рецепты", status="active")
        recipe_course_resource = Resource(
            code="ACCESS_RECIPES", name="Система рецептов", status="active"
        )
        db.add_all([recipe_resource, recipe_course_resource])
        db.flush()
        resources = list(db.scalars(select(Resource).where(Resource.code.in_(
            ["ACCESS_MASTERCLASS", "ACCESS_CALORIES", "ACCESS_RECIPES", "recipes"]
        ))))
        for resource in resources:
            db.add(UserAccess(user_id=user_id, resource_id=resource.id, source="test",
                              granted_at=datetime.now(timezone.utc)))
        db.add(MasterclassEvent(
            user_id=user_id,
            event_key="course:completed",
            event_type="masterclass_completed",
            details={},
        ))
        db.commit()
        before = [(row.id, row.resource_id, row.revoked_at, row.expires_at)
                  for row in db.scalars(select(UserAccess).order_by(UserAccess.id))]

    monkeypatch.setattr(calorie_materials, "publication_status", lambda db: {"ready": True})
    login_user(client, "client@example.test")
    accepted = client.post("/api/account-auth/legal-acceptances", json={
        "document_codes": ["educational_disclaimer", "personal_data_consent"]
    })
    assert accepted.status_code == 200
    data = client.get("/api/account-auth/account").json()
    courses = {item["code"]: item for item in data["courses"]}
    assert courses["masterclass"]["app"] == "masterclass-course"
    for code in ("calories", "recipes"):
        assert courses[code]["owned"] is True
        assert courses[code]["state"] == "maintenance"
        assert courses[code]["ready"] is False
        assert courses[code]["app"] is None
    assert courses["strength"]["ready"] is False
    recipe_app = next(item for item in data["applications"] if item["code"] == "recipes")
    assert recipe_app["owned"] is True
    assert recipe_app["state"] == "available"
    assert recipe_app["app"] == "recipes"
    assert next(item for item in account_applications({"recipes", "ACCESS_APPLICATION_PREVIEW"}, False) if item["code"] == "recipes")["app"] == "recipes"

    login_user(client, "other@example.test")
    empty = client.get("/api/account-auth/account").json()
    for item in empty["courses"]:
        if item["code"] in {"calories", "recipes"}:
            assert item["owned"] is False
            assert item["state"] == "maintenance"
            assert item["purchase_mode"] is None

    for code in ("calories", "recipes"):
        monkeypatch.setitem(PRODUCT_CONNECTIONS[code], "maintenance", False)
    login_user(client, "client@example.test")
    restored = client.get("/api/account-auth/account").json()
    restored_courses = {item["code"]: item for item in restored["courses"]}
    assert restored_courses["calories"]["app"] == "calories-course"
    assert restored_courses["recipes"]["app"] == "recipes-course"
    assert next(item for item in restored["applications"] if item["code"] == "recipes")["app"] == "recipes"
    with factory() as db:
        after = [(row.id, row.resource_id, row.revoked_at, row.expires_at)
                 for row in db.scalars(select(UserAccess).order_by(UserAccess.id))]
        assert after == before
