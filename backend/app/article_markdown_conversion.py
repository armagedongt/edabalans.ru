"""Convert retained course HTML only when the current renderer proves a round trip."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit
from fastapi import HTTPException

from app.article_markup import markdown_to_article_html
from app.masterclass_article_components import DQS_SCORE_TABLES, render_masterclass_component


class ConversionError(ValueError):
    pass


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


class Tree(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(html)
        self.close()
        if len(self.stack) != 1:
            raise ConversionError("Незакрытая HTML-разметка")

    def handle_starttag(self, tag, attrs):
        if len(self.stack) > 60:
            raise ConversionError("Слишком глубокая HTML-разметка")
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "hr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {"img", "br", "hr"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise ConversionError("Несогласованная HTML-разметка: " + tag)
        self.stack.pop()

    def handle_data(self, text):
        self.stack[-1].children.append(text)

    def handle_comment(self, text):
        raise ConversionError("HTML-комментарий требует проверки оригинала")


def fingerprint(node):
    if isinstance(node, str):
        return re.sub(r"\s+", " ", node)
    children = []
    for child in node.children:
        value = fingerprint(child)
        if isinstance(value, str) and not value.strip() and node.tag not in {"p", "li", "a", "strong", "em", "blockquote", "th", "td"}:
            continue
        if isinstance(value, str) and children and isinstance(children[-1], str):
            children[-1] += value
        else:
            children.append(value)
    attrs = {key: value for key, value in node.attrs.items() if not (node.tag == "img" and key == "decoding")}
    return node.tag, tuple(sorted(attrs.items())), tuple(children)


def component(name: str, arguments: list[str]) -> str:
    if any("\n" in argument or not argument.strip() for argument in arguments):
        raise ConversionError("Непредставимый аргумент компонента " + name)
    return name + "(\n" + "\n".join(arguments) + "\n)"


def rendered(markdown: str) -> str:
    try:
        return markdown_to_article_html(markdown, component_renderer=render_masterclass_component)
    except HTTPException as exc:
        raise ConversionError(str(exc.detail)) from exc


def checked_component(node: Node, name: str, arguments: list[str]) -> str:
    source = component(name, arguments)
    if fingerprint(Tree(rendered(source)).root.children[0]) != fingerprint(node):
        raise ConversionError("Особая вставка отличается от действующего компонента: " + name)
    return source


def descendants(node: Node, tag: str) -> list[Node]:
    result = []
    for child in node.children:
        if isinstance(child, Node):
            if child.tag == tag:
                result.append(child)
            result.extend(descendants(child, tag))
    return result


def inline(node) -> str:
    if isinstance(node, str):
        return re.sub(r"\s+", " ", node).replace("*", r"\*").replace("~", r"\~")
    body = "".join(inline(child) for child in node.children)
    if node.tag == "strong":
        return "**" + body + "**"
    if node.tag == "em":
        return "*" + body + "*"
    if node.tag == "del":
        return "~~" + body + "~~"
    if node.tag == "a":
        href = node.attrs.get("href", "")
        if not href or re.search(r"[\s()]", href):
            raise ConversionError("Ссылка требует расширения Markdown-диалекта")
        return "[" + body.replace("[", r"\[").replace("]", r"\]") + "](" + href + ")"
    raise ConversionError("Непредставимый строчный элемент: " + node.tag)


def block(node: Node) -> str:
    if node.tag in {"p", "h2", "h3"} and not node.attrs:
        prefix = {"p": "", "h2": "## ", "h3": "### "}[node.tag]
        return prefix + "".join(inline(child) for child in node.children).strip()
    if node.tag in {"ul", "ol"} and set(node.attrs) <= {"start"}:
        result = []
        start = int(node.attrs.get("start", "1"))
        for index, child in enumerate(node.children):
            if not isinstance(child, Node) or child.tag != "li" or child.attrs:
                raise ConversionError("Необычный элемент списка")
            prefix = "- " if node.tag == "ul" else str(start + index) + ". "
            result.append(prefix + "".join(inline(part) for part in child.children).strip())
        return "\n".join(result)
    if node.tag == "blockquote" and not node.attrs:
        lines = [""]
        for child in node.children:
            if isinstance(child, Node) and child.tag == "br":
                lines.append("")
            else:
                lines[-1] += inline(child)
        return "\n".join("> " + line.strip() for line in lines)
    if node.tag == "div" and node.attrs == {"class": "article-note-accent"}:
        body = blocks(node.children)
        return "> [!NOTE]\n" + "\n".join("> " + line for line in body.splitlines())
    if node.tag == "figure" and not node.attrs:
        images = [child for child in node.children if isinstance(child, Node) and child.tag == "img"]
        captions = [child for child in node.children if isinstance(child, Node) and child.tag == "figcaption"]
        if len(images) != 1 or len(captions) > 1 or len(node.children) != 1 + len(captions):
            raise ConversionError("Необычная фотография")
        image = images[0]
        alt, src = image.attrs.get("alt", ""), image.attrs.get("src", "")
        if re.search(r"[\]\n]", alt) or re.search(r"[\s()]", src):
            raise ConversionError("Непредставимая ссылка или подпись фотографии")
        caption = ""
        if captions:
            if any(not isinstance(child, str) for child in captions[0].children):
                raise ConversionError("Разметка в подписи фотографии")
            text = "".join(captions[0].children)
            if '"' in text or "\n" in text:
                raise ConversionError("Непредставимая подпись фотографии")
            caption = ' "' + text + '"'
        return f"![{alt}]({src}{caption})"
    if node.tag == "div" and node.attrs == {"class": "dqs-score-table-wrap"}:
        for key in DQS_SCORE_TABLES:
            source = component("dqs_score_table", [key])
            if fingerprint(Tree(rendered(source)).root.children[0]) == fingerprint(node):
                return source
        raise ConversionError("Таблица DQS отличается от действующего оригинала")
    if node.tag == "section" and node.attrs.get("class") == "article-gallery":
        return checked_component(node, "slider", [image.attrs["src"] for image in descendants(node, "img")])
    if node.tag == "details" and node.attrs == {"class": "article-spoiler"}:
        titles = descendants(node, "summary")
        paragraphs = descendants(node, "p")
        if len(titles) != 1:
            raise ConversionError("Необычный спойлер")
        return checked_component(node, "spoiler", ["".join(inline(child) for child in part.children) for part in titles + paragraphs])
    if node.tag == "div" and node.attrs == {"class": "article-table-wrap"}:
        rows = descendants(node, "tr")
        result = []
        for row in rows:
            cells = [child for child in row.children if isinstance(child, Node) and child.tag in {"td", "th"}]
            result.append("| " + " | ".join("".join(inline(child) for child in cell.children).replace("|", r"\|") for cell in cells) + " |")
        if len(result) < 2:
            raise ConversionError("Таблица без строк")
        result.insert(1, "| " + " | ".join("---" for _ in rows[0].children) + " |")
        return "\n".join(result)
    if node.tag == "div" and node.attrs.get("class") in {"article-audio", "media"}:
        frames = descendants(node, "iframe")
        if len(frames) != 1:
            raise ConversionError("Необычная вставка медиа")
        frame = frames[0]
        url = urlsplit(frame.attrs["src"])
        query = parse_qs(url.query)
        if node.attrs["class"] == "article-audio":
            if url.path != "/course-assets/masterclass/audio-player":
                raise ConversionError("Неизвестный аудиоплеер")
            args = [query[key][0] for key in ("src", "avatar", "author", "duration")]
            return checked_component(node, "audio", args)
        src = query["src"][0] if url.path == "/apps/video-player.html" else frame.attrs["src"]
        return checked_component(node, "video", [src, frame.attrs.get("title", "Видео")])
    raise ConversionError("Непредставимый блок: " + node.tag + " " + repr(node.attrs))


def blocks(children: list) -> str:
    result = []
    for child in children:
        if isinstance(child, str):
            if child.strip():
                raise ConversionError("Текст вне абзаца")
        else:
            result.append(block(child))
    return "\n\n".join(result)


def convert(html: str) -> str:
    if not html.strip() or len(html.encode()) > 500_000:
        raise ConversionError("Нет опубликованного HTML допустимого размера")
    original = Tree(html).root
    markdown = blocks(original.children) + "\n"
    if fingerprint(Tree(rendered(markdown)).root) != fingerprint(original):
        raise ConversionError("Обратный рендер изменил содержание или визуальную структуру")
    return markdown


def preserved_html(current_html: str, rendered_html: str, expected_hash: str) -> str:
    """Adoption changes the editable source, never the published HTML bytes."""
    import hashlib
    if hashlib.sha256(current_html.encode("utf-8")).hexdigest() != expected_hash:
        raise HTTPException(409, "Исходная HTML-редакция изменилась")
    try:
        equivalent = fingerprint(Tree(current_html).root) == fingerprint(Tree(rendered_html).root)
    except (ConversionError, ValueError, KeyError) as exc:
        raise HTTPException(422, "Не удалось доказать сохранение содержания") from exc
    if not equivalent:
        raise HTTPException(422, "Markdown изменяет содержание или визуальную структуру")
    return current_html
