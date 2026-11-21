import os
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from threading import Barrier, BrokenBarrierError

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")

from app.config import get_settings

get_settings.cache_clear()

from app.main import app
from app import timeboard
from app.timeboard_snapshot import snapshot
from app.auth import ADMIN_COOKIE, admin_session_token


@pytest.fixture(autouse=True)
def board_credentials(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "board-owner")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-timeboard-password")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


AUTH = ("board-owner", "test-timeboard-password")


@pytest.mark.parametrize("path", ["/timeboard", "/timeboard/", "/timeboard/app.js", "/timeboard/style.css", "/timeboard/api/state", "/timeboard/api/session"])
def test_timeboard_requires_admin_for_every_entry_point(path):
    client = TestClient(app)
    for auth in [None, ("board-owner", "wrong-password")]:
        response = client.get(path, auth=auth, follow_redirects=False)
        assert response.status_code == 401
        assert "Basic" in response.headers["www-authenticate"]
    client.cookies.set(ADMIN_COOKIE, admin_session_token(AUTH[0], 4102444800))
    assert client.get(path, follow_redirects=False).status_code in (200, 307)



class PageResources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.urls.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.urls.append(values["href"])


def test_timeboard_redirect_and_page_resources_work_with_admin_session() -> None:
    client = TestClient(app)
    client.auth = AUTH
    redirect = client.get("/timeboard", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/timeboard/"

    page = client.get("/timeboard/")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert page.headers["referrer-policy"] == "no-referrer"
    resources = PageResources()
    resources.feed(page.text)
    assert sorted(resources.urls) == ["/assets/site-typography.css", "app.js", "style.css"]
    for url in resources.urls:
        response = client.get(url if url.startswith("/") else f"/timeboard/{url}")
        assert response.status_code == 200
        if not url.startswith("/"):
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
        assert response.headers["content-type"].startswith(
            "text/css" if url.endswith(".css") else ("text/javascript", "application/javascript")
        )


@pytest.mark.parametrize("name", ["README.md", "calendar.json", ".env", "app.js.map", "%2e%2e%2fconfig.py"])
def test_timeboard_cannot_serve_unlisted_files(name: str) -> None:
    assert TestClient(app).get(f"/timeboard/{name}", auth=AUTH).status_code == 404


def test_timeboard_private_read_and_atomic_admin_import(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TIMEBOARD_DB", str(tmp_path / "board.sqlite3"))
    monkeypatch.setenv("ADMIN_USERNAME", "board-owner")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-timeboard-password")
    get_settings.cache_clear()
    client = TestClient(app)
    auth = ("board-owner", "test-timeboard-password")
    headers = {"X-Timeboard-Request": "1"}
    api = "/timeboard/api/"
    operation = {"op": "add", "date": "2026-11-19", "cat": "training", "title": "Растяжка"}
    packet = {"v": 1, "baseRevision": 0, "ops": [operation]}
    try:
        assert client.get(api + "state", auth=auth).json()["entries"] == []
        assert client.get(api + "session").status_code == 401
        assert client.get(api + "session", auth=auth).json() == {"canEdit": True}
        assert client.post(api + "apply", json=packet, headers=headers).status_code == 401
        assert client.post(api + "preview", json=packet, headers=headers).status_code == 401
        assert client.post(api + "apply", json=packet, auth=auth).status_code == 403

        preview = client.post(api + "preview", json=packet, auth=auth, headers=headers)
        assert preview.status_code == 200
        assert preview.json()["changes"][0]["after"]["title"] == operation["title"]
        assert client.get(api + "state", auth=auth).json()["entries"] == []

        invalid = {**packet, "ops": [operation, {"op": "update", "id": "missing", "title": "Чужая запись"}]}
        assert client.post(api + "apply", json=invalid, auth=auth, headers=headers).status_code == 422
        assert client.get(api + "state", auth=auth).json()["revision"] == 0
        credentials_in_url = {**packet, "ops": [{**operation, "url": "https://:demo@example.org/"}]}
        assert client.post(api + "apply", json=credentials_in_url, auth=auth, headers=headers).status_code == 422

        result = client.post(api + "apply", json=packet, auth=auth, headers=headers)
        assert result.status_code == 200
        committed = result.json()
        assert committed["revision"] == committed["applied"] == 1
        assert client.post(api + "apply", json=packet, auth=auth, headers=headers).status_code == 409
        anonymous = TestClient(app).get(api + "state", auth=auth)
        assert anonymous.headers["cache-control"] == "no-store"
        entry = anonymous.json()["entries"][0]
        assert entry["title"] == operation["title"]
        assert committed["changes"] == [{"op": "add", "before": None, "after": entry}]

        update = {**packet, "baseRevision": 1, "ops": [{"op": "update", "id": entry["id"], "flag": "blue"}]}
        changed_entry = {**entry, "flag": "blue"}
        updated = client.post(api + "apply", json=update, auth=auth, headers=headers).json()
        assert updated["revision"] == 2
        assert updated["changes"] == [{"op": "update", "before": entry, "after": changed_entry}]
        assert client.get(api + "state", auth=auth).json()["entries"][0] == changed_entry
        remove = {**packet, "baseRevision": 2, "ops": [{"op": "remove", "id": entry["id"]}]}
        removed = client.post(api + "apply", json=remove, auth=auth, headers=headers).json()
        assert removed["revision"] == 3
        assert removed["changes"] == [{"op": "remove", "before": changed_entry, "after": None}]
        assert client.get(api + "state", auth=auth).json()["entries"] == []

        restore = {**packet, "baseRevision": 3, "ops": [{"op": "add", **removed["changes"][0]["before"]}]}
        assert client.post(api + "apply", json=restore, auth=auth, headers=headers).status_code == 200
        assert client.get(api + "state", auth=auth).json()["entries"] == [changed_entry]
        duplicate = {**restore, "baseRevision": 4}
        assert client.post(api + "apply", json=duplicate, auth=auth, headers=headers).status_code == 422
        wrong_category = {**duplicate, "ops": [{**operation, "sonyaRole": "weekly"}]}
        assert client.post(api + "apply", json=wrong_category, auth=auth, headers=headers).status_code == 422
        marker = {**operation, "cat": "sonya", "sonyaRole": "indicator"}
        invalid_marker = {**duplicate, "ops": [marker]}
        assert client.post(api + "apply", json=invalid_marker, auth=auth, headers=headers).status_code == 422
        schedule = {**operation, "cat": "sonya", "sonyaRole": "weekly"}
        competition = {**operation, "cat": "competitions", "title": "Вариант старта"}
        popup_packet = {**duplicate, "ops": [schedule, {**marker, "phase": "period"}, competition]}
        assert client.post(api + "apply", json=popup_packet, auth=auth, headers=headers).status_code == 200
        assert any(
            e["cat"] == "competitions" and e["title"] == competition["title"]
            for e in client.get(api + "state", auth=auth).json()["entries"]
        )
        assert {e["sonyaRole"]: e["phase"] for e in client.get(api + "state", auth=auth).json()["entries"]} == {
            "": "", "weekly": "", "indicator": "period",
        }

        gate = Barrier(2)
        prepare = timeboard.prepare

        def hold_first_revision(packet, revision, entries):
            checked = prepare(packet, revision, entries)
            try:
                gate.wait(timeout=0.4)
            except BrokenBarrierError:
                pass
            return checked

        monkeypatch.setattr(timeboard, "prepare", hold_first_revision)

        def write(title):
            body = {**packet, "baseRevision": 5, "ops": [{**operation, "title": title}]}
            return TestClient(app).post(api + "apply", json=body, auth=auth, headers=headers).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(write, ["Первая запись", "Вторая запись"])) == [200, 409]
        final_state = client.get(api + "state", auth=auth).json()
        assert final_state["revision"] == 6
        assert len(final_state["entries"]) == 5
        backup = tmp_path / "restored.sqlite3"
        with backup.open("wb") as output:
            snapshot(tmp_path / "board.sqlite3", output)
        monkeypatch.setenv("TIMEBOARD_DB", str(backup))
        assert client.get(api + "state", auth=auth).json() == final_state
    finally:
        get_settings.cache_clear()
