from datetime import datetime, timezone, timedelta
import uuid
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from test_account_password_auth import settings
from app import account_onboarding_service as delivery, tilda_mailing_service as mailing
from app.account_security import decrypt_password
from app.auth import require_admin
from app.config import get_settings
from app.database import Base, get_db
from app.importers.prepare_tilda_accounts import prepare
from app.models import AccountCredential, AccountOnboarding, AccountSession, Resource, User, UserAccess, UserCoursePolicy, UserEmail
from app.product_catalog_service import active_product_catalog
from app.tilda_mailing_routes import router


@pytest.fixture
def store():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        active_product_catalog(db)
        for code in ("ACCESS_MASTERCLASS", "ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES", "ACCESS_CALORIES_LEGACY", "ACCESS_RECIPES", "ACCESS_CONSULTATION", "ACCESS_COACHING", "dqs", "recipes", "metabolism"):
            db.add(Resource(code=code, name=code, status="active"))
        db.commit()
        members = [{"email":"new@example.test", "name":"New", "groups":[], "codes":["ACCESS_MASTERCLASS", "ACCESS_CONSULTATION", "ACCESS_COACHING"]},
                   {"email":"unknown@example.test", "name":"Unknown", "groups":[], "codes":[]},
                   {"email":"old@example.test", "name":"Old", "groups":[], "codes":["ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES_LEGACY"]},
                   {"email":"existing@example.test", "name":"Existing", "groups":[], "codes":["ACCESS_MASTERCLASS"]}]
        manifest = prepare(db, members, settings(), "fixture", "fixture")
        manifest["recipients"][-1]["account_existing"] = True
        db.commit()
    yield factory, manifest


def stage(factory, manifest):
    with factory() as db:
        result = mailing.prepare_drafts(db, manifest, settings(), "owner")
        db.commit()
        return result


def test_paused_drafts_have_current_password_correct_editions_and_exclude_existing(store, monkeypatch):
    factory, manifest = store
    assert stage(factory, manifest) == 3
    assert stage(factory, manifest) == 0
    monkeypatch.setattr(delivery, "SessionLocal", factory)
    sender = Mock()
    monkeypatch.setattr(delivery, "_send_message", sender)
    assert delivery.process_due_account_email(settings()) is False
    sender.assert_not_called()
    with factory() as db:
        drafts = mailing.rows(db)
        assert len(drafts) == 3
        for row in drafts:
            bundle = delivery._decrypt_bundle(row.claim_bundle_encrypted, settings())
            credential = db.get(AccountCredential, row.user_id)
            assert decrypt_password(credential.password_ciphertext, settings().app_auth_secret) in bundle["message_text"]
            assert row.email_status == "draft"
            assert bundle["message_text"].startswith("Здравствуйте!\n")
            assert "сопровожд" not in bundle["message_text"].lower()
            if bundle["email"] == "new@example.test":
                assert "консультац" not in bundle["message_text"].lower()
                assert "ACCESS_CONSULTATION" in mailing.active_resource_codes(db, row.user_id)
            assert 'edabalans.ru' not in bundle["message_text"]
            if bundle["email"].startswith('old'):
                assert 'необновляемый доступ' in bundle['message_text']
                assert 'Приобрести полный пакет' in bundle['message_text']
                assert '— DQS' not in bundle['message_text']
            if bundle["email"].startswith('unknown'):
                assert 'нет подтверждённых доступов' in bundle['message_text']


def test_preview_edit_exclude_launch_and_repeat_do_not_send_twice(store, monkeypatch):
    factory, manifest = store
    stage(factory, manifest)
    with factory() as db:
        all_rows = mailing.rows(db)
        for row in all_rows:
            bundle = delivery._decrypt_bundle(row.claim_bundle_encrypted, settings())
            subject = 'Моя поправленная тема' if bundle['email'] == 'new@example.test' else bundle['subject']
            text = bundle['message_text'] + '\nМоё личное дополнение.' if bundle['email'] == 'new@example.test' else bundle['message_text']
            mailing.update_draft(db,row,settings(),'owner',subject,text,not bundle['upgrade'])
            if bundle['email'] == 'new@example.test':
                edited_text = text
        db.commit()
        assert mailing.launch(db, settings(), 'owner', 2) == 2
        db.commit()
        assert {r.email_status for r in mailing.rows(db)} == {'pending','excluded'}
        with pytest.raises(ValueError,match='Список получателей изменился'):
            mailing.launch(db,settings(),'owner',2)
    monkeypatch.setattr(delivery,'SessionLocal',factory)
    sender = Mock()
    monkeypatch.setattr(delivery,'_send_message',sender)
    assert delivery.process_due_account_email(settings()) is True
    assert delivery.process_due_account_email(settings()) is True
    assert delivery.process_due_account_email(settings()) is False
    assert sender.call_count == 2
    messages = {str(call.args[0]['To']):call.args[0] for call in sender.call_args_list}
    assert set(messages) == {'new@example.test','unknown@example.test'}
    assert str(messages['new@example.test']['Subject']) == 'Моя поправленная тема'
    assert messages['new@example.test'].get_content().rstrip() == edited_text.rstrip()
    with factory() as db:
        assert [r.email_status for r in mailing.rows(db)].count('excluded') == 1


