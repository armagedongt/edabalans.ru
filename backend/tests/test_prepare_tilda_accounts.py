import hashlib
import csv
from datetime import datetime, timezone

import pytest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from test_account_password_auth import settings
from app.account_security import verify_password, decrypt_password
from app.database import Base
from app.importers.prepare_tilda_accounts import parse_members, prepare
from app.models import AccountCredential, AccountOnboarding, Resource, User, UserAccess, UserCoursePolicy, UserEmail


def fixture():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for code in ["ACCESS_MASTERCLASS", "ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES",
                 "ACCESS_CALORIES_LEGACY", "ACCESS_RECIPES", "dqs", "recipes", "metabolism"]:
        db.add(Resource(code=code, name=code, status="active"))
    db.commit()
    return db


def member(email="member@example.test", codes=None):
    return {"email": email, "name": "Member", "groups": [], "codes": codes or []}


def run(db, members):
    result = prepare(db, members, settings(), "test-transfer", hashlib.sha256(b"fixture").hexdigest())
    db.commit()
    return result


def test_prepare_issues_working_password_without_queue_and_preserves_it_on_repeat():
    with fixture() as db:
        first = run(db, [member(codes=["ACCESS_MASTERCLASS"])])
        user = db.scalar(select(User))
        credential = db.get(AccountCredential, user.id)
        password = decrypt_password(credential.password_ciphertext, settings().app_auth_secret)
        assert verify_password(password, credential.password_hash, settings().app_auth_secret)
        original = credential.password_hash
        second = run(db, [member(codes=["ACCESS_MASTERCLASS"])])
        assert first["passwords_created"] == 1
        assert second["passwords_created"] == 0
        assert db.get(AccountCredential, user.id).password_hash == original
        assert db.scalar(select(func.count()).select_from(AccountOnboarding)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_unknown_materials_get_account_without_course_rights():
    with fixture() as db:
        report = run(db, [member()])
        assert report["recipients"][0]["rights"] == []
        assert report["recipients"][0]["review_status"] == "pending"
        assert db.scalar(select(func.count()).select_from(AccountOnboarding)) == 0


def test_legacy_courses_and_separately_purchased_recipes_remain_distinct():
    with fixture() as db:
        report = run(db, [member(codes=["ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES_LEGACY", "ACCESS_RECIPES"])])
        rights = set(report["recipients"][0]["rights"])
        assert {"ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES_LEGACY", "ACCESS_RECIPES", "recipes", "metabolism"} <= rights
        assert not rights.intersection({"ACCESS_MASTERCLASS", "ACCESS_CALORIES", "dqs"})


@pytest.mark.parametrize("restriction", ["paused_at", "revoked_at"])
@pytest.mark.parametrize("start_mode", ["open", "blocked"])
def test_explicit_right_restriction_and_manual_course_policy_are_preserved(restriction, start_mode):
    with fixture() as db:
        user = User(status="active", access_review_status="not_required")
        db.add(user)
        db.flush()
        db.add(UserEmail(user_id=user.id, email_original="member@example.test", email_normalized="member@example.test", source="fixture"))
        mc = db.scalar(select(Resource).where(Resource.code == "ACCESS_MASTERCLASS"))
        recipes = db.scalar(select(Resource).where(Resource.code == "ACCESS_RECIPES"))
        db.add(UserAccess(user_id=user.id, resource_id=mc.id, source="manual_admin", granted_at=datetime.now(timezone.utc)))
        db.add(UserAccess(user_id=user.id, resource_id=recipes.id, source="manual_admin", granted_at=datetime.now(timezone.utc), **{restriction: datetime.now(timezone.utc)}))
        db.add(UserCoursePolicy(user_id=user.id, resource_id=mc.id, start_mode=start_mode, unlock_mode="fully_unlocked", source="manual_admin"))
        db.commit()
        report = run(db, [member(codes=["ACCESS_MASTERCLASS", "ACCESS_RECIPES"])])
        assert "ACCESS_RECIPES" not in report["recipients"][0]["rights"]
        assert "ACCESS_RECIPES" in report["recipients"][0]["skipped_rights"]
        policy = db.scalar(select(UserCoursePolicy).where(UserCoursePolicy.user_id == user.id))
        assert policy.unlock_mode == "fully_unlocked"
        assert policy.start_mode == start_mode
        assert policy.source == "manual_admin"


def test_legacy_calories_alone_do_not_grant_recipes():
    with fixture() as db:
        result = run(db, [member(codes=["ACCESS_CALORIES_LEGACY"])])
        rights = set(result["recipients"][0]["rights"])
        assert rights == {"ACCESS_CALORIES_LEGACY", "metabolism"}


def test_parse_excludes_owner_and_maps_standalone_recipes(tmp_path):
    path = tmp_path / "members.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["armagedongt@gmail.com", "Owner", "", "Active", "", "", "Мастер-класс"])
        writer.writerow(["member@example.test", "Member", "", "Active", "", "", "Книга рецептов"])
    members = parse_members(path)
    assert len(members) == 1
    assert members[0]["email"] == "member@example.test"
    assert members[0]["codes"] == ["ACCESS_RECIPES"]


def test_unknown_snapshot_does_not_open_unrelated_preexisting_calories():
    with fixture() as db:
        user = User(status="active", access_review_status="not_required")
        db.add(user)
        db.flush()
        db.add(UserEmail(user_id=user.id, email_original="member@example.test", email_normalized="member@example.test", source="fixture"))
        cal = db.scalar(select(Resource).where(Resource.code == "ACCESS_CALORIES"))
        db.add(UserAccess(user_id=user.id, resource_id=cal.id, source="paid_product_rule", granted_at=datetime.now(timezone.utc)))
        db.add(UserCoursePolicy(user_id=user.id, resource_id=cal.id, start_mode="auto", unlock_mode="paced", source="paid_product_rule"))
        db.commit()
        report = run(db, [member()])
        assert report["recipients"][0]["rights"] == ["ACCESS_CALORIES"]
        policy = db.scalar(select(UserCoursePolicy).where(UserCoursePolicy.user_id == user.id))
        assert policy.start_mode == "auto"
