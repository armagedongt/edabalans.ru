"""Extract one Tilda course article into reviewable semantic Markdown.

Only the lecture body is read.  Navigation, scripts, member-area chrome and
other page scaffolding are ignored.  The tool is intentionally extraction-only:
it preserves visible wording and presentation primitives without editorial
rewriting.
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
from urllib.parse import quote


class TildaArticle(HTMLParser):
    def __init__(self, source_dir: Path, assets_dir: Path | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.source_dir = source_dir
        self.assets_dir = assets_dir
        self.in_article = False
        self.article_depth = 0
        self.tag_stack: list[str] = []
        self.block: list[str] = []
        self.blocks: list[str] = []
        self.list_stack: list[str] = []
        self.link_stack: list[str | None] = []
        self.figure_image: str | None = None

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def flush(self) -> None:
        value = "".join(self.block).strip()
        self.block.clear()
        if value:
            self.blocks.append(value)

    def local_asset(self, source: str) -> str | None:
        """Copy an article-local Tilda asset beside the Markdown rendition."""
        if not self.assets_dir or source.startswith(("https://", "http://", "data:")):
            return source if source.startswith(("https://", "http://")) else None
        original = (self.source_dir / source).resolve()
        if not original.is_file():
            return None
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        destination = self.assets_dir / original.name
        shutil.copy2(original, destination)
        return destination.name

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if not self.in_article and tag == "div" and "tlk-lecture__text" in classes:
            self.in_article = True
            self.article_depth = 1
            self.tag_stack.append(tag)
            return
        if not self.in_article:
            return
        if tag not in self.VOID_TAGS:
            self.tag_stack.append(tag)
        if tag == "div" and "t-redactor__text" in classes:
            self.flush()
        elif tag in {"h2", "h3", "h4"}:
            self.flush()
            self.block.append("## " if tag in {"h2", "h3"} else "### ")
        elif tag == "blockquote":
            self.flush()
            self.block.append("> ")
        elif tag in {"ul", "ol"}:
            self.flush()
            self.list_stack.append(tag)
        elif tag == "li":
            self.flush()
            self.block.append("1. " if self.list_stack and self.list_stack[-1] == "ol" else "- ")
        elif tag == "figure":
            self.flush()
            self.figure_image = None
        elif tag == "meta" and attributes.get("itemprop") == "image":
            original = attributes.get("content")
            if original and original.startswith(("https://", "http://")):
                self.figure_image = original
        elif tag == "img":
            self.flush()
            # Saved Tilda pages often keep a tiny lazy-load placeholder in
            # img[src].  The schema.org meta inside the same figure retains
            # the public CDN original, which is also valid in course Markdown.
            src = self.figure_image or attributes.get("data-original") or attributes.get("src")
            local_or_remote = self.local_asset(src) if src else None
            if local_or_remote:
                alt = attributes.get("alt") or ""
                if local_or_remote.startswith(("https://", "http://")):
                    self.blocks.append(f"![{alt}]({local_or_remote})")
                else:
                    asset_url = quote(local_or_remote)
                    self.blocks.append(f"![{alt}](assets/{self.assets_dir.name}/{asset_url})")
        elif tag == "strong":
            self.block.append("**")
        elif tag in {"em", "i"}:
            self.block.append("*")
        elif tag == "a":
            self.link_stack.append(attributes.get("href"))
            self.block.append("[")
        elif tag == "br":
            self.block.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_article:
            return
        if tag == "strong":
            # Tilda frequently puts the separator before </strong>.  Markdown
            # needs that separator after the closing delimiter instead.
            if self.block and self.block[-1].endswith(" "):
                self.block[-1] = self.block[-1][:-1]
                self.block.append("** ")
            else:
                self.block.append("**")
        elif tag in {"em", "i"}:
            self.block.append("*")
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else None
            self.block.append("]" + (f"({href})" if href else ""))
        elif tag in {"div", "p", "h2", "h3", "h4", "blockquote", "li", "figure"}:
            self.flush()
            if tag == "figure":
                self.figure_image = None
        elif tag in {"ul", "ol"}:
            self.flush()
            if self.list_stack:
                self.list_stack.pop()
        if self.tag_stack:
            self.tag_stack.pop()
        if tag == "div" and not self.tag_stack:
            self.in_article = False

    def handle_data(self, data: str) -> None:
        if self.in_article:
            self.block.append(data)

    def markdown(self) -> str:
        self.flush()
        result = "\n\n".join(block.strip() for block in self.blocks if block.strip())
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = re.sub(r"(?m)^(?:- |1\. ).+\n\n(?=(?:- |1\. ))", lambda match: match.group(0).replace("\n\n", "\n"), result)
        return result.strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--copy-local-assets",
        action="store_true",
        help="copy local *_files images beside the Markdown file",
    )
    args = parser.parse_args()
    assets_dir = args.output.parent / "assets" / args.output.stem if args.copy_local_assets else None
    article = TildaArticle(args.source.parent, assets_dir)
    article.feed(args.source.read_text(encoding="utf-8", errors="ignore"))
    article.close()
    rendered = article.markdown()
    if not rendered:
        raise SystemExit("Tilda lecture body was not found")
    args.output.write_text(rendered, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
