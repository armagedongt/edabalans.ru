import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.account_onboarding_service import account_access_email
from app.app_auth import send_login_code
from app.auth import require_admin
from app.config import Settings
from app.robokassa_subscription_service import _failed_charge_email
from app import service_email_templates as templates
from app import service_email_editorial_routes as routes


ORIGINALS = json.loads((Path(__file__).parent / "fixtures/service_email_originals.json").read_text(encoding="utf-8"))


def settings():
    return Settings(smtp_host="smtp.example.test", smtp_use_ssl=True,
                    smtp_from_email="sender@example.test", smtp_from_name="Test",
                    smtp_reply_to="reply@example.test", account_public_url="https://example.test/lk?x=1&y=2")


def content(message):
    return {"subject": str(message["Subject"]),
            "text": message.get_body(preferencelist=("plain",)).get_content(),
            "html": message.get_body(preferencelist=("html",)).get_content() if message.is_multipart() else None}


@pytest.mark.parametrize("paid", [True, False])
@pytest.mark.parametrize("direct,links", [
    (True, {}), (False, {"telegram": "https://example.test/tg", "max": "https://example.test/max"}),
    (False, {"telegram": "https://example.test/tg"}), (False, {}),
])
def test_access_email_subject_plain_html_match_original_outputs(paid, direct, links):
    message = account_access_email(email="person@example.test", links=links,
        expires_at=datetime(2026, 10, 8, 12, tzinfo=timezone.utc), settings=settings(),
        payment_completed=paid, password="A<&b" if direct else None)
    assert content(message) == ORIGINALS[f"account-{paid}-{direct}-{len(links)}"]
    assert message["To"] == "person@example.test"
    assert message["Reply-To"] == "reply@example.test"


def test_subscription_failed_email_matches_original_outputs():
    message = _failed_charge_email(SimpleNamespace(amount=Decimal("1490.00"), email_normalized="person@example.test"), settings())
    assert content(message) == ORIGINALS["renewal"]
    assert message["To"] == "person@example.test"


def test_login_code_email_matches_original_and_same_smtp_delivery():
    with patch("app.app_auth.smtplib.SMTP_SSL") as smtp:
        send_login_code("person@example.test", "123456", settings())
    message = smtp.return_value.send_message.call_args.args[0]
    assert content(message) == ORIGINALS["login"]
    assert message["To"] == "person@example.test"
    smtp.return_value.send_message.assert_called_once()


def test_senders_read_changed_original_file_instead_of_hardcoded_body(tmp_path, monkeypatch):
    source = (templates.ROOT / "login-code.md").read_text(encoding="utf-8")
    (tmp_path / "login-code.md").write_text(source.replace("Код входа в приложение ЕдаБаланс:", "Ваш код:"), encoding="utf-8")
    monkeypatch.setattr(templates, "ROOT", tmp_path)
    with patch("app.app_auth.smtplib.SMTP_SSL") as smtp:
        send_login_code("person@example.test", "123456", settings())
    assert smtp.return_value.send_message.call_args.args[0].get_content().startswith("Ваш код: 123456")


