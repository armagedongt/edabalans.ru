"""Validate machine-checkable facts and protected editing boundaries."""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path

from search_author_voice import private


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


class _VisibleHTMLParser(HTMLParser):
    block_tags = {
        "address", "article", "aside", "blockquote", "br", "div", "figcaption",
        "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header",
        "hr", "li", "main", "nav", "ol", "p", "section", "table", "td", "th", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in self.block_tags:
            self.parts.append(" ")
        if tag == "a" and attributes.get("href"):
            self.parts.append(f"⟦HTML_LINK:{attributes['href']}:START⟧")
        if tag in {"img", "video", "audio", "source", "iframe", "embed", "object"}:
            media_target = attributes.get("src") or attributes.get("data")
            if media_target:
                self.parts.append(f"⟦HTML_MEDIA:{media_target}⟧")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.parts.append("⟦HTML_LINK:END⟧")
        if tag in self.block_tags:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class _LinkMediaHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.media: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.append(str(attributes["href"]))
        if tag in {"img", "video", "audio", "source", "iframe", "embed", "object"}:
            target = attributes.get("src") or attributes.get("data")
            if target:
                self.media.append(str(target))


def visible_text(value: str) -> str:
    """Remove supported presentation markup while preserving authored characters."""
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]*)\)",
        lambda match: f"⟦IMAGE:{match.group(2)}⟧{match.group(1)}",
        value,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]*)\)",
        lambda match: f"{match.group(1)}⟦LINK:{match.group(2)}⟧",
        text,
    )
    parser = _VisibleHTMLParser()
    parser.feed(text)
    text = "".join(parser.parts)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s+", "", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def inline_signature(value: str) -> list[str]:
    """Keep the order and placement class of protected inline markup."""
    pattern = re.compile(
        r"!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\)|\*\*.+?\*\*|__.+?__|(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_)",
        flags=re.S,
    )
    signature: list[str] = []
    cursor = 0
    for match in pattern.finditer(value):
        if value[cursor:match.start()].strip():
            signature.append("text")
        token = match.group(0)
        if token.startswith("!["):
            target = re.search(r"\]\(([^)]+)\)$", token).group(1)
            signature.append(f"image:{target}")
        elif token.startswith("["):
            target = re.search(r"\]\(([^)]+)\)$", token).group(1)
            signature.append(f"link:{target}")
        elif token.startswith(("**", "__")):
            signature.append("bold")
        else:
            signature.append("italic")
        cursor = match.end()
    if value[cursor:].strip():
        signature.append("text")
    return signature


def html_signature(value: str) -> list[str]:
    signature = []
    cursor = 0
    for match in re.finditer(r"<\s*(/?)\s*([a-zA-Z][\w:-]*)\b([^>]*)>", value):
        if value[cursor:match.start()].strip():
            signature.append("text")
        closing, name, attributes = match.groups()
        name = name.casefold()
        token = f"/{name}" if closing else name
        if not closing:
            parsed_attributes = []
            for attribute in re.finditer(
                r"([:\w-]+)(?:\s*=\s*(?:(['\"])(.*?)\2|([^\s'\"=<>`]+)))?",
                attributes,
                flags=re.S,
            ):
                attribute_name, _, quoted_value, bare_value = attribute.groups()
                attribute_value = quoted_value if quoted_value is not None else bare_value
                parsed_attributes.append(
                    f"{attribute_name.casefold()}={'' if attribute_value is None else attribute_value}"
                )
            if parsed_attributes:
                token += "|" + "|".join(sorted(parsed_attributes))
        signature.append(token)
        cursor = match.end()
    if value[cursor:].strip():
        signature.append("text")
    return signature


def block_signature(value: str) -> list[dict]:
    """Describe Markdown block structure without freezing editable wording."""
    blocks = [block for block in re.split(r"\n\s*\n", value.strip()) if block.strip()]
    signature = []
    for block in blocks:
        lines = block.splitlines()
        first = lines[0].lstrip()
        if re.match(r"^#{1,6}\s+", first):
            kind = re.match(r"^(#{1,6})", first).group(1)
        elif all(re.match(r"^\s*[-+*]\s+", line) for line in lines):
            kind = "unordered_list"
        elif all(re.match(r"^\s*\d+[.)]\s+", line) for line in lines):
            kind = "ordered_list"
        elif all(re.match(r"^\s*>\s?", line) for line in lines):
            kind = "quote"
        elif re.match(r"^!\[", first):
            kind = "image"
        else:
            kind = "paragraph"
        signature.append({
            "kind": kind,
            "line_count": len(lines),
            "bold_count": len(re.findall(r"\*\*.+?\*\*|__.+?__", block, flags=re.S)),
            "italic_count": len(re.findall(
                r"(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_)", block
            )),
            "links": re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", block),
            "images": re.findall(r"!\[[^\]]*\]\(([^)]+)\)", block),
            "inline": inline_signature(block),
            "html": html_signature(block),
        })
    return signature


def link_and_media_targets(value: str) -> dict[str, list[str]]:
    parser = _LinkMediaHTMLParser()
    parser.feed(value)
    return {
        "links": re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", value),
        "images": re.findall(r"!\[[^\]]*\]\(([^)]+)\)", value),
        "html_links": parser.links,
        "html_media": parser.media,
    }


