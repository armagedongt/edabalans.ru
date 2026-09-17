from fastapi.testclient import TestClient

from app.main import app
import app.main as main


def test_bot_shared_cookie_survives_29_days_and_logout_clears_it(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_username", "owner@example.com")
    monkeypatch.setattr(main.settings, "admin_password", "contract-test-password")
    start = 2_000_000_000
    monkeypatch.setattr(main.time, "time", lambda: start)
    client = TestClient(app, base_url="https://edabalans.ru")
    client.cookies.set("edabalans_admin", "legacy-host-cookie", domain="edabalans.ru", path="/")
    login = client.post("/bot-api/login", json={
        "username": "owner@example.com", "password": "contract-test-password",
    })
    assert login.status_code == 200
    assert len([c for c in client.cookies.jar if c.name == "edabalans_admin"]) == 1
    token = client.cookies.get("edabalans_admin")
    cookies = login.headers.get_list("set-cookie")
    assert any("Domain=.edabalans.ru" in value and "Max-Age=2592000" in value
               and "HttpOnly" in value and "Secure" in value and "SameSite=strict" in value
               for value in cookies)
    monkeypatch.setattr(main.time, "time", lambda: start + 29 * 86400)
    assert 'id="login-form"' not in client.get("https://api.edabalans.ru/bot").text
    assert 'id="login-form"' in client.get("https://unrelated.example/bot").text
    monkeypatch.setattr(main.time, "time", lambda: start + 31 * 86400)
    assert 'id="login-form"' in client.get(
        "/bot", headers={"Cookie": f"edabalans_admin={token}"},
    ).text
    monkeypatch.setattr(main.time, "time", lambda: start)
    client.cookies.set("edabalans_admin", token, domain=".edabalans.ru", path="/")
    assert 'id="login-form"' not in client.get("/bot").text
    client.cookies.set("edabalans_admin", "legacy-host-cookie", domain="edabalans.ru", path="/")
    assert client.post("/bot-api/logout").status_code == 200
    assert not any(c.name == "edabalans_admin" for c in client.cookies.jar)
    assert 'id="login-form"' in client.get("https://api.edabalans.ru/bot").text


def test_bot_accepts_shared_backend_signature_and_rotation_revokes_it(monkeypatch):
    import base64
    import hashlib
    import hmac

    monkeypatch.setattr(main.settings, "admin_username", "owner@example.com")
    monkeypatch.setattr(main.settings, "admin_password", "contract-test-password")
    payload = base64.urlsafe_b64encode(b"owner@example.com|4000000000").decode().rstrip("=")
    signature = hmac.new(b"contract-test-password", payload.encode(), hashlib.sha256).hexdigest()
    client = TestClient(app, base_url="https://edabalans.ru")
    client.cookies.set("edabalans_admin", f"{payload}.{signature}", domain=".edabalans.ru", path="/")
    assert 'id="login-form"' not in client.get("/bot").text
    monkeypatch.setattr(main.settings, "admin_password", "rotated-contract-password")
    assert 'id="login-form"' in client.get("/bot").text
    assert client.post("/bot-api/login", json={
        "username": "owner@example.com", "password": "contract-test-password",
    }).status_code == 401


def test_bot_independent_host_cookie_stays_host_only(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_username", "owner@example.com")
    monkeypatch.setattr(main.settings, "admin_password", "contract-test-password")
    client = TestClient(app, base_url="https://independent.example")
    response = client.post("/bot-api/login", json={
        "username": "owner@example.com", "password": "contract-test-password",
    })
    assert response.status_code == 200
    assert "Domain=" not in response.headers["set-cookie"]
    assert 'id="login-form"' not in client.get("/bot").text
    assert client.post("/bot-api/logout").status_code == 200
    assert 'id="login-form"' in client.get("/bot").text
