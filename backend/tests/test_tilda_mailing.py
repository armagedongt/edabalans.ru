from datetime import datetime, timezone
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
from app.models import AccountCredential, AccountOnboarding, Resource, User, UserCoursePolicy, UserEmail
from app.product_catalog_service import active_product_catalog
from app.tilda_mailing_routes import router


@pytest.fixture
def store():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        active_product_catalog(db)
        for code in ("ACCESS_MASTERCLASS", "ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES", "ACCESS_CALORIES_LEGACY", "ACCESS_RECIPES", "dqs", "recipes", "metabolism"):
            db.add(Resource(code=code, name=code, status="active"))
        db.commit()
        members = [{"email":"new@example.test", "name":"New", "groups":[], "codes":["ACCESS_MASTERCLASS"]},
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
    ("auto", "fully_unlocked", "начало откроется по условиям программы"),
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
