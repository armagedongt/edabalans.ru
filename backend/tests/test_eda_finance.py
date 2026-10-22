from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient

from app.main import app


def test_finance_model_uses_admin_session() -> None:
    client = TestClient(app, base_url="https://app.edabalans.ru")
    anonymous = client.get("/finance", follow_redirects=False)
    assert anonymous.status_code == 303
    assert anonymous.headers["location"] == "/admin?next=/finance"
    login = client.post(
        "/admin/api/login",
        json={"username": "admin@example.com", "password": "test-admin-password"},
    )
    assert login.status_code == 200
    response = client.get("/finance")

    assert response.status_code == 200
    assert '<link rel="icon" type="image/svg+xml" href="/admin/static/admin-favicon.svg">' in response.text
    assert 'id="save"' in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert "digitalAverage:4840" in response.text
    assert 'id="ltv-after-labor"' in response.text
    assert 'id="self-cashflow"' in response.text
    assert 'id="self-ltv"' in response.text
    assert 'id="self-after-cac"' in response.text
    assert "consultCap:6" in response.text
    assert "supportPrice:9800" in response.text
    assert "const fieldOptions" in response.text
    assert "conversion:{step:.25" in response.text
    assert "supportMonths:{step:.5" in response.text
    assert "normaliseTariffShares" in response.text
    assert 'id="consult-tariff-sold"' in response.text
    assert 'id="lost-by-cap"' in response.text
    assert "lostByCap=excessConsultDemand*.10" in response.text
    assert "reallocatedByCap=excessConsultDemand*.90" in response.text
    assert "finance-tooltip" in response.text
    assert "edabalans-finance-model-v2" in response.text
    assert "/admin/static/admin-shell.css" in response.text
    assert "/admin/static/admin-shell.js" in response.text


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import get_db
from app.models import ManagedDocumentVersion

ENDPOINT = '/admin/api/finance/plans'
PARAMETERS = dict(paid=25, organic=5, conversion=3, cpl=150, minPrice=6900,
    standardPrice=8900, consultTariff=15900, consultCap=6, minShare=40,
    standardShare=40, consultShare=20, digitalRate=15, digitalAverage=4840,
    consultRate=10, supportRate=35, supportPrice=9800, supportMonths=3,
    clubEnabled=False, clubRate=10, clubPrice=990, clubMonths=4, opex=20000,
    weeklyCap=6, timeUnit=4000, feeRate=10)


@pytest.fixture
def plans_client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    ManagedDocumentVersion.__table__.create(engine)
    factory = sessionmaker(engine)
    def db():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = db
    client = TestClient(app, base_url='https://admin.example.com')
    client.post('/admin/api/login', json={'username':'admin@example.com','password':'test-admin-password'})
    yield client
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def plan_body(**updates):
    return dict(name='План <b>1</b>', parameters=PARAMETERS,
        summary=dict(club=0,club_enabled=False,income=100,margin=50,ads=125000,opex=20000,turnover=200000), **updates)


def test_server_plans_roundtrip_multiple_and_delete(plans_client):
    client = plans_client
    headers = {'X-Finance-Write':'1'}
    first = client.post(ENDPOINT, json=plan_body(), headers=headers)
    assert first.status_code == 200, first.text
    plan = first.json()['plan']
    assert plan['parameters'] == PARAMETERS
    assert plan['saved_at'].endswith('+00:00')
    second = client.post(ENDPOINT, json=plan_body(), headers=headers).json()['plan']
    assert plan['id'] != second['id']
    # A new client with the same admin cookie can read the persisted scenarios.
    other = TestClient(app, base_url='https://admin.example.com')
    other.cookies.update(client.cookies)
    listing = other.get(ENDPOINT)
    assert listing.headers['cache-control'] == 'no-store'
    assert [p['id'] for p in listing.json()['plans']] == [second['id'],plan['id']]
    assert other.delete(ENDPOINT+'/'+plan['id'], headers=headers).status_code == 200
    assert [p['id'] for p in client.get(ENDPOINT).json()['plans']] == [second['id']]
    assert client.delete(ENDPOINT+'/'+plan['id'], headers=headers).status_code == 404


def test_legacy_import_is_idempotent_and_does_not_resurrect_deleted_plan(plans_client):
    client=plans_client
    headers={'X-Finance-Write':'1'}
    body=plan_body(legacy=True)
    first=client.post(ENDPOINT,json=body,headers=headers).json()['plan']
    assert client.post(ENDPOINT,json=body,headers=headers).json()['plan']['id'] == first['id']
    client.delete(ENDPOINT+'/'+first['id'],headers=headers)
    assert client.post(ENDPOINT,json=body,headers=headers).json()['plan'] is None
    assert client.get(ENDPOINT).json()['plans'] == []


def test_plan_api_rejects_anonymous_cross_origin_and_incomplete_data(plans_client):
    anonymous=TestClient(app,base_url='https://admin.example.com')
    assert anonymous.get(ENDPOINT).status_code == 401
    assert anonymous.post(ENDPOINT,json=plan_body(),headers={'X-Finance-Write':'1'}).status_code == 401
    assert anonymous.delete(ENDPOINT+'/00000000-0000-0000-0000-000000000000',headers={'X-Finance-Write':'1'}).status_code == 401
    assert plans_client.post(ENDPOINT,json=plan_body()).status_code == 403
    headers={'X-Finance-Write':'1','Origin':'https://untrusted.example'}
    assert plans_client.post(ENDPOINT,json=plan_body(),headers=headers).status_code == 403
    assert plans_client.delete(ENDPOINT+'/00000000-0000-0000-0000-000000000000',headers=headers).status_code == 403
    body=plan_body(); body['parameters']={'paid':5}
    assert plans_client.post(ENDPOINT,json=body,headers={'X-Finance-Write':'1'}).status_code == 422


def test_split_conversions_roundtrip_and_validate_total(plans_client):
    parameters={**PARAMETERS,'paidConversion30':2,'paidConversionLater':1,
                'organicConversion30':4,'organicConversionLater':2}
    body={**plan_body(),'parameters':parameters}
    headers={'X-Finance-Write':'1'}
    saved=plans_client.post(ENDPOINT,json=body,headers=headers)
    assert saved.status_code==200
    assert saved.json()['plan']['parameters']==parameters
    for changes in ({'paidConversionLater':99},{'conversion':5},{'organicConversion30':True}):
        invalid={**body,'parameters':{**parameters,**changes}}
        assert plans_client.post(ENDPOINT,json=invalid,headers=headers).status_code==422
    missing={**parameters};missing.pop('organicConversionLater')
    assert plans_client.post(ENDPOINT,json={**body,'parameters':missing},headers=headers).status_code==422
