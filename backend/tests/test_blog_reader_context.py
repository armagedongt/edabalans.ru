from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import base64
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.blog_routes import router
from app.blog_reader_context import COOKIE, TELEGRAM_BOT, TELEGRAM_PIN
from app.intensive_web_access import issue_access_token
from app.models import User, MessengerAccount, MessengerLinkToken


def test_public_article_prepares_single_shared_subscription_component(reader_client):
    client, _, _, _ = reader_client
    response = client.get('/blog/articles/pochemu-yapontsy-hudye-a-ty-net')
    assert response.status_code == 200
    assert response.text.count('id="reader-popup"') == 1
    assert response.text.split('<dialog id="reader-popup"')[1].count('Пишу о питании и похудении так, чтобы вы менялись.') == 1
    assert '/blog/assets/reader-subscription.js' in response.text
    assert 'reader-visitor' not in response.text
    assert client.get('/blog/assets/reader-subscription.js').status_code == 200
    assert client.get('/blog/assets/reader-subscription.css').status_code == 200
    assert client.get('/blog/assets/reader-max-logo.png').headers['content-type'] == 'image/png'


@pytest.fixture
def reader_client(monkeypatch):
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr('app.blog_routes.get_settings', lambda: SimpleNamespace(app_auth_secret='reader-test-secret'))
    def test_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = test_db
    with Session(engine) as db:
        user = User(status='active', display_name='Private name')
        db.add(user)
        db.flush()
        token, row = issue_access_token(db, user.id, 'telegram')
        account = MessengerAccount(user_id=user.id, platform='telegram', platform_user_id='12345', source='test', is_deliverable=True)
        db.add(account)
        db.commit()
        ids = user.id, row.id, account.id
    try:
        with TestClient(app, base_url='https://edabalans.ru') as client:
            yield client, engine, token, ids
    finally:
        engine.dispose()


def test_unknown_and_forged_cookie_never_prove_identity(reader_client):
    client, _, _, ids = reader_client
    guest = client.get('/blog/reader/context')
    assert guest.json()['recognized'] is False
    assert guest.json()['show_subscription'] is True
    assert guest.json()['telegram']['url'] == TELEGRAM_BOT
    assert guest.headers['cache-control'] == 'private, no-store'
    client.cookies.set(COOKIE, str(ids[0]), domain='edabalans.ru')
    assert client.get('/blog/reader/context').json() == guest.json()


def test_personal_link_sets_shared_recognition_cookie_without_login_or_personal_data(reader_client):
    client, _, token, _ = reader_client
    linked = client.post('/blog/reader/recognize', json={'token': token})
    assert linked.status_code == 204
    cookie = linked.headers['set-cookie']
    assert 'Domain=edabalans.ru' in cookie
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=lax' in cookie
    assert 'Max-Age=2592000' in cookie
    context = client.get('https://blog.edabalans.ru/blog/reader/context').json()
    assert context['recognized'] is True
    assert context['telegram']['url'] == TELEGRAM_BOT
    assert 'Private name' not in str(context)
    assert '12345' not in str(context)
    assert not any(c.name in {'edabalans_account_session', 'edabalans_intensive_session', 'edabalans_admin'} for c in client.cookies.jar)


def test_cookie_is_shared_between_russian_main_and_blog_not_unrelated_domains(reader_client):
    client, _, token, _ = reader_client
    root = 'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai'
    assert client.post(f'https://blog.{root}/blog/reader/recognize', json={'token': token}).status_code == 204
    assert client.get(f'https://{root}/blog/reader/context').json()['recognized'] is True
    assert client.get('https://edabalans.ru/blog/reader/context').json()['recognized'] is False


@pytest.mark.parametrize('entered,status,age,show,url', [
    (True, 'subscribed', 1, False, TELEGRAM_PIN),
    (True, 'not_subscribed', 1, True, TELEGRAM_PIN),
    (True, 'unknown', 1, True, TELEGRAM_PIN),
    (True, 'subscribed', 25, True, TELEGRAM_PIN),
    (False, 'subscribed', 1, False, TELEGRAM_BOT),
    (False, 'unknown', 1, True, TELEGRAM_BOT),
])
def test_bot_start_selects_destination_and_membership_separately_controls_visibility(reader_client, entered, status, age, show, url):
    client, engine, token, ids = reader_client
    with Session(engine) as db:
        account = db.get(MessengerAccount, ids[2])
        account.main_scenario_seen_at = datetime.now(timezone.utc) if entered else None
        account.subscription_status = status
        account.subscription_checked_at = datetime.now(timezone.utc) - timedelta(hours=age)
        db.commit()
    assert client.post('/blog/reader/recognize', json={'token': token}).status_code == 204
    context = client.get('/blog/reader/context').json()
    assert context['recognized'] is True
    assert context['show_subscription'] is show
    assert context['telegram']['url'] == url


@pytest.mark.parametrize('change', ['expired', 'deleted', 'wrong-purpose', 'inactive', 'merged'])
def test_revoked_source_or_user_invalidates_cookie(reader_client, change):
    client, engine, token, ids = reader_client
    assert client.post('/blog/reader/recognize', json={'token': token}).status_code == 204
    with Session(engine) as db:
        row = db.get(MessengerLinkToken, ids[1])
        user = db.get(User, ids[0])
        if change == 'expired':
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif change == 'deleted':
            db.delete(row)
        elif change == 'wrong-purpose':
            row.purpose = 'other'
        elif change == 'inactive':
            user.status = 'inactive'
        else:
            other = User(status='active')
            db.add(other)
            db.flush()
            user.merged_into_user_id = other.id
        db.commit()
    context = client.get('/blog/reader/context').json()
    assert context['recognized'] is False
    assert context['show_subscription'] is True


