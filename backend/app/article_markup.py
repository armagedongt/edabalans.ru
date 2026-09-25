from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import HTTPException


ALLOWED_TAGS = {
    "h1", "h2", "h3", "p", "div", "ul", "ol", "li", "strong", "em",
    "a", "blockquote", "aside", "img", "br", "hr",
}
COURSE_TAGS = ALLOWED_TAGS | {
    "figure", "figcaption", "section", "table", "thead", "tbody", "tr", "th",
    "td", "span", "button", "details", "summary",
}
VOID_TAGS = {"img", "br", "hr"}
BLOCKED_TAGS = {"script", "style", "iframe", "object", "svg", "math"}
COURSE_CLASS_TOKENS = {
    "article-gallery", "gallery-window", "gallery-track", "gallery-slide",
    "gallery-arrow", "gallery-prev", "gallery-next", "gallery-footer",
    "gallery-counter", "gallery-dots", "gallery-dot", "active",
    "dqs-score-table-wrap", "dqs-score-table",
    "article-spoiler", "article-spoiler-body", "media", "article-audio",
    "blog-cta", "blog-cta-intensive", "blog-cta-masterclass", "blog-cta-telegram",
    "blog-cta-eyebrow",
    "score-2", "score-1", "score-0", "score--1", "score--2",
}
COURSE_BASE_CLASS_TOKENS = {"article-table-wrap", "article-data-table", "article-note-accent"}


def safe_href(value: str) -> bool:
    cleaned = value.strip()
    decoded = unquote(cleaned)
    if decoded.startswith("//") or "\\" in decoded or any(ord(character) < 32 for character in decoded):
        return False
    return urlparse(cleaned).scheme in {"", "http", "https", "mailto"}


def opens_in_new_tab(value: str) -> bool:
    """Keep same-site course navigation in place; separate external browsing."""
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not course_material_href(value)


def course_material_href(value: str) -> str | None:
    """Keep links to our course materials on the current site's account route."""
    parsed = urlparse(value.strip())
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        course_hosts = {
            "edabalans.ru",
            "похудение-это-есть.рф".encode("idna").decode("ascii"),
        }
        if hostname not in course_hosts:
            return None
    if parsed.path not in {"/lk", "/apps/masterclass-course.html"}:
        return None
    query = parse_qs(parsed.query)
    if not query.get("course_day") or not query.get("course_material"):
        return None
    return "/lk?" + parsed.query + ("#" + parsed.fragment if parsed.fragment else "")


def safe_video_source(value: str) -> bool:
    decoded = unquote(value)
    if value != value.strip() or "\\" in decoded or any(ord(c) < 32 for c in decoded):
        return False
    try:
        parsed = urlparse(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and parsed.port in {None, 443} and not parsed.fragment
                and parsed.path.lower().endswith(".mp4"))
    except ValueError:
        return False


