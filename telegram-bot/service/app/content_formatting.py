from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import urlparse


SUPPORTED_SOURCE_FORMATS = {"telegram_html"}
PLACEHOLDER_PREFIXES = (
    "[Добавьте ",
    "[Полезный ",
    "[Сильный ",
    "[Второй ",
    "[Пост ",
    "Здесь будет ",
    "Небольшой полезный материал",
    "Вы начали итоговое саморевью. Здесь будет ",
    "Прошло несколько дней после саморевью. Здесь будет ",
    "Неделя после саморевью завершена. Здесь будет ",
)
ALLOWED_TAGS = {
    "a", "b", "blockquote", "code", "del", "em", "i", "ins", "pre",
    "s", "span", "strike", "strong", "tg-emoji", "tg-spoiler", "u",
}
TEMPLATE_VALUE = re.compile(r"{{\s*[a-zA-Z0-9_]+\s*}}")
TEMPLATE_VARIABLE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
INVALID_HTML_ENTITY = re.compile(r"&(?!#(?:[0-9]+|x[0-9a-fA-F]+);|(?:lt|gt|amp|quot);)")


def is_placeholder_text(value: str | None) -> bool:
    text = (value or "").lstrip()
    return not text or text.startswith(PLACEHOLDER_PREFIXES) or "\n\nЗдесь будет " in text


def _safe_url(value: str) -> bool:
    value = value.strip()
    if TEMPLATE_VALUE.fullmatch(value):
        return True
    parsed = urlparse(value)
    return parsed.scheme.lower() in {"http", "https", "tg", "mailto", "tel"}


class _TelegramHtmlValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value for key, value in attrs}
        if tag not in ALLOWED_TAGS:
            self.errors.append(f"недопустимый тег <{tag}>")
            return
        allowed_attributes: set[str] = set()
        if tag == "a":
            allowed_attributes = {"href"}
            if not _safe_url(attributes.get("href") or ""):
                self.errors.append("у ссылки <a> отсутствует допустимый href")
        elif tag == "span":
            allowed_attributes = {"class"}
            if attributes.get("class") != "tg-spoiler":
                self.errors.append("у <span> разрешён только class=\"tg-spoiler\"")
        elif tag == "blockquote":
            allowed_attributes = {"expandable"}
        elif tag == "tg-emoji":
            allowed_attributes = {"emoji-id"}
            if not attributes.get("emoji-id"):
                self.errors.append("у <tg-emoji> обязателен emoji-id")
        elif tag == "code" and self.stack and self.stack[-1] == "pre":
            allowed_attributes = {"class"}
            language = attributes.get("class") or ""
            if language and not language.startswith("language-"):
                self.errors.append("внутри <pre> class у <code> должен начинаться с language-")
        unexpected = set(attributes) - allowed_attributes
        if unexpected:
            self.errors.append(f"у <{tag}> недопустимые атрибуты: {', '.join(sorted(unexpected))}")
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack:
            self.errors.append(f"закрывающий тег </{tag}> не имеет начала")
            return
        expected = self.stack.pop()
        if expected != tag:
            self.errors.append(f"ожидался </{expected}>, получен </{tag}>")

    def handle_comment(self, data: str) -> None:
        self.errors.append("HTML-комментарии разрешены только в служебной шапке файла, не в тексте сообщения")


class _TelegramHtmlLinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = {key.lower(): value for key, value in attrs}
        if attributes.get("href"):
            self.links.append(str(attributes["href"]))


def validate_telegram_html(source: str) -> None:
    if INVALID_HTML_ENTITY.search(source or ""):
        raise ValueError(
            "символ & должен быть записан как &amp;; разрешены числовые сущности и &lt;, &gt;, &amp;, &quot;"
        )
    parser = _TelegramHtmlValidator()
    try:
        parser.feed(source or "")
        parser.close()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"не удалось разобрать HTML: {exc}") from exc
    if parser.stack:
        parser.errors.append(f"не закрыты теги: {', '.join(parser.stack)}")
    if parser.errors:
        raise ValueError("; ".join(parser.errors))


def telegram_html_links(source: str) -> list[str]:
    parser = _TelegramHtmlLinkCollector()
    parser.feed(source or "")
    parser.close()
    return parser.links


def template_value_for_source(value: str, source_format: str) -> str:
    return value


def replace_template_values(source: str, values: dict[str, str]) -> str:
    return TEMPLATE_VARIABLE.sub(
        lambda match: values.get(match.group(1), match.group(0)),
        source or "",
    )


def content_body_for_telegram(content: Any) -> str:
    return getattr(content, "body_source", "") or ""


def content_is_runtime_ready(content: Any) -> bool:
    ready = (
        getattr(content, "status", None) == "published"
        and getattr(content, "editorial_status", None) == "approved"
        and getattr(content, "source_format", None) == "telegram_html"
    )
    if not ready:
        return False
    try:
        validate_telegram_html(getattr(content, "body_source", "") or "")
    except ValueError:
        return False
    return True
