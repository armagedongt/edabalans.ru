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


def test_finance_model_uses_admin_session_and_contains_browser_persistence() -> None:
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
    assert 'id="save"' in response.text
    assert 'id="restore"' in response.text
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