def safe_video_frame(value: str) -> bool:
    if not value.startswith("/apps/video-player.html?"):
        return False
    parsed = urlparse(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    return (not parsed.fragment and set(query) == {"src"}
            and len(query["src"]) == 1 and safe_video_source(query["src"][0]))


def safe_audio_arguments(source: str, avatar: str, author: str, duration: str) -> bool:
    """Closed audio player accepts direct HTTPS media, never arbitrary embeds."""
    def media_url(value: str, suffixes: tuple[str, ...]) -> bool:
        decoded = unquote(value)
        if value != value.strip() or "\\" in decoded or any(ord(c) < 32 for c in decoded):
            return False
        try:
            parsed = urlparse(value)
            return (parsed.scheme == "https" and bool(parsed.hostname)
                    and not parsed.username and not parsed.password
                    and parsed.port in {None, 443} and not parsed.fragment
                    and parsed.path.lower().endswith(suffixes))
        except ValueError:
            return False
    return (media_url(source, (".mp3", ".ogg", ".m4a"))
            and media_url(avatar, (".webp", ".jpg", ".jpeg", ".png"))
            and 1 <= len(author.strip()) <= 100
            and re.fullmatch(r"[0-9]{1,3}:[0-5][0-9]", duration) is not None)


def safe_audio_frame(value: str) -> bool:
    if not value.startswith("/course-assets/masterclass/audio-player?"):
        return False
    parsed = urlparse(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    keys = ("src", "avatar", "author", "duration")
    return (not parsed.fragment and set(query) == set(keys)
            and all(len(query[key]) == 1 for key in keys)
            and safe_audio_arguments(*(query[key][0] for key in keys)))


def safe_image_src(value: str, *, allow_relative: bool = False) -> bool:
    cleaned = value.strip()
    decoded = unquote(cleaned)
    if decoded.startswith("//") or "\\" in decoded or any(ord(character) < 32 for character in decoded):
        return False
    if allow_relative and cleaned.startswith("/"):
        return True
    parsed = urlparse(cleaned)
    return parsed.scheme == "https" and bool(parsed.netloc)


class ArticleSanitizer(HTMLParser):
    def __init__(
        self,
        *,
        allow_h1: bool,
        course_semantics: bool,
        allow_product_components: bool,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.allow_h1 = allow_h1
        self.course_semantics = course_semantics
        self.allow_product_components = allow_product_components
        self.parts: list[str] = []
        self.blocked_depth = 0
        self.disallowed_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if (tag == "iframe" and not self.blocked_depth
                and self.course_semantics and self.allow_product_components):
            attributes = dict(attrs)
            source = str(attributes.get("src") or "")
            if safe_audio_frame(source):
                self.parts.append(
                    f'<iframe src="{escape(source, quote=True)}"'
                    ' title="Голосовое Сергея Воронцова" loading="lazy"></iframe>'
                )
                return
            if safe_video_frame(source):
                title = str(attributes.get("title") or "Видео")[:200]
                self.parts.append(
                    f'<iframe src="{escape(source, quote=True)}"'
                    f' title="{escape(title, quote=True)}" loading="lazy"'
                    ' allow="fullscreen; picture-in-picture" allowfullscreen></iframe>'
                )
                return
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
                rendered_attrs = f' href="{escape(course_material_href(href) or href.strip(), quote=True)}"'
                if self.course_semantics and opens_in_new_tab(href):
                    rendered_attrs += ' target="_blank" rel="noopener"'
                tracking_key = next(
                    (value for name, value in attrs if name.lower() == "data-tracking-key"),
                    None,
                )
                if self.allow_product_components and tracking_key and re.fullmatch(
                    r"[a-z0-9_-]{1,80}", tracking_key
                ):
                    rendered_attrs += (
                        f' data-tracking-key="{escape(tracking_key, quote=True)}"'
                    )
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
                ' loading="lazy" decoding="async"'
            )
        elif tag == "aside" and self.course_semantics:
            rendered_attrs = ' class="editorial-note"'
        elif self.course_semantics:
            attributes = {name.lower(): value for name, value in attrs}
            rendered: list[str] = []
            class_value = str(attributes.get("class") or "").strip()
            if class_value:
                tokens = class_value.split()
                allowed_tokens = COURSE_BASE_CLASS_TOKENS | (
                    COURSE_CLASS_TOKENS if self.allow_product_components else set()
                )
                if tokens and all(token in allowed_tokens for token in tokens):
                    rendered.append(f'class="{escape(" ".join(tokens), quote=True)}"')
            if self.allow_product_components and tag == "section" and attributes.get("data-gallery") == "true":
                rendered.append('data-gallery="true"')
            if self.allow_product_components and tag == "section" and attributes.get("data-component") in {"image-slider", "blog-cta"}:
                rendered.append(f'data-component="{attributes["data-component"]}"')
            if tag == "button" and self.allow_product_components:
                slide = str(attributes.get("data-slide") or "")
                label = str(attributes.get("aria-label") or "")
                if slide.isdigit():
                    rendered.append(f'data-slide="{slide}"')
                if label:
                    rendered.append(f'aria-label="{escape(label[:200], quote=True)}"')
                rendered.append('type="button"')
            rendered_attrs = (" " + " ".join(rendered)) if rendered else ""
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
    value: str,
    *,
    allow_h1: bool = True,
    course_semantics: bool = False,
    allow_product_components: bool = False,
) -> str:
    parser = ArticleSanitizer(
        allow_h1=allow_h1,
        course_semantics=course_semantics,
        allow_product_components=allow_product_components,
    )
    parser.feed(value)
    parser.close()
    if parser.disallowed_h1:
        raise HTTPException(
            status_code=422,
            detail="Главный заголовок хранится в карточке материала; удалите h1 из текста статьи",
        )
    result = "".join(parser.parts).strip()
    if not result or (not article_plain_text(result).strip() and "<img " not in result
                      and "<iframe " not in result):
        raise HTTPException(status_code=422, detail="Текст страницы не может быть пустым")
    return result


def inline_markdown(value: str) -> str:
    rendered = escape(value)

    def render_link(match: re.Match[str]) -> str:
        label = match.group(1).replace(r"\[", "[").replace(r"\]", "]")
        href = match.group(2)
        external = ' target="_blank" rel="noopener"' if opens_in_new_tab(href) else ""
        return f'<a href="{course_material_href(href) or href}"{external}>{label}</a>'

    rendered = re.sub(
        r"\[((?:\\[\[\]]|[^\]])+)\]\((https?://[^\s)]+|/(?!/)[^\s)]+)\)",
        render_link,
        rendered,
    )
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered)
    return rendered


