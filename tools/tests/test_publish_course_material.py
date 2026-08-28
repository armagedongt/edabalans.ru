import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import URLError

import pytest

from tools import publish_course_material as publisher


def write_gate(tmp_path, material):
    pack = tmp_path / "pack.json"
    pack.write_text('{"content_contract": {}}', encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "schema_version": "author-validation-v1",
        "status": "pass",
        "pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
        "draft_sha256": hashlib.sha256(material.read_bytes()).hexdigest(),
        "review_sha256": None,
        "pending_manual_reviews": [],
        "fact_review_expires_at": None,
    }), encoding="utf-8")
    return pack, report


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
    pack, report = write_gate(tmp_path, material)
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
            "--pack", str(pack),
            "--validation-report", str(report),
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


def test_publish_gate_rejects_stale_draft_before_api(monkeypatch, tmp_path) -> None:
    material = tmp_path / "material.md"
    material.write_text("Проверенная версия", encoding="utf-8")
    pack, report = write_gate(tmp_path, material)
    material.write_text("Изменённая версия", encoding="utf-8")
    calls = []
    monkeypatch.setattr(publisher, "api_request", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(sys, "argv", [
        "publish_course_material.py", "publish", "day-01-article-02", str(material),
        "--pack", str(pack), "--validation-report", str(report),
    ])
    with pytest.raises(SystemExit, match="материал изменился"):
        publisher.main()
    assert calls == []


def test_publish_gate_rechecks_fact_review_expiry(tmp_path) -> None:
    material = tmp_path / "material.md"
    material.write_text("Проверенная версия", encoding="utf-8")
    pack, report = write_gate(tmp_path, material)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["fact_review_expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match="fact review старше 24 часов"):
        publisher.verify_publish_gate(material, pack, report)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update(schema_version="unknown"), "неизвестный формат"),
        (lambda payload: payload.update(status="needs_fix"), "status=pass"),
        (lambda payload: payload.update(pack_sha256="changed"), "pack изменился"),
        (
            lambda payload: payload.update(
                pending_manual_reviews=[{"id": "semantic_facts"}], review_sha256=None
            ),
            "manual review",
        ),
    ],
)
def test_publish_gate_rejects_invalid_contract_branches(tmp_path, mutation, message) -> None:
    material = tmp_path / "material.md"
    material.write_text("Проверенная версия", encoding="utf-8")
    pack, report = write_gate(tmp_path, material)
    payload = json.loads(report.read_text(encoding="utf-8"))
    mutation(payload)
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match=message):
        publisher.verify_publish_gate(material, pack, report)


def test_put_network_error_requires_get_before_retry(monkeypatch) -> None:
    monkeypatch.setenv("EDABALANS_ADMIN_USERNAME", "writer@example.test")
    monkeypatch.setenv("EDABALANS_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(publisher, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("timeout")))
    args = argparse.Namespace(api_url="https://api.example.test", timeout=1, username="")
    with pytest.raises(SystemExit, match="Сначала выполните.*get STEP_ID"):
        publisher.api_request(args, "PUT", "/material", {"content": "text"})


def test_put_timeout_requires_get_before_retry(monkeypatch) -> None:
    monkeypatch.setenv("EDABALANS_ADMIN_USERNAME", "writer@example.test")
    monkeypatch.setenv("EDABALANS_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(
        publisher,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("slow")),
    )
    args = argparse.Namespace(api_url="https://api.example.test", timeout=1, username="")
    with pytest.raises(SystemExit, match="Сначала выполните.*get STEP_ID"):
        publisher.api_request(args, "PUT", "/material", {"content": "text"})


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