def test_disabled_offer_or_changed_password_blocks_entire_launch(store):
    factory, manifest = store
    stage(factory, manifest)
    with factory() as db:
        with pytest.raises(ValueError,match='ещё не включено'):
            mailing.launch(db,settings(),'owner',3)
        assert all(r.email_status == 'draft' for r in mailing.rows(db))
        row = mailing.rows(db)[0]
        credential = db.get(AccountCredential,row.user_id)
        credential.password_version += 1
        db.flush()
        with pytest.raises(ValueError,match='Пароль'):
            mailing.launch(db,settings(),'owner',3)


def test_worker_preserves_subject_body_and_password_and_suppresses_changed_credential(store, monkeypatch):
    factory, manifest = store
    stage(factory, manifest)
    with factory() as db:
        rows = mailing.rows(db)
        for row in rows:
            bundle=delivery._decrypt_bundle(row.claim_bundle_encrypted,settings())
            if bundle['email']=='new@example.test':
                row.email_status='pending'
                good=bundle
            elif bundle['email']=='unknown@example.test':
                row.email_status='pending'
                db.get(AccountCredential,row.user_id).password_version += 1
        db.commit()
    monkeypatch.setattr(delivery,'SessionLocal',factory)
    sender=Mock()
    monkeypatch.setattr(delivery,'_send_message',sender)
    assert delivery.process_due_account_email(settings()) is True
    assert delivery.process_due_account_email(settings()) is True
    assert delivery.process_due_account_email(settings()) is False
    sender.assert_called_once()
    message=sender.call_args.args[0]
    assert str(message['Subject'])==good['subject']
    assert message.get_content().rstrip()==good['message_text'].rstrip()
    with factory() as db:
        assert {r.email_status for r in mailing.rows(db)} == {'sent','superseded','draft'}
        assert db.scalar(select(func.count()).select_from(AccountCredential)) == 4


def test_admin_only_no_cache_origin_guard_and_confirmation(store):
    factory,manifest=store
    stage(factory,manifest)
    app=FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings]=settings
    def database():
        with factory() as db: yield db
    app.dependency_overrides[get_db]=database
    with TestClient(app) as client:
        assert client.get('/admin/api/tilda-mailing').status_code == 401
        app.dependency_overrides[require_admin]=lambda:'owner'
        response=client.get('/admin/api/tilda-mailing')
        assert response.status_code==200
        assert response.headers['cache-control']=='no-store'
        assert 'message_text' not in response.text
        row=response.json()['recipients'][0]
        draft=client.get('/admin/api/tilda-mailing/'+row['id'])
        assert draft.headers['cache-control']=='no-store'
        assert 'Пароль:' in draft.json()['text']
        assert client.post('/admin/api/tilda-mailing/launch',json={'expected_count':3,'confirm_send':False}).status_code==422
        assert client.post('/admin/api/tilda-mailing/launch',headers={'Origin':'https://another.example.test'},json={'expected_count':3,'confirm_send':True}).status_code==403


@pytest.mark.parametrize("start,unlock,expected", [
    ("blocked", "fully_unlocked", "начало пока закрыто — напишите мне"),
    ("auto", "fully_unlocked", "материалы открыты сразу"),
    ("open", "fully_unlocked", "материалы открыты сразу"),
    ("open", "paced", "можно начать сразу; материалы открываются последовательно"),
])
def test_access_description_matches_actual_course_policy(store, start, unlock, expected):
    factory, manifest = store
    with factory() as db:
        user = db.scalar(select(User).join(UserEmail).where(UserEmail.email_normalized == "new@example.test"))
        resource = db.scalar(select(Resource).where(Resource.code == "ACCESS_MASTERCLASS"))
        policy = db.scalar(select(UserCoursePolicy).where(UserCoursePolicy.user_id == user.id, UserCoursePolicy.resource_id == resource.id))
        policy.start_mode = start
        policy.unlock_mode = unlock
        db.flush()
        text = mailing.access_text(db, user)
        assert "— Мастер-класс" in text
        assert expected in text
        assert "Мини-курс" not in text
        assert "Система рецептов" not in text
        assert "— DQS" in text
        assert "по условиям открытия соответствующих материалов" in text


def test_main_routes_mailing_before_generic_admin_section(monkeypatch):
    from app.main import app
    monkeypatch.setattr("app.auth.admin_identity", lambda request: "owner")
    response = TestClient(app).get("/admin/tilda-mailing")
    assert response.status_code == 200
    assert 'id="letter-form"' in response.text