@pytest.mark.parametrize("change", [
    lambda text: text.replace("${code}", "${unknown}"),
    lambda text: text.replace("${code}", ""),
    lambda text: text.replace("${code}", "${"),
    lambda text: text.replace("## text", "## other"),
    lambda text: text.replace("Код входа в ЕдаБаланс\n```", "Тема\nBcc: x@example.test\n```"),
])
def test_compiler_rejects_missing_unknown_fields_and_header_injection(change):
    source = (templates.ROOT / "login-code.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        templates.compile_source("login-code", change(source))


def test_only_fixed_template_paths_allowed():
    with pytest.raises(KeyError):
        routes.ServiceEmailContentEditor().source_path("../../app/config.py")


def test_runtime_original_path_and_hash_report_actual_sender_source():
    repo = Path(__file__).resolve().parents[2]
    assert templates.ROOT == repo / "content/service-messages/email"
    with patch.object(routes, "editor") as editor:
        editor.return_value.load.return_value = {"main": {"sha": "a" * 40}}
        response = routes.email_source("login-code", "owner")
    actual = (templates.ROOT / "login-code.md").read_text(encoding="utf-8")
    assert response["runtime_source"] == {
        "path": "content/service-messages/email/login-code.md",
        "sha256": hashlib.sha256(actual.encode("utf-8")).hexdigest(),
    }


def test_editorial_router_requires_admin_and_reuses_guarded_editor_without_sending():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    assert client.get("/admin/api/editorial/service-emails").status_code == 401
    app.dependency_overrides[require_admin] = lambda: "owner"
    with patch.object(routes, "editor") as editor, patch("app.account_onboarding_service._send_message") as send:
        editor.return_value.save_draft.return_value = {"ok": True}
        editor.return_value.publish.return_value = {"ok": True}
        assert client.get("/admin/api/editorial/service-emails").json()["templates"]
        invalid = client.get("/admin/api/editorial/service-emails/not-allowed")
        assert invalid.status_code == 404
        draft = client.put("/admin/api/editorial/service-emails/login-code/draft", json={
            "content": "source", "expected_main_sha": "a" * 40, "expected_draft_sha": None})
        assert draft.status_code == 200
        publish = client.post("/admin/api/editorial/service-emails/login-code/publish", json={
            "expected_main_sha": "a" * 40, "expected_draft_sha": "b" * 40})
        assert publish.status_code == 200
        assert publish.headers["cache-control"] == "private, no-store"
        editor.return_value.publish.assert_called_once_with("login-code", expected_main_sha="a" * 40,
            expected_draft_sha="b" * 40, admin="owner")
        send.assert_not_called()


def test_editorial_api_exposes_conflicting_sha_without_retrying_or_sending():
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_admin] = lambda: "owner"
    with patch.object(routes, "editor") as editor:
        editor.return_value.publish.side_effect = HTTPException(409, "conflict")
        response = TestClient(app).post("/admin/api/editorial/service-emails/login-code/publish", json={
            "expected_main_sha": "a" * 40, "expected_draft_sha": "b" * 40})
        assert response.status_code == 409
        assert editor.return_value.publish.call_count == 1


@pytest.mark.parametrize("code,direct,replacements", [
    ("account-onboarding", True, [
        ("Доступ в личный кабинет", "Ваш новый доступ"),
        ("Оплата прошла успешно.", "Оплата подтверждена."),
    ]),
    ("account-direct", True, [
        ("Доступ в личный кабинет готов", "Ваш кабинет готов к работе"),
    ]),
    ("account-messenger", False, [
        ("Это техническое письмо, я не увижу ответ.", "Ответ на это письмо не читается."),
    ]),
    ("renewal-failed", None, [
        ("Не удалось продлить сопровождение", "Продление не состоялось"),
        ("Новых автоматических попыток по этой карте не будет.", "Автоматически эту карту больше не списываем."),
    ]),
])
def test_actual_account_and_renewal_senders_emit_edited_originals_exactly(tmp_path, monkeypatch, code, direct, replacements):
    for source in templates.ROOT.glob("*.md"):
        (tmp_path / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    source_path = tmp_path / (code + ".md")
    updated = source_path.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in updated
        updated = updated.replace(old, new)
    source_path.write_text(updated, encoding="utf-8")
    monkeypatch.setattr(templates, "ROOT", tmp_path)
    if direct is None:
        message = _failed_charge_email(SimpleNamespace(amount=Decimal("1490.00"),
                                      email_normalized="person@example.test"), settings())
        expected = dict(ORIGINALS["renewal"])
    else:
        links = {} if direct else {"telegram": "https://example.test/tg", "max": "https://example.test/max"}
        message = account_access_email(email="person@example.test", links=links,
            expires_at=datetime(2026, 10, 8, 12, tzinfo=timezone.utc), settings=settings(),
            payment_completed=True, password="A<&b" if direct else None)
        expected = dict(ORIGINALS[f"account-True-{direct}-{len(links)}"])
    for part, value in expected.items():
        if value is not None:
            for old, new in replacements:
                if code == "account-onboarding" and old == "Доступ в личный кабинет" and part != "subject":
                    continue
                value = value.replace(old, new)
            expected[part] = value
    assert content(message) == expected
    assert content(message) != ORIGINALS["renewal" if direct is None else f"account-True-{direct}-{len(links)}"]
    assert message["To"] == "person@example.test"
