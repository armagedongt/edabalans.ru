from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.article_markup import inline_markdown, safe_href
from app.managed_documents import active_document, ensure_seed_document, publish_document
from app.models import ManagedDocumentVersion


ROOT = Path(__file__).resolve().parents[2]
CONTENT_ROOT = ROOT / "content" / "public-site" / "homepage"
DOCUMENT_TYPE = "public-site-homepage"
DOCUMENT_KEY = "homepage"
SCHEMA_VERSION = 1
KEY = r"[a-z0-9][a-z0-9.-]*"
SOURCE_SLOT = re.compile(rf"<!-- homepage:({KEY}) -->\n([\s\S]*?)\n<!-- /homepage:\1 -->")
TEMPLATE_SLOT = re.compile(rf"<!-- homepage-slot:({KEY}) -->")
INLINE_COMPONENT = re.compile(r"homepage_inline\(([a-z0-9-]+)\)")
RAW_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
ENTITY = re.compile(r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]+);")


def definitions() -> tuple[list[dict], str]:
    mapping = json.loads((CONTENT_ROOT / "block-map.json").read_text(encoding="utf-8"))
    slots = mapping["textSlots"]
    digest = hashlib.sha256(json.dumps(slots, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return slots, digest


class InlineValidator(HTMLParser):
    """The homepage keeps its original inline vocabulary, never a second layout."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"strong", "em", "del", "mark", "small", "span", "a", "br"}:
            raise HTTPException(422, "В тексте главной разрешена только строчная разметка")
        attributes = dict(attrs)
        if tag == "a" and not safe_href(attributes.get("href") or ""):
            raise HTTPException(422, "Недопустимая ссылка в тексте главной")
        if tag != "br":
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            raise HTTPException(422, "Незакрытая строчная разметка в тексте главной")


def compile_inline(source: str, definition: dict) -> str:
    protected: list[str] = []

    def protect(value: str) -> str:
        protected.append(value)
        return f"\x00{len(protected) - 1}\x00"

    components = definition.get("inlineComponents", {})
    component_names = INLINE_COMPONENT.findall(source)
    if sorted(component_names) != sorted(components):
        raise HTTPException(422, f"Сохраните встроенные элементы поля {definition['key']}")
    source = INLINE_COMPONENT.sub(lambda match: protect(match.group(0)), source)
    if RAW_TAG.findall(source) != definition["requiredMarkup"]:
        raise HTTPException(422, f"Сохраните оформление поля {definition['key']}; структуру меняют через Codex")

    def protect_tag(match: re.Match[str]) -> str:
        if match.group(0) not in definition["requiredMarkup"]:
            raise HTTPException(422, "Произвольный HTML в тексте главной запрещён")
        return protect(match.group(0))

    source = RAW_TAG.sub(protect_tag, source)
    if re.search(r"<\s*[!/a-zA-Z]|-->|homepage_inline\(", source):
        raise HTTPException(422, "Некорректная вставка в тексте главной")
    # Preserve original entities and literal quotation marks byte for byte.
    source = ENTITY.sub(lambda match: protect(match.group(0)), source)
    try:
        rendered = inline_markdown(source)
        # Original text-node quotes stay literal; generated href attributes stay escaped.
        rendered = re.sub(r"(<[^>]*>)|([^<]+)", lambda match: match.group(1) or
                          match.group(2).replace("&quot;", '"').replace("&#x27;", "'"), rendered)
    except ValueError as exc:
        raise HTTPException(422, "Некорректная ссылка в тексте главной") from exc
    for index, value in enumerate(protected):
        rendered = rendered.replace(f"\x00{index}\x00", value)
    validator = InlineValidator()
    # Locked buttons belong to the template, not to the editable HTML vocabulary.
    validator.feed(INLINE_COMPONENT.sub("", rendered))
    validator.close()
    if validator.stack:
        raise HTTPException(422, "Незакрытая строчная разметка в тексте главной")
    return INLINE_COMPONENT.sub(lambda match: components[match.group(1)], rendered)


def compile_homepage(markdown: str) -> dict:
    if not markdown.strip() or len(markdown.encode("utf-8")) > 500_000 or "\x00" in markdown:
        raise HTTPException(422, "Некорректный Markdown главной")
    slots, schema_hash = definitions()
    known = {item["key"]: item for item in slots}
    fragments: dict[str, str] = {}
    for match in SOURCE_SLOT.finditer(markdown.replace("\r", "")):
        key, source = match.groups()
        if key not in known or key in fragments or not source.strip():
            raise HTTPException(422, "Неизвестное, повторяющееся или пустое поле главной")
        fragments[key] = compile_inline(source, known[key])
    remainder = SOURCE_SLOT.sub("", markdown.replace("\r", ""))
    if any(line.strip() and not re.fullmatch(r"#{1,2} [^<>]+", line) for line in remainder.splitlines()):
        raise HTTPException(422, "Текст главной должен находиться внутри служебных полей")
    if set(fragments) != set(known):
        raise HTTPException(422, "В Markdown главной отсутствуют обязательные поля")
    return {"schemaVersion": SCHEMA_VERSION, "schema_hash": schema_hash,
            "markdown": markdown.replace("\r", ""), "fragments": fragments}


def active_homepage(db: Session) -> ManagedDocumentVersion:
    current = active_document(db, DOCUMENT_TYPE, DOCUMENT_KEY)
    if current is not None:
        return current
    return ensure_seed_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
                                schema_version=SCHEMA_VERSION,
                                payload=compile_homepage((CONTENT_ROOT / "homepage.md").read_text(encoding="utf-8")))


def serialize_homepage(version: ManagedDocumentVersion) -> dict:
    return {"markdown": version.payload["markdown"], "version": version.version_no,
            "updated_at": version.created_at.isoformat(), "updated_by": version.created_by,
            "schema_hash": version.payload["schema_hash"]}


def publish_homepage(db: Session, *, markdown: str, expected_version: int, admin: str) -> ManagedDocumentVersion:
    active_homepage(db)
    return publish_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
                            schema_version=SCHEMA_VERSION, payload=compile_homepage(markdown),
                            expected_version=expected_version, admin=admin)


def render_homepage(db: Session, template: str) -> str:
    document = active_homepage(db)
    slots, schema_hash = definitions()
    keys = TEMPLATE_SLOT.findall(template)
    if (document.payload["schema_hash"] != schema_hash or len(keys) != len(set(keys))
            or set(keys) != {slot["key"] for slot in slots}):
        raise HTTPException(503, "Редакционная карта главной не соответствует шаблону")
    return TEMPLATE_SLOT.sub(lambda match: document.payload["fragments"][match.group(1)], template)