def record_login(db, user_id):
    now = datetime.now(timezone.utc)
    # Expired/revoked sessions still prove a previous customer login.
    db.add(AccountSession(user_id=user_id, token_hash=uuid.uuid4().hex * 2,
                          password_version=1, created_at=now - timedelta(days=60),
                          last_seen_at=now - timedelta(days=59), expires_at=now - timedelta(days=15),
                          revoked_at=now - timedelta(days=59)))
    db.flush()


def test_refresh_uses_current_rights_keeps_password_and_excludes_previous_login(store):
    factory, manifest = store
    stage(factory, manifest)
    with factory() as db:
        row = next(r for r in mailing.rows(db) if delivery._decrypt_bundle(r.claim_bundle_encrypted,settings())["email"] == "new@example.test")
        old = delivery._decrypt_bundle(row.claim_bundle_encrypted,settings())
        cred = db.get(AccountCredential,row.user_id)
        fingerprint = (cred.password_hash,cred.password_ciphertext,cred.password_version)
        resource = db.scalar(select(Resource).where(Resource.code == "ACCESS_CALORIES"))
        db.add(UserAccess(user_id=row.user_id,resource_id=resource.id,source="fixture",granted_at=datetime.now(timezone.utc)))
        db.add(UserCoursePolicy(user_id=row.user_id,resource_id=resource.id,start_mode="open",unlock_mode="paced",source="fixture"))
        record_login(db,row.user_id)
        assert mailing.refresh_drafts(db,settings(),"owner") == 3
        db.commit()
        bundle = delivery._decrypt_bundle(row.claim_bundle_encrypted,settings())
        assert 'Мини-курс «Калорийный»' in bundle['message_text']
        assert bundle['message_text'].startswith('Здравствуйте!\n')
        assert 'сопровожд' not in bundle['message_text'].lower()
        assert bundle['password_version'] == old['password_version']
        assert fingerprint == (cred.password_hash,cred.password_ciphertext,cred.password_version)
        assert row.email_status == 'excluded'
        assert mailing.listing(db,settings())['selected'] == 2


def test_later_login_excluded_at_launch_and_cannot_be_reincluded(store):
    factory,manifest=store
    stage(factory,manifest)
    with factory() as db:
        all_rows=mailing.rows(db)
        new=next(r for r in all_rows if delivery._decrypt_bundle(r.claim_bundle_encrypted,settings())['email']=='new@example.test')
        old=next(r for r in all_rows if delivery._decrypt_bundle(r.claim_bundle_encrypted,settings())['upgrade'])
        old.email_status='excluded'
        record_login(db,new.user_id)
        assert mailing.listing(db,settings())['selected'] == 1
        with pytest.raises(ValueError,match='Участник уже входил'):
            mailing.update_draft(db,new,settings(),'owner','Тема','Текст',True)
        assert mailing.launch(db,settings(),'owner',1) == 1
        db.commit()
        assert new.email_status == 'excluded'
        assert old.email_status == 'excluded'
        assert [r.email_status for r in mailing.rows(db)].count('pending') == 1


@pytest.mark.parametrize("ordinary_mode", ["admin_message", "direct_password"])
def test_login_after_queue_prevents_smtp_without_affecting_other_mail(store,monkeypatch,ordinary_mode):
    factory,manifest=store
    stage(factory,manifest)
    with factory() as db:
        row=mailing.rows(db)[0]
        row.email_status='pending'
        row.created_at=datetime.now(timezone.utc)-timedelta(minutes=2)
        record_login(db,row.user_id)
        if ordinary_mode == "admin_message":
            regular,_=delivery.queue_admin_message_email(db,user_id=row.user_id,message_text="Личное сообщение",settings=settings(),admin="owner")
        else:
            user=db.get(User,row.user_id)
            regular=delivery.queue_direct_credential_email(db,user=user,password_version=db.get(AccountCredential,user.id).password_version,settings=settings())
        regular_id=regular.id
        db.commit()
    monkeypatch.setattr(delivery,'SessionLocal',factory)
    sender=Mock();monkeypatch.setattr(delivery,'_send_message',sender)
    assert delivery.process_due_account_email(settings()) is True
    sender.assert_not_called()
    assert delivery.process_due_account_email(settings()) is True
    assert delivery.process_due_account_email(settings()) is False
    sender.assert_called_once()
    with factory() as db:
        assert [r.email_status for r in mailing.rows(db)].count('excluded') == 1
        assert db.get(AccountOnboarding,regular_id).email_status == "sent"


def test_calories_without_start_policy_does_not_promise_immediate_entry(store):
    factory,manifest=store
    with factory() as db:
        user=db.scalar(select(User).join(UserEmail).where(UserEmail.email_normalized=='new@example.test'))
        resource=db.scalar(select(Resource).where(Resource.code=='ACCESS_CALORIES'))
        db.add(UserAccess(user_id=user.id,resource_id=resource.id,source='fixture',granted_at=datetime.now(timezone.utc)))
        db.flush()
        line=next(l for l in mailing.access_text(db,user).splitlines() if 'Мини-курс' in l)
        assert 'начало откроется по условиям программы' in line
        assert 'можно начать сразу' not in line
