import os
import json
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.main import app
from app.account_auth_routes import COOKIE_NAME
from app.account_security import token_hash
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.models import AccountCredential, AccountSession, AdminAppEdit, DqsState, MetabolismState, StrengthState, User, UserEmail, Resource, UserAccess
from app.recipe_models import NutritionProduct


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def override_db():
        with factory() as db:
            yield db
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(database_url="sqlite+pysqlite:///:memory:", admin_username="admin", admin_password="admin-test")
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    monkeypatch.setattr("app.auth.get_settings", app.dependency_overrides[get_settings])
    monkeypatch.setattr("app.crm_routes.get_settings", app.dependency_overrides[get_settings])
    with factory() as db:
        ids = []
        for email, name in [("armagedongt@gmail.com", "Сергей Воронцов"), ("client@example.test", "Анна Клиент"), ("other@example.test", "Другой клиент")]:
            user = User(display_name=name, status="active"); db.add(user); db.flush(); ids.append(user.id)
            db.add(UserEmail(user_id=user.id, email_original=email, email_normalized=email, is_primary=True, source="test"))
            db.add(AccountCredential(user_id=user.id, password_hash="unused-password-hash", password_version=1, issued_via="test"))
            db.add(AccountSession(user_id=user.id, token_hash=token_hash(str(user.id)), password_version=1, expires_at=datetime.now(timezone.utc)+timedelta(days=1), last_seen_at=datetime.now(timezone.utc)))
            db.add(DqsState(user_id=user.id, start_date="2026-10-01", days={}))
            db.add(MetabolismState(user_id=user.id, variants={"1": {"weight": 60}}, active_variant=1, version=1))
            db.add(StrengthState(user_id=user.id, workout_types=[], workouts=[], hidden_exercises=[], version=1))
        db.commit()
    client = TestClient(app, base_url="https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai")
    def sign_in(index):
        client.cookies.set(COOKIE_NAME, str(ids[index]))
    yield client, factory, ids, sign_in
    client.close(); app.dependency_overrides.clear(); app.dependency_overrides.update(previous); engine.dispose()


def test_owner_session_can_select_client_without_general_admin_access(setup):
    client, _, ids, sign_in = setup; sign_in(0)
    response = client.get('/api/apps/manager/context', params={'app_user': str(ids[1])})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['actor']['email'] == 'armagedongt@gmail.com'
    assert response.json()['selected']['user_id'] == str(ids[1])
    assert client.get('/admin/api/apps/users?app_code=strength').status_code == 401
    assert client.get('/api/account-auth/session').json()['email'] == 'armagedongt@gmail.com'


def test_other_users_cannot_spoof_owner_or_read_any_managed_app(setup):
    client, factory, ids, sign_in = setup; sign_in(1)
    assert client.get('/api/apps/manager/context?email=armagedongt@gmail.com').status_code == 403
    assert client.get('/api/apps/manager/context').json()['can_manage'] is False
    assert client.get('/api/apps/manager/users').status_code == 401
    for method, path, data in [
        ('get', '/api/apps/strength', {'action': 'getWorkout', 'target_user_id': str(ids[2])}),
        ('post', f'/admin/api/apps/dqs/users/{ids[2]}/runtime', {'action': 'saveDay', 'day': '1', 'data': '{}'}),
        ('put', f'/admin/api/apps/metabolism/users/{ids[2]}/runtime', {'version': 1, 'variants': {'1': {'weight': 99}}}),
        ('get', '/api/apps/recipes', {'target_user_id': str(ids[2])}),
    ]:
        result = client.request(method, path, **({'params': data} if method == 'get' else {'json': data}))
        assert result.status_code == 401, result.text
    with factory() as db:
        assert db.scalar(select(MetabolismState).where(MetabolismState.user_id == ids[2])).version == 1
        assert db.scalar(select(AdminAppEdit.id)) is None