def markdown_table_cells(value: str) -> list[str]:
    row = value.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith(r"\|"):
        row = row[:-1]
    cells = re.split(r"(?<!\\)\|", row)
    return [cell.strip().replace(r"\|", "|") for cell in cells]


def is_markdown_table_separator(value: str) -> bool:
    cells = markdown_table_cells(value)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def markdown_to_article_html(
    source: str,
    *,
    strip_source_metadata: bool = False,
    component_renderer: Callable[[str, list[str]], str] | None = None,
) -> str:
    cleaned_source = str(source or "").replace("\r", "")
    cleaned_source = re.sub(r"<!--[\s\S]*?-->", "", cleaned_source)
    if "<!--" in cleaned_source or "-->" in cleaned_source:
        raise HTTPException(422, "Незакрытый HTML-комментарий в материале")
    lines = cleaned_source.split("\n")
    output: list[str] = []
    index = 0

    def is_boundary(value: str) -> bool:
        stripped = value.strip()
        return bool(
            not stripped
            or stripped.startswith(("# ", "## ", "### ", "> ", ":::"))
            or re.match(r"^(?:[-*] |\d+[.)] )", stripped)
            or re.fullmatch(r"!\[[^\]]*\]\(.+\)", stripped)
            or re.fullmatch(r"[a-z][\w-]*\(", stripped)
            or stripped.startswith("|")
        )

    while index < len(lines):
        line = lines[index].strip()
        if not line or (
            strip_source_metadata
            and (line.startswith("Статус:") or line.startswith("Источник:"))
        ):
            index += 1
            continue
        if line.startswith("# "):
            index += 1
            continue
        if line.startswith("### "):
            output.append(f"<h3>{inline_markdown(line[4:])}</h3>")
            index += 1
            continue
        if line.startswith("## "):
            output.append(f"<h2>{inline_markdown(line[3:])}</h2>")
            index += 1
            continue
        if (
            line.startswith("|")
            and index + 1 < len(lines)
            and is_markdown_table_separator(lines[index + 1])
        ):
            headers = markdown_table_cells(line)
            separator = markdown_table_cells(lines[index + 1])
            if len(headers) != len(separator):
                raise HTTPException(422, "В Markdown-таблице не совпадает число колонок")
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = markdown_table_cells(lines[index])
                if len(cells) != len(headers):
                    raise HTTPException(422, "В Markdown-таблице не совпадает число колонок")
                rows.append(cells)
                index += 1
            head = "".join(f"<th>{inline_markdown(cell)}</th>" for cell in headers)
            body = "".join(
                "<tr>" + "".join(f"<td>{inline_markdown(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            output.append(
                '<div class="article-table-wrap"><table class="article-data-table">'
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
            )
            continue
        if line.startswith(":::"):
            note = re.fullmatch(r":::note(?:\s+\[([^\]]+)\])?", line)
            if not note:
                raise HTTPException(422, f"Неизвестная directive: {line}")
            title = note.group(1) or "Важно"
            body_lines: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != ":::":
                if lines[index].strip().startswith(":::"):
                    raise HTTPException(422, "Вложенные directives не поддерживаются")
                body_lines.append(lines[index])
                index += 1
            if index >= len(lines):
                raise HTTPException(422, "Незакрытая directive :::note")
            paragraphs = [
                " ".join(part.strip() for part in block.splitlines() if part.strip())
                for block in re.split(r"\n\s*\n", "\n".join(body_lines))
                if block.strip()
            ]
            if not paragraphs:
                raise HTTPException(422, "Плашка :::note не может быть пустой")
            output.append(
                f"<aside><strong>{inline_markdown(title)}</strong>"
                + "".join(f"<p>{inline_markdown(paragraph)}</p>" for paragraph in paragraphs)
                + "</aside>"
            )
            index += 1
            continue
        component = re.fullmatch(r"([a-z][\w-]*)\(", line)
        if component:
            name = component.group(1)
            arguments: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != ")":
                argument = lines[index].strip()
                if argument:
                    arguments.append(argument)
                index += 1
            if index >= len(lines):
                raise HTTPException(422, f"Незакрытый вызов компонента {name}(")
            if component_renderer is None:
                raise HTTPException(422, f"Компонент {name} доступен только в продуктовом renderer")
            output.append(component_renderer(name, arguments))
            index += 1
            continue
        if line.startswith(">"):
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(re.sub(r"^>\s?", "", lines[index].strip()))
                index += 1
            note = quote_lines[0] == "[!NOTE]"
            if note:
                body = "\n".join(quote_lines[1:]).strip()
                if not body:
                    raise HTTPException(422, "Плашка NOTE не может быть пустой")
                if any(re.match(r"^(?:>|\[!|#|\||```|:::|!\[|(?:slider|spoiler|dqs_score_table)\()", item.strip()) for item in quote_lines[1:]):
                    raise HTTPException(422, "В NOTE поддержаны абзацы, списки, выделения и ссылки")
                output.append(
                    '<div class="article-note-accent">'
                    + markdown_to_article_html(body)
                    + "</div>"
                )
            elif quote_lines[0].startswith("[!"):
                raise HTTPException(422, "В этом renderer поддержан только обычный NOTE")
            else:
                output.append(
                    "<blockquote>" + "<br>".join(inline_markdown(item) for item in quote_lines) + "</blockquote>"
                )
            continue
        image = re.fullmatch(
            r'!\[([^\]]*)\]\((https://[^\s)]+|/(?!/)[^\s)]+)(?:\s+"([^"]*)")?\)',
            line,
        )
        if image:
            alt, src, caption = image.groups()
            figure = (
                f'<figure><img src="{escape(src, quote=True)}" '
                f'alt="{escape(alt, quote=True)}" loading="lazy" decoding="async">'
            )
            if caption:
                figure += f"<figcaption>{escape(caption)}</figcaption>"
            output.append(figure + "</figure>")
            index += 1
            continue
        bullet = re.match(r"^[-*] (.+)", line)
        numbered = re.match(r"^\d+[.)] (.+)", line)
        if bullet or numbered:
            kind = "ul" if bullet else "ol"
            items = []
            while index < len(lines):
                candidate = lines[index].strip()
                match = re.match(r"^[-*] (.+)", candidate) if kind == "ul" else re.match(r"^\d+[.)] (.+)", candidate)
                if not match:
                    break
                items.append(f"<li>{inline_markdown(match.group(1))}</li>")
                index += 1
            output.append(f"<{kind}>{''.join(items)}</{kind}>")
            continue
        paragraph_lines = [line]
        index += 1
        while index < len(lines) and not is_boundary(lines[index]):
            paragraph_lines.append(lines[index].strip())
            index += 1
        output.append(f"<p>{inline_markdown(' '.join(paragraph_lines))}</p>")
    return sanitize_article_html(
        "".join(output),
        allow_h1=False,
        course_semantics=True,
        allow_product_components=component_renderer is not None,
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
