"""Compile the actual service email originals without changing delivery logic."""
from __future__ import annotations

from pathlib import Path
import re
from string import Template


ROOT = Path(__file__).resolve().parents[2] / "content/service-messages/email"
SCHEMAS = {
    "tilda-transfer": {"subject": set(), "text": {"name", "account_url", "email", "password", "access_text", "upgrade_text"}, "unconfirmed": set(), "upgrade": set()},
    "account-onboarding": {"subject_paid": set(), "subject_free": set(), "intro_paid": set(), "intro_free": set()},
    "account-direct": {
        "text": {"intro", "email", "password", "account_url"},
        "html": {"intro_html", "email_html", "password_html", "account_url_html"},
    },
    "account-messenger": {
        "text": {"intro", "messenger_links", "expiry_notice"},
        "html": {"intro", "buttons", "expiry_notice"},
        "expiry": {"deadline"}, "telegram_link": {"url"}, "max_link": {"url"},
        "telegram_button_html": {"url"}, "max_button_html": {"url"},
    },
    "login-code": {"subject": set(), "text": {"code"}},
    "renewal-failed": {"subject": set(), "text": {"amount", "page"}, "html": {"amount", "page"}},
}


def source_path(code: str) -> str:
    if code not in SCHEMAS:
        raise KeyError("Неизвестный шаблон письма")
    return f"content/service-messages/email/{code}.md"


def compile_source(code: str, source: str) -> dict[str, Template]:
    source_path(code)
    if len(source.encode("utf-8")) > 100_000 or "\0" in source:
        raise ValueError("Недопустимый размер или символ в шаблоне письма")
    source = source.replace("\r\n", "\n")
    matches = list(re.finditer(r"(?m)^## ([a-z0-9_]+)\n\n```(?:text|html)\n(.*?)\n```(?=\n|$)", source, re.S))
    sections = {}
    for match in matches:
        name, value = match.groups()
        if name in sections:
            raise ValueError("Повторяется раздел шаблона: " + name)
        sections[name] = Template(value)
    if sections.keys() != SCHEMAS[code].keys():
        raise ValueError("Нужны точные разделы шаблона: " + ", ".join(SCHEMAS[code]))
    for name, template in sections.items():
        if not template.is_valid() or set(template.get_identifiers()) != SCHEMAS[code][name]:
            raise ValueError("Сохраните переменные раздела " + name + ": " + ", ".join(sorted(SCHEMAS[code][name])))
        if name.startswith("subject") and (not template.template.strip() or re.search(r"[\x00-\x1f\x7f]", template.template)):
            raise ValueError("Тема письма должна быть одной непустой строкой")
    return sections


def render_section(code: str, section: str, /, **values: str) -> str:
    templates = compile_source(code, (ROOT / (code + ".md")).read_text(encoding="utf-8"))
    return templates[section].substitute(values)