def test_owner_changes_only_selected_runtime_and_writes_audit(setup):
    client, factory, ids, sign_in = setup; sign_in(0); target = ids[1]
    dqs = client.post(f'/admin/api/apps/dqs/users/{target}/runtime', json={'action': 'saveDay', 'day': '1', 'data': json.dumps({'p': [0] * 17, 'd': [None] * 17})})
    assert dqs.status_code == 200 and dqs.json()['ok'], dqs.text
    meta = client.put(f'/admin/api/apps/metabolism/users/{target}/runtime', json={'variants': {'1': {'weight': 79}}, 'activeVariant': 1, 'version': 1})
    assert meta.status_code == 200 and meta.json()['version'] == 2
    strength = client.get('/api/apps/strength', params={'action': 'getWorkout', 'target_user_id': str(target), 'type': 1})
    assert strength.status_code == 200 and strength.json()['user']['email'] == 'client@example.test'
    saved = client.post('/api/apps/strength', json={'action': 'saveWorkoutTypes', 'target_user_id': str(target), 'version': 1, 'workout_types': [{'workout_type': 1, 'title': 'Верх', 'active': True}]})
    assert saved.status_code == 200 and saved.json()['ok'], saved.text
    with factory() as db:
        assert db.scalar(select(MetabolismState).where(MetabolismState.user_id == ids[0])).variants['1']['weight'] == 60
        assert db.scalar(select(MetabolismState).where(MetabolismState.user_id == target)).variants['1']['weight'] == 79
        edits = db.scalars(select(AdminAppEdit).where(AdminAppEdit.target_user_id == target)).all()
        assert {'dqs', 'strength', 'metabolism'} <= {edit.app_code for edit in edits}
        assert all(edit.admin_username == f'account:{ids[0]}' for edit in edits)


def test_recipes_keep_selected_client_products_private_and_audited(setup):
    client, factory, ids, sign_in = setup; sign_in(0)
    path = f'/api/apps/recipes/products?target_user_id={ids[1]}'
    created = client.post(path, json={'name': 'Личный продукт', 'protein': 2, 'fat': 3, 'carbohydrate': 4, 'calories': 50})
    assert created.status_code == 200 and created.json()['ok'], created.text
    product_id = created.json()['product']['id']
    assert len(client.get(path).json()['products']) == 1
    assert client.get(f'/api/apps/recipes/products?target_user_id={ids[2]}').json()['products'] == []
    assert client.delete(f'/api/apps/recipes/products/{product_id}?target_user_id={ids[2]}').status_code == 404
    with factory() as db:
        product = db.scalar(select(NutritionProduct).where(NutritionProduct.owner_user_id == ids[1]))
        assert str(product.id) == product_id
        assert db.scalar(select(AdminAppEdit).where(AdminAppEdit.app_code == 'recipes')).target_user_id == ids[1]


@pytest.mark.parametrize('invalid_session', ['revoked', 'expired', 'password_changed'])
def test_owner_capability_follows_live_native_session(setup, invalid_session):
    client, factory, ids, sign_in = setup; sign_in(0)
    with factory() as db:
        row = db.scalar(select(AccountSession).where(AccountSession.user_id == ids[0]))
        if invalid_session == 'revoked': row.revoked_at = datetime.now(timezone.utc)
        elif invalid_session == 'expired': row.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        else: db.get(AccountCredential, ids[0]).password_version += 1
        db.commit()
    assert client.get('/api/apps/manager/users').status_code == 401
    assert client.get('/api/apps/recipes', params={'target_user_id': str(ids[1])}).status_code == 401


def test_owner_write_rejects_foreign_origin(setup):
    client, _, ids, sign_in = setup; sign_in(0)
    response = client.post(f'/admin/api/apps/dqs/users/{ids[1]}/runtime', headers={'Origin': 'https://foreign.example'}, json={'action': 'saveDay'})
    assert response.status_code == 403


