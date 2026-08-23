from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote

from lxml import etree, html


ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "div",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "span",
    "strong",
    "u",
    "ul",
}
DROP_TAGS = {"button", "form", "input", "noscript", "script", "style", "svg", "textarea"}
KEEP_ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "title"}}


def has_class(element: etree._Element, class_name: str) -> bool:
    return class_name in (element.get("class") or "").split()


def encoded_local_asset(source_dir: Path, page_dir_name: str, value: str) -> str:
    cleaned = unquote(value).replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned.startswith(page_dir_name + "/"):
        return value
    relative = source_dir.name + "/" + cleaned
    return "/content/masterclass/source-tilda/" + "/".join(quote(part) for part in relative.split("/"))


def sanitize_tree(container: etree._Element, source_dir: Path, page_dir_name: str) -> str:
    cloned = html.fromstring(html.tostring(container, encoding="unicode"))
    # Saved Tilda pages may keep only a tiny lazy-load placeholder in img[src].
    # The adjacent schema.org meta element still contains the original CDN URL.
    for figure in cloned.xpath(".//figure"):
        original = figure.xpath(".//meta[@itemprop='image']/@content")
        images = figure.xpath(".//img")
        if original and images and re.match(r"^https?://", original[0], re.IGNORECASE):
            images[0].set("src", original[0])
    for element in list(cloned.iterdescendants()):
        tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag in DROP_TAGS:
            element.drop_tree()
            continue
        if tag not in ALLOWED_TAGS:
            element.drop_tag()
            continue
        original_class = element.get("class") or ""
        if tag == "div" and "t-redactor__text" in original_class.split():
            element.tag = "p"
            tag = "p"
        if tag == "h4" and "t-redactor__h4" in original_class.split():
            element.tag = "h2"
            tag = "h2"
        allowed = KEEP_ATTRS.get(tag, set())
        for attribute in list(element.attrib):
            if attribute not in allowed:
                del element.attrib[attribute]
        if tag == "a":
            href = element.get("href") or ""
            if not re.match(r"^(https?://|mailto:|tel:|#)", href, re.IGNORECASE):
                element.attrib.pop("href", None)
        if tag == "img":
            source = element.get("src") or ""
            element.set("src", encoded_local_asset(source_dir, page_dir_name, source))
            element.set("loading", "lazy")
    parts = [html.tostring(child, encoding="unicode", method="html") for child in cloned]
    return "".join(parts).strip()


def extract_page(path: Path, source_dir: Path) -> dict[str, object]:
    document = html.fromstring(path.read_text(encoding="utf-8"))
    title_nodes = document.xpath("//title")
    title = " ".join(title_nodes[0].text_content().split()) if title_nodes else path.stem
    containers = document.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' tlk-lecture__text ')]"
    )
    if not containers:
        containers = document.xpath(
            "//*[contains(concat(' ', normalize-space(@class), ' '), ' tlk-lecture__text-top ') or "
            "contains(concat(' ', normalize-space(@class), ' '), ' tlk-lecture__text-bottom ')]"
        )
    if not containers:
        raise ValueError(f"Lecture content not found in {path.name}")
    container = html.Element("div")
    for source in containers:
        for child in source:
            container.append(copy.deepcopy(child))
    rich_html = sanitize_tree(container, source_dir, f"{path.stem}_files")
    plain_text = " ".join(container.text_content().split())
    headings = [" ".join(node.text_content().split()) for node in container.xpath(".//h1|.//h2|.//h3|.//h4")]
    links = sorted(
        {
            value
            for value in container.xpath(".//a/@href")
            if re.match(r"^https?://", value or "", re.IGNORECASE)
        }
    )
    images = [value for value in container.xpath(".//img/@src") if value]
    media_links = sorted(
        {
            value
            for value in document.xpath(
                "//*[contains(concat(' ', normalize-space(@class), ' '), ' tlk-lecture__video-wrap ')]"
                "//@src | //*[contains(concat(' ', normalize-space(@class), ' '), ' tlk-lecture__video-wrap ')]//@data-original"
            )
            if value
        }
    )
    return {
        "source_file": path.name,
        "title": title,
        "plain_text": plain_text,
        "word_count": len(re.findall(r"[\wЁёА-Яа-я-]+", plain_text, re.UNICODE)),
        "headings": headings,
        "links": links,
        "image_count": len(images),
        "media_links": media_links,
        "rich_html": rich_html,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pages = [extract_page(path, args.source) for path in sorted(args.source.glob("*.html"))]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pages": len(pages), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
