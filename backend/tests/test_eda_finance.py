from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from fastapi.testclient import TestClient

from app.main import app


def test_finance_model_is_public_and_contains_browser_persistence() -> None:
    response = TestClient(app).get("/finance")

    assert response.status_code == 200
    assert 'id="save"' in response.text
    assert 'id="restore"' in response.text
    assert "digitalAverage:4840" in response.text
    assert 'id="ltv-after-labor"' in response.text
    assert 'id="self-cashflow"' in response.text
    assert 'id="self-ltv"' in response.text
    assert 'id="self-after-cac"' in response.text
    assert "finance-tooltip" in response.text
    assert "edabalans-finance-model-v2" in response.text