def test_directory_lists_all_clients_with_pagination_and_name_or_alias_search(setup):
    client, factory, ids, sign_in = setup; sign_in(0)
    with factory() as db:
        for i in range(103):
            user = User(display_name=f'Z{i:03}', status='active'); db.add(user); db.flush()
            db.add(UserEmail(user_id=user.id, email_original=f'z{i}@example.test', email_normalized=f'z{i}@example.test', source='test'))
        db.add(User(display_name='😀', status='active')); db.add(User(display_name='Без почты', status='active'))
        db.add(UserEmail(user_id=ids[1], email_original='alias@example.test', email_normalized='alias@example.test', is_primary=False, source='test')); db.commit()
    first = client.get('/api/apps/manager/users').json(); second = client.get('/api/apps/manager/users?offset=100').json()
    assert first['more'] is True and len(first['users']) == 100 and second['more'] is False
    assert len({user['user_id'] for user in first['users']+second['users']}) == 106
    assert all(user['email'] for user in first['users']+second['users'])
    assert client.get('/api/apps/manager/users', params={'q': 'Без почты'}).json()['users'] == []
    for query in ['Клиент', 'alias@example.test']:
        result = client.get('/api/apps/manager/users', params={'q': query}).json()
        assert str(ids[1]) in {row['user_id'] for row in result['users']}


def test_existing_admin_basic_and_cookie_entries_keep_managed_apis(setup):
    client, factory, ids, _ = setup
    denied = client.get(f'/admin/api/apps/dqs/users/{ids[1]}')
    assert denied.status_code == 401 and denied.headers['www-authenticate'] == 'Basic realm="Edabalans CRM"'
    with factory() as db:
        resource = Resource(code="strength", name="Силовые", status="active"); db.add(resource); db.flush()
        db.add(UserAccess(user_id=ids[1], resource_id=resource.id, source="test", granted_at=datetime.now(timezone.utc))); db.commit()
    basic = ("admin", "admin-test")
    for code in ["dqs", "metabolism", "strength"]:
        assert client.get(f'/admin/api/apps/{code}/users/{ids[1]}', auth=basic).status_code == 200
    assert client.post(f'/admin/api/apps/strength/users/{ids[1]}/open', auth=basic).status_code == 200
    assert client.post(f'/admin/api/apps/dqs/users/{ids[1]}/runtime', auth=basic, json={"action": "openUser"}).status_code == 200
    assert client.get(f'/admin/api/apps/metabolism/users/{ids[1]}/runtime', auth=basic).status_code == 200
    assert client.put(f'/admin/api/apps/metabolism/users/{ids[1]}/runtime', auth=basic, json={"variants": {"1": {"weight": 70}}, "activeVariant": 1, "version": 1}).status_code == 200
    assert client.post('/admin/api/login', json={"username": basic[0], "password": basic[1]}).status_code == 200
    assert client.get(f'/admin/api/apps/dqs/users/{ids[1]}').status_code == 200


def test_native_owner_cannot_mutate_strength_by_cross_site_get(setup):
    client, factory, ids, sign_in = setup; sign_in(0)
    with factory() as db:
        row = db.scalar(select(StrengthState).where(StrengthState.user_id == ids[1]))
        row.hidden_exercises = [{"exercise_id": "bench-press", "workout_type": 1, "active": True}]; db.commit()
    response = client.get('/api/apps/strength', params={"action": "saveExerciseSettings", "target_user_id": str(ids[1]), "workout_type": 1, "version": 1}, headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Referer": "https://foreign.example/"})
    assert response.status_code == 405, response.text
    with factory() as db:
        row = db.scalar(select(StrengthState).where(StrengthState.user_id == ids[1]))
        assert row.version == 1 and row.hidden_exercises == [{"exercise_id": "bench-press", "workout_type": 1, "active": True}]
        assert db.scalar(select(AdminAppEdit.id)) is None
