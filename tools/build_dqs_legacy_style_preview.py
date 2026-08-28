"""Build a review-only DQS Markdown draft with the legacy article's semantics.

The old production response is the visual reference.  The result keeps its
headings, quotes, lists and inline emphasis, but replaces legacy runtime tokens
with the friendly component calls used by the current Markdown editor.
"""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "work/content-authoring-system/rollback-snapshots/day-04-dqs-production-before-publish-api.html"
CURRENT = ROOT / "content/masterclass/source-current/13-dqs-system.md"
OUTPUT = ROOT / "work/content-authoring-system/day-04-dqs-legacy-style-review.md"

TABLE_NAMES = {
    "all": "full",
    "plants": "plants",
    "proteins": "protein",
    "fats": "fats",
    "garnishes": "side-dishes",
    "harmful": "unhealthy",
}


def gallery_calls(markdown: str) -> dict[str, str]:
    calls = {}
    for name, block in re.findall(
        r"<!--\s*Слайдер DQS:\s*([^.]*)\..*?-->\s*(slider\([\s\S]*?\n\))",
        markdown,
    ):
        calls[name.strip()] = block
    if set(calls) != {"home", "takeout"}:
        raise ValueError(f"Expected both gallery calls, got {sorted(calls)}")
    return calls


class LegacyToMarkdown(HTMLParser):
    block_tags = {"p", "blockquote", "h2", "h3", "li"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.buffer: list[str] = []
        self.stack: list[str] = []
        self.list_stack: list[str] = []

    def flush(self) -> None:
        value = "".join(self.buffer).strip()
        self.buffer.clear()
        if value:
            self.output.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.block_tags:
            self.flush()
            if tag == "blockquote":
                self.buffer.append("> ")
            elif tag == "h2":
                self.buffer.append("## ")
            elif tag == "h3":
                self.buffer.append("### ")
            elif tag == "li":
                marker = "1. " if self.list_stack and self.list_stack[-1] == "ol" else "- "
                self.buffer.append(marker)
        elif tag in {"ul", "ol"}:
            self.flush()
            self.list_stack.append(tag)
        elif tag in {"strong", "b"}:
            self.buffer.append("**")
        elif tag in {"em", "i"}:
            self.buffer.append("*")
        elif tag == "br":
            self.buffer.append("\n")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"strong", "b"}:
            self.buffer.append("**")
        elif tag in {"em", "i"}:
            self.buffer.append("*")
        elif tag in self.block_tags:
            self.flush()
        elif tag in {"ul", "ol"}:
            self.flush()
            if self.list_stack:
                self.list_stack.pop()
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.buffer.append(data)

    def markdown(self) -> str:
        self.flush()
        return "\n\n".join(self.output).strip() + "\n"


def componentize(markdown: str, galleries: dict[str, str]) -> str:
    def table(match: re.Match[str]) -> str:
        return f"dqs_score_table(\n{TABLE_NAMES[match.group(1)]}\n)"

    markdown = re.sub(r"\[\[DQS_MATRIX:([^\]]+)\]\]", table, markdown)
    markdown = markdown.replace("[[GALLERY:dqs-home]]", galleries["home"])
    markdown = markdown.replace("[[GALLERY:dqs-takeout]]", galleries["takeout"])
    # The legacy HTML contained spacer paragraphs with a single >. They were not
    # author-visible quotations and must not become empty quote blocks in Markdown.
    markdown = re.sub(r"(?m)^>\s*$\n*", "", markdown)
    # Adjacent list items must stay in one Markdown list; the generic block
    # converter deliberately inserts blank lines between all other blocks.
    markdown = re.sub(r"(?m)^(- .+)\n\n(?=- )", r"\1\n", markdown)
    markdown = re.sub(r"(?m)^(1\. .+)\n\n(?=1\. )", r"\1\n", markdown)
    # In the original article adjacent quote paragraphs form one visual callout
    # with line breaks inside it, not several unrelated callout cards.
    while re.search(r"(?m)^> .+\n\n(?=> )", markdown):
        markdown = re.sub(r"(?m)^(> .+)\n\n(?=> )", r"\1\n", markdown)
    # Legacy HTML represented this recurring low-level heading as bold text.
    # Keep the words untouched but give it the intended hierarchy in Markdown.
    markdown = re.sub(r"(?m)^\*\*(Примечания:?)\*\*$", r"### \1", markdown)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"


def main() -> None:
    legacy_html = json.loads(REFERENCE.read_text(encoding="utf-8"))["html"]
    parser = LegacyToMarkdown()
    parser.feed(legacy_html)
    parser.close()
    draft = componentize(parser.markdown(), gallery_calls(CURRENT.read_text(encoding="utf-8")))
    if "<!--" in draft or "[[" in draft:
        raise ValueError("The review draft still has a runtime-only artefact")
    OUTPUT.write_text(draft, encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
