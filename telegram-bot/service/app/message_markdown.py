"""Compile an editorial Markdown original once, before publication."""
from html import escape
from html.parser import HTMLParser

import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import SimpleTagInlineProcessor

from app.content_formatting import validate_telegram_html


class MessageInlineExtension(Extension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(SimpleTagInlineProcessor(r"(~~)(.+?)(~~)", "del"), "strike", 175)
        md.inlinePatterns.register(SimpleTagInlineProcessor(r"(\|\|)(.+?)(\|\|)", "tg-spoiler"), "spoiler", 175)


class TelegramRenderer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.lists = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"strong", "em", "blockquote", "code", "pre", "del", "tg-spoiler"}:
            self.output.append("<" + {"strong": "b", "em": "i", "del": "s"}.get(tag, tag) + ">")
        elif tag == "a":
            self.output.append('<a href="' + escape(attributes.get("href", ""), quote=True) + '">')
        elif tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            if self.output and not "".join(self.output).endswith("\n"):
                self.output.append("\n\n")
            if tag != "p":
                self.output.append("<b>")
        elif tag == "br":
            self.output.append("\n")
        elif tag in {"ul", "ol"}:
            try:
                self.lists.append(int(attributes.get("start", "1")) - 1 if tag == "ol" else None)
            except ValueError as exc:
                raise ValueError("Некорректный начальный номер списка") from exc
        elif tag == "li":
            if not self.lists:
                raise ValueError("Элемент списка должен находиться внутри списка")
            if self.lists[-1] is None:
                self.output.append("• ")
            else:
                self.lists[-1] += 1
                self.output.append(str(self.lists[-1]) + ". ")
        else:
            raise ValueError("Неподдерживаемая разметка сообщения: " + tag + ". Картинки привязываются отдельно.")

    def handle_endtag(self, tag):
        if tag in {"strong", "em", "blockquote", "code", "pre", "del", "tg-spoiler"}:
            self.output.append("</" + {"strong": "b", "em": "i", "del": "s"}.get(tag, tag) + ">")
        elif tag == "a":
            self.output.append("</a>")
        elif tag.startswith("h") and tag[1:] in {"1", "2", "3", "4", "5", "6"}:
            self.output.append("</b>\n")
        elif tag in {"ul", "ol"}:
            if not self.lists:
                raise ValueError("Некорректная разметка списка")
            self.lists.pop()
        elif tag in {"p", "li"}:
            self.output.append("\n")

    def handle_data(self, data):
        self.output.append(escape(data, quote=False))

    def handle_entityref(self, name):
        from html import unescape
        self.output.append(escape(unescape("&" + name + ";"), quote=False))

    def handle_charref(self, name):
        self.output.append("&#" + name + ";")

    def handle_comment(self, data):
        raise ValueError("Служебные комментарии не должны находиться в тексте сообщения")


def compile_message_markdown(source: str, *, allow_image: bool = False) -> str:
    if allow_image:
        import re
        source, count = re.subn(r"(?m)^!\[[^\]\n]*\]\((?:<[^>\n]+>|[^)\n]+)\)\s*\n?", "", source)
        if count > 1:
            raise ValueError("У поста бота только одно вложение")
    renderer = TelegramRenderer()
    renderer.feed(markdown.markdown(source, extensions=["sane_lists", MessageInlineExtension()]))
    renderer.close()
    result = "".join(renderer.output).strip()
    validate_telegram_html(result)
    return result
