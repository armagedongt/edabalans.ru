import argparse
import base64
import json
import sys

from tools import publish_course_material as publisher


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_api_request_uses_basic_auth_without_password_in_url(monkeypatch) -> None:
    monkeypatch.setenv("EDABALANS_ADMIN_USERNAME", "writer@example.test")
    monkeypatch.setenv("EDABALANS_ADMIN_PASSWORD", "secret-value")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"ok": True})

    monkeypatch.setattr(publisher, "urlopen", fake_urlopen)
    args = argparse.Namespace(
        api_url="https://api.example.test",
        timeout=17,
        username="",
    )
    result = publisher.api_request(
        args,
        "PUT",
        "/admin/api/courses/masterclass-21/materials/day-01-article-02",
        {"content": "Текст"},
    )

    request = captured["request"]
    expected = base64.b64encode(
        b"writer@example.test:secret-value"
    ).decode()
    assert result == {"ok": True}
    assert request.full_url.startswith("https://api.example.test/admin/api/")
    assert "secret-value" not in request.full_url
    assert request.headers["Authorization"] == f"Basic {expected}"
    assert json.loads(request.data.decode("utf-8")) == {"content": "Текст"}
    assert captured["timeout"] == 17


def test_publish_reads_utf8_and_fetches_expected_version(monkeypatch, tmp_path, capsys) -> None:
    material = tmp_path / "material.md"
    material.write_text("## Заголовок\n\nТекст с ёлкой.", encoding="utf-8")
    calls = []

    def fake_api_request(args, method, path, payload=None):
        calls.append((method, path, payload))
        if method == "GET":
            return {"version": 4}
        return {"ok": True, "version": 5, "html": "<h2>Заголовок</h2>"}

    monkeypatch.setattr(publisher, "api_request", fake_api_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_course_material.py",
            "publish",
            "day-01-article-02",
            str(material),
        ],
    )

    assert publisher.main() == 0
    assert calls[0][0] == "GET"
    assert calls[1][0] == "PUT"
    assert calls[1][2] == {
        "expected_version": 4,
        "content": "## Заголовок\n\nТекст с ёлкой.",
        "format": "markdown",
    }
    assert json.loads(capsys.readouterr().out)["version"] == 5


def test_restore_fetches_current_version_and_targets_requested_history(monkeypatch) -> None:
    calls = []

    def fake_api_request(args, method, path, payload=None):
        calls.append((method, path, payload))
        return {"version": 7} if method == "GET" else {"ok": True, "version": 8}

    monkeypatch.setattr(publisher, "api_request", fake_api_request)
    monkeypatch.setattr(
        sys,
        "argv",
        ["publish_course_material.py", "restore", "day-01-article-02", "3"],
    )

    assert publisher.main() == 0
    assert calls[1] == (
        "POST",
        "/admin/api/courses/masterclass-21/materials/day-01-article-02/versions/3/restore",
        {"expected_version": 7},
    )