def targeted_edit_preserves_protected_text(
    source_text: str, draft: str, editable_scope: list[object]
) -> bool:
    fragments = [
        item if isinstance(item, str) else item.get("source") if isinstance(item, dict) else None
        for item in editable_scope
    ]
    if any(not isinstance(item, str) or not item for item in fragments):
        return False
    source_fragments = [str(item) for item in fragments]
    located = sorted((source_text.find(item), item) for item in source_fragments)
    if any(position < 0 or source_text.count(fragment) != 1 for position, fragment in located):
        return False
    protected_segments: list[str] = []
    cursor = 0
    for position, fragment in located:
        if position < cursor:
            return False
        protected_segments.append(source_text[cursor:position])
        cursor = position + len(fragment)
    protected_segments.append(source_text[cursor:])
    if not draft.startswith(protected_segments[0]):
        return False
    draft_cursor = len(protected_segments[0])
    for segment in protected_segments[1:-1]:
        position = draft.find(segment, draft_cursor)
        if position < 0:
            return False
        draft_cursor = position + len(segment)
    return draft[draft_cursor:].endswith(protected_segments[-1])


def validate(pack_path: Path, draft_path: Path) -> dict:
    pack_path, draft_path = private(pack_path), private(draft_path)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    draft = draft_path.read_text(encoding="utf-8")
    contract = pack["content_contract"]
    missing_verbatim = []
    semantic_review = []
    for item in contract.get("required_facts") or []:
        fact = item if isinstance(item, str) else str(item.get("text") or "")
        mode = "semantic" if isinstance(item, str) else item.get("mode", "semantic")
        if mode == "verbatim" and normalized(fact) not in normalized(draft):
            missing_verbatim.append(fact)
        elif mode != "verbatim":
            semantic_review.append(fact)
    cta = contract.get("cta") or {}
    required_cta = cta.get("required_phrase") if isinstance(cta, dict) else None
    if required_cta and normalized(required_cta) not in normalized(draft):
        missing_verbatim.append(required_cta)
    unresolved_placeholders = re.findall(r"\[(?:УТОЧНИТЬ|ФАКТ|ССЫЛКА|CTA)[^\]]*\]", draft, flags=re.I)
    protected_layer_errors = []
    edit_mode = contract.get("edit_mode")
    source_text = contract.get("source_text")
    if edit_mode == "targeted_edit":
        if not isinstance(source_text, str):
            protected_layer_errors.append("source_text is required for targeted_edit")
        elif not targeted_edit_preserves_protected_text(
            source_text, draft, contract.get("editable_scope") or []
        ):
            protected_layer_errors.append("targeted_edit changed text outside editable_scope")
    elif edit_mode == "proofread":
        if not isinstance(source_text, str):
            protected_layer_errors.append("source_text is required for proofread")
        else:
            similarity = SequenceMatcher(
                None, normalized(source_text), normalized(draft), autojunk=False
            ).ratio()
            if block_signature(source_text) != block_signature(draft):
                protected_layer_errors.append("proofread changed protected structure or presentation markup")
            if len(source_text) >= 50 and similarity < 0.82:
                protected_layer_errors.append("proofread changed too much text for a correction-only mode")
    elif edit_mode == "structure_only":
        if not isinstance(source_text, str):
            protected_layer_errors.append("source_text is required for structure_only")
        elif (
            visible_text(source_text) != visible_text(draft)
            or link_and_media_targets(source_text) != link_and_media_targets(draft)
        ):
            protected_layer_errors.append("structure_only changed authored characters or their order")
    elif edit_mode == "text_only":
        if not isinstance(source_text, str):
            protected_layer_errors.append("source_text is required for text_only")
        elif block_signature(source_text) != block_signature(draft):
            protected_layer_errors.append("text_only changed protected structure or presentation markup")
    elif edit_mode == "rewrite":
        if not isinstance(source_text, str):
            protected_layer_errors.append("source_text is required for rewrite")
        if not str(contract.get("rewrite_goal") or "").strip():
            protected_layer_errors.append("rewrite_goal is required for rewrite")
        if (
            isinstance(source_text, str)
            and not contract.get("allow_link_media_changes")
            and link_and_media_targets(source_text) != link_and_media_targets(draft)
        ):
            protected_layer_errors.append("rewrite changed links or media without explicit permission")
    rewrite_review = None
    proofread_review = None
    if edit_mode == "proofread" and isinstance(source_text, str):
        proofread_review = {
            "instruction": "Confirm that every wording change is only spelling, punctuation, or explicit agreement correction.",
            "similarity": SequenceMatcher(
                None, normalized(source_text), normalized(draft), autojunk=False
            ).ratio(),
        }
    inline_binding_review = None
    if edit_mode == "text_only" and isinstance(source_text, str):
        source_inline = inline_signature(source_text)
        if source_inline or re.search(r"<(?:a|strong|b|em|i)\b", source_text, flags=re.I):
            inline_binding_review = {
                "instruction": "Confirm that emphasis and links remain bound to the same semantic fragments.",
                "source_inline_signature": source_inline,
                "draft_inline_signature": inline_signature(draft),
            }
    if edit_mode == "rewrite" and isinstance(source_text, str):
        rewrite_review = {
            "goal": contract.get("rewrite_goal"),
            "preserve": contract.get("rewrite_preserve") or [],
            "comparison_texts": contract.get("comparison_texts") or [],
            "source_characters": len(source_text),
            "draft_characters": len(draft),
        }
    return {
        "status": "pass" if not missing_verbatim and not unresolved_placeholders and not protected_layer_errors else "needs_fix",
        "missing_verbatim": missing_verbatim,
        "unresolved_placeholders": unresolved_placeholders,
        "protected_layer_errors": protected_layer_errors,
        "inline_binding_review_required_once": inline_binding_review,
        "proofread_change_review_required_once": proofread_review,
        "rewrite_continuity_review_required_once": rewrite_review,
        "semantic_fact_review_required_once": [fact for fact in semantic_review if fact],
        "forbidden_claims_to_check_once": contract.get("forbidden_claims") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.pack, args.draft), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