def test_invalid_personal_code_does_not_set_cookie(reader_client):
    client, _, _, _ = reader_client
    result = client.post('/blog/reader/recognize', json={'token': 'unknown-code'})
    assert result.status_code == 400
    assert 'set-cookie' not in result.headers


def test_tampered_well_formed_cookie_is_unknown(reader_client):
    client, _, token, _ = reader_client
    assert client.post('/blog/reader/recognize', json={'token': token}).status_code == 204
    value = next(c.value for c in client.cookies.jar if c.name == COOKIE)
    raw = bytearray(base64.urlsafe_b64decode(value))
    raw[-1] ^= 1
    forged = base64.urlsafe_b64encode(raw).decode()
    assert client.get('/blog/reader/context', headers={'Cookie': COOKIE + '=' + forged}).json()['recognized'] is False


def test_expired_authenticated_cookie_is_unknown_while_source_is_valid(reader_client):
    from app.blog_reader_context import _cipher, COOKIE_AGE
    client, _, _, ids = reader_client
    old = _cipher('reader-test-secret').encrypt_at_time(ids[1].bytes, int(time.time()) - COOKIE_AGE - 1).decode()
    context = client.get('/blog/reader/context', headers={'Cookie': COOKIE + '=' + old}).json()
    assert context['recognized'] is False


def test_subscribed_without_checked_date_is_unknown(reader_client):
    client, engine, token, ids = reader_client
    with Session(engine) as db:
        account = db.get(MessengerAccount, ids[2])
        account.subscription_status = 'subscribed'
        account.subscription_checked_at = None
        db.commit()
    assert client.post('/blog/reader/recognize', json={'token': token}).status_code == 204
    context = client.get('/blog/reader/context').json()
    assert context['telegram']['subscribed'] is None
    assert context['show_subscription'] is True


def test_cookie_does_not_expose_legacy_personal_token_record(reader_client):
    client, _, token, ids = reader_client
    assert client.post('/blog/reader/recognize', json={'token': token}).status_code == 204
    value = next(c.value for c in client.cookies.jar if c.name == COOKIE)
    raw = base64.urlsafe_b64decode(value)
    assert ids[1].bytes not in raw
    assert ids[1].hex not in value
    assert token not in value


@pytest.mark.parametrize('body', [
    '{"token":"\\ud800"}', '{"token":["\\ud800"]}',
    '{"token":{"x":"\\ud800"}}', '{"other":"\\ud800"}', '"\\ud800"',
])
def test_malformed_unicode_token_is_rejected_without_cookie(reader_client, body):
    client, _, _, _ = reader_client
    result = client.post('/blog/reader/recognize', content=body, headers={'Content-Type': 'application/json'})
    assert result.status_code == 422
    assert 'set-cookie' not in result.headers


def test_non_ascii_cookie_returns_unknown(reader_client):
    client, _, _, _ = reader_client
    result = client.get('/blog/reader/context', headers=[(b'cookie', b'edabalans_reader=a.b.\xff')])
    assert result.status_code == 200
    assert result.json()['recognized'] is False


def test_actual_short_bot_code_is_not_recoverable_from_reader_cookie(reader_client):
    import hashlib
    from app.intensive_web_access import consume_access_token
    client, engine, _, ids = reader_client
    # Canonical bot/service/app/intensive_access.py intensive_token uses this format.
    short = 'E' + base64.urlsafe_b64encode(ids[1].bytes).decode().rstrip('=')[:8]
    with Session(engine) as db:
        row = db.get(MessengerLinkToken, ids[1])
        row.token_hash = hashlib.sha256(short.encode()).hexdigest()
        db.commit()
    assert client.post('/blog/reader/recognize', json={'token': short}).status_code == 204
    value = next(c.value for c in client.cookies.jar if c.name == COOKIE)
    assert ids[1].bytes not in base64.urlsafe_b64decode(value)
    assert short not in value
    with Session(engine) as db:
        assert consume_access_token(db, value) is None
        assert consume_access_token(db, short).user_id == ids[0]
    assert client.get('/blog/reader/context').json()['recognized'] is True


def test_foreign_channel_membership_cannot_suppress_known_readers_invitation(reader_client):
    client, engine, token, ids = reader_client
    with Session(engine) as db:
        db.delete(db.get(MessengerAccount, ids[2]))
        other = User(status='active')
        db.add(other)
        db.flush()
        db.add(MessengerAccount(user_id=other.id, platform='telegram', platform_user_id='99999',
                                source='test', is_deliverable=True,
                                main_scenario_seen_at=datetime.now(timezone.utc),
                                subscription_status='subscribed', subscription_checked_at=datetime.now(timezone.utc)))
        db.commit()
    assert client.post('/blog/reader/recognize', json={'token': token}).status_code == 204
    context = client.get('/blog/reader/context').json()
    assert context['recognized'] is True
    assert context['show_subscription'] is True
    assert context['telegram']['url'] == TELEGRAM_BOT
