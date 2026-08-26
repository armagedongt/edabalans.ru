from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

from fastapi import HTTPException


ALLOWED_TAGS = {
    "h1", "h2", "h3", "p", "div", "ul", "ol", "li", "strong", "em",
    "a", "blockquote", "aside", "img", "br", "hr",
}
COURSE_TAGS = ALLOWED_TAGS | {"figure", "figcaption"}
VOID_TAGS = {"img", "br", "hr"}
BLOCKED_TAGS = {"script", "style", "iframe", "object", "svg", "math"}


def safe_href(value: str) -> bool:
    cleaned = value.strip()
    if cleaned.startswith("//") or any(ord(character) < 32 for character in cleaned):
        return False
    return urlparse(cleaned).scheme in {"", "http", "https", "mailto"}


def safe_image_src(value: str, *, allow_relative: bool = False) -> bool:
    cleaned = value.strip()
    if cleaned.startswith("//") or any(ord(character) < 32 for character in cleaned):
        return False
    if allow_relative and cleaned.startswith("/"):
        return True
    parsed = urlparse(cleaned)
    return parsed.scheme == "https" and bool(parsed.netloc)


class ArticleSanitizer(HTMLParser):
    def __init__(self, *, allow_h1: bool, course_semantics: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.allow_h1 = allow_h1
        self.course_semantics = course_semantics
        self.parts: list[str] = []
        self.blocked_depth = 0
        self.disallowed_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS:
            self.blocked_depth += 1
            return
        allowed_tags = COURSE_TAGS if self.course_semantics else ALLOWED_TAGS
        if self.blocked_depth or tag not in allowed_tags:
            return
        if tag == "h1" and not self.allow_h1:
            self.disallowed_h1 = True
            return
        rendered_attrs = ""
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            if href and safe_href(href):
                rendered_attrs = f' href="{escape(href.strip(), quote=True)}"'
                if self.course_semantics:
                    rendered_attrs += ' target="_blank" rel="noopener"'
        elif tag == "img":
            src = next((value for name, value in attrs if name.lower() == "src"), None)
            if not src or not safe_image_src(
                src, allow_relative=self.course_semantics
            ):
                return
            alt = next((value for name, value in attrs if name.lower() == "alt"), "") or ""
            rendered_attrs = (
                f' src="{escape(src.strip(), quote=True)}"'
                f' alt="{escape(alt[:500], quote=True)}"'
            )
            if self.course_semantics:
                rendered_attrs += ' loading="lazy"'
        elif tag == "aside" and self.course_semantics:
            rendered_attrs = ' class="editorial-note"'
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS or self.blocked_depth:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if tag == "h1" and not self.allow_h1:
            return
        allowed_tags = COURSE_TAGS if self.course_semantics else ALLOWED_TAGS
        if not self.blocked_depth and tag in allowed_tags and tag not in VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(escape(data))


def sanitize_article_html(
    value: str, *, allow_h1: bool = True, course_semantics: bool = False
) -> str:
    parser = ArticleSanitizer(
        allow_h1=allow_h1, course_semantics=course_semantics
    )
    parser.feed(value)
    parser.close()
    if parser.disallowed_h1:
        raise HTTPException(
            status_code=422,
            detail="Главный заголовок хранится в карточке материала; удалите h1 из текста статьи",
        )
    result = "".join(parser.parts).strip()
    if not result or (not article_plain_text(result).strip() and "<img " not in result):
        raise HTTPException(status_code=422, detail="Текст страницы не может быть пустым")
    return result


def inline_markdown(value: str) -> str:
    rendered = escape(value)
    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+|/(?!/)[^\s)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        rendered,
    )
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered)
    return rendered


def markdown_to_article_html(
    source: str, *, strip_source_metadata: bool = False
) -> str:
    lines = str(source or "").replace("\r", "").split("\n")
    output: list[str] = []
    active_list = ""

    def end_list() -> None:
        nonlocal active_list
        if active_list:
            output.append(f"</{active_list}>")
            active_list = ""

    for raw in lines:
        line = raw.strip()
        if not line or (
            strip_source_metadata
            and (line.startswith("Статус:") or line.startswith("Источник:"))
        ):
            end_list()
            continue
        if line.startswith("# "):
            continue
        if line.startswith("### "):
            end_list()
            output.append(f"<h3>{inline_markdown(line[4:])}</h3>")
            continue
        if line.startswith("## "):
            end_list()
            output.append(f"<h2>{inline_markdown(line[3:])}</h2>")
            continue
        if line.startswith("> "):
            end_list()
            output.append(f"<blockquote>{inline_markdown(line[2:])}</blockquote>")
            continue
        image = re.fullmatch(
            r'!\[([^\]]*)\]\((https://[^\s)]+|/(?!/)[^\s)]+)(?:\s+"([^"]*)")?\)',
            line,
        )
        if image:
            end_list()
            alt, src, caption = image.groups()
            figure = (
                f'<figure><img src="{escape(src, quote=True)}" '
                f'alt="{escape(alt, quote=True)}" loading="lazy">'
            )
            if caption:
                figure += f"<figcaption>{escape(caption)}</figcaption>"
            output.append(figure + "</figure>")
            continue
        bullet = re.match(r"^[-*] (.+)", line)
        numbered = re.match(r"^\d+[.)] (.+)", line)
        if bullet or numbered:
            wanted = "ul" if bullet else "ol"
            if active_list != wanted:
                end_list()
                active_list = wanted
                output.append(f"<{active_list}>")
            output.append(f"<li>{inline_markdown((bullet or numbered).group(1))}</li>")
            continue
        end_list()
        output.append(f"<p>{inline_markdown(line)}</p>")
    end_list()
    return sanitize_article_html(
        "".join(output), allow_h1=False, course_semantics=True
    )


class PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def article_plain_text(value: str) -> str:
    parser = PlainTextExtractor()
    parser.feed(value)
    parser.close()
    return "\n".join(parser.parts)
