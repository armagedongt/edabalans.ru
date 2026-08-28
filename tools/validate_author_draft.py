"""Validate machine-checkable facts and protected editing boundaries."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path

from search_author_voice import private


SIGNIFICANT_TOKEN = re.compile(r"[\wёЁ]+", flags=re.UNICODE)
FACT_REVIEW_TTL = timedelta(hours=24)


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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def significant_tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in SIGNIFICANT_TOKEN.findall(value)
        if len(token) >= 2
    ]


def without_allowed_removals(value: str, removals: list[str]) -> tuple[str, list[str]]:
    result = value
    missing: list[str] = []
    for fragment in removals:
        if fragment not in result:
            missing.append(fragment)
            continue
        result = result.replace(fragment, "")
    return result, missing


def structure_only_preserves_authored_text(
    source: str, draft: str, labels: list[str]
) -> bool:
    """Allow heading-level changes and new allowlisted headings, not authored-text edits."""
    heading = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
    source_lines = source.splitlines()
    draft_lines = draft.splitlines()
    authored_labels = [
        " ".join(visible_text(match.group(1)).split())
        for line in source_lines
        if (match := heading.match(line))
    ]

    source_heading_cursor = 0
    source_comparable: list[str] = []
    for line in source_lines:
        if heading.match(line):
            source_comparable.append(f"⟦AUTHORED_HEADING_{source_heading_cursor}⟧")
            source_heading_cursor += 1
        else:
            source_comparable.append(line)

    allowed = {normalized(label) for label in labels}
    added_counts: Counter[str] = Counter()
    draft_comparable: list[str] = []
    authored_cursor = 0
    for line in draft_lines:
        match = heading.match(line)
        if match:
            authored_label = " ".join(visible_text(match.group(1)).split())
            if (
                authored_cursor < len(authored_labels)
                and authored_label == authored_labels[authored_cursor]
            ):
                draft_comparable.append(
                    f"⟦AUTHORED_HEADING_{authored_cursor}⟧"
                )
                authored_cursor += 1
                continue
            if authored_label in authored_labels:
                return False
            label = normalized(authored_label)
            if label in allowed:
                added_counts[label] += 1
                continue
        draft_comparable.append(line)
    if authored_cursor != len(authored_labels):
        return False
    if any(count > 1 for count in added_counts.values()):
        return False
    return visible_text("\n".join(source_comparable)) == visible_text(
        "\n".join(draft_comparable)
    )


def preservation_metrics(source: str, draft: str) -> dict:
    source_visible = visible_text(source)
    draft_visible = visible_text(draft)
    source_tokens = significant_tokens(source_visible)
    draft_tokens = Counter(significant_tokens(draft_visible))
    source_counts = Counter(source_tokens)
    preserved = sum((source_counts & draft_tokens).values())
    return {
        "source_significant_tokens": len(source_tokens),
        "token_coverage": preserved / len(source_tokens) if source_tokens else 1.0,
        "source_visible_characters": len(source_visible),
        "draft_visible_characters": len(draft_visible),
        "visible_length_ratio": (
            len(draft_visible) / len(source_visible) if source_visible else 1.0
        ),
    }


def required_manual_reviews(contract: dict, draft: str) -> list[dict]:
    checks: list[dict] = []
    work_profile = contract.get("work_profile")
    edit_mode = contract.get("edit_mode")
    if edit_mode == "rewrite" and work_profile in {
        "transcript_to_article", "develop_existing"
    }:
        checks.append({"id": "rewrite_continuity", "instruction": "Confirm that the source argument, author position, and useful examples remain continuous."})
    facts_to_review = []
    for item in contract.get("required_facts") or []:
        facts_to_review.append(
            item if isinstance(item, str) else str(item.get("text") or "")
        )
    if any(facts_to_review):
        profile = contract.get("fact_check_profile") or "editorial_materiality"
        instruction = (
            "Confirm numbers, definitions, medical or food guidance, risk, and causality "
            "against the task sources. Accept a clearly signalled analogy or simplification "
            "only when it preserves the correct practical principle."
            if profile == "instructional_strict"
            else
            "Confirm that the draft contains no materially false or invented number, "
            "mechanism, diagnosis, contraindication, or claim that changes the advice. "
            "Do not fail colloquial rounding, metaphor, irony, or stylistic simplification "
            "that preserves the factual meaning."
        )
        checks.append({
            "id": "semantic_facts",
            "instruction": instruction,
            "fact_check_profile": profile,
            "items": [item for item in facts_to_review if item],
        })
    forbidden = contract.get("forbidden_claims") or []
    if forbidden:
        checks.append({"id": "forbidden_claims", "instruction": "Confirm that none of the forbidden claims is present.", "items": forbidden})
    source_text = contract.get("source_text")
    if edit_mode == "text_only" and isinstance(source_text, str):
        source_inline = inline_signature(source_text)
        if source_inline or re.search(r"<(?:a|strong|b|em|i)\b", source_text, flags=re.I):
            checks.append({"id": "inline_binding", "instruction": "Confirm emphasis and links remain bound to the same semantic fragments."})
    if edit_mode == "proofread":
        checks.append({"id": "proofread_changes", "instruction": "Confirm every wording change is only spelling, punctuation, or an explicitly requested agreement correction."})
    return checks


def review_errors(
    review: dict | None,
    pending: list[dict],
    *,
    pack_sha256: str,
    draft_sha256: str,
    fact_sources: list[dict],
    now: datetime,
) -> list[str]:
    if not pending:
        return []
    if not review:
        return ["manual review artifact is required"]
    errors: list[str] = []
    if review.get("pack_sha256") != pack_sha256:
        errors.append("review pack_sha256 does not match")
    if review.get("draft_sha256") != draft_sha256:
        errors.append("review draft_sha256 does not match")
    if not str(review.get("reviewer") or "").strip():
        errors.append("reviewer is required")
    expected = {item["id"] for item in pending}
    checks = review.get("checks")
    if not isinstance(checks, list):
        checks = []
        errors.append("review checks must be a list")
    actual = {item.get("id") for item in checks if isinstance(item, dict)}
    if actual != expected or len(checks) != len(expected):
        errors.append("review checks must exactly match pending_manual_reviews")
    for item in checks:
        if not isinstance(item, dict):
            continue
        if item.get("result") != "pass" or not str(item.get("notes") or "").strip():
            errors.append(f"review check {item.get('id')!r} requires result=pass and notes")
    try:
        reviewed_at = datetime.fromisoformat(str(review.get("reviewed_at") or "").replace("Z", "+00:00"))
        if reviewed_at.tzinfo is None:
            raise ValueError
    except ValueError:
        errors.append("reviewed_at must be an ISO-8601 timestamp with timezone")
        reviewed_at = None
    reviewed_at_utc = reviewed_at.astimezone(timezone.utc) if reviewed_at else None
    if reviewed_at_utc and reviewed_at_utc > now:
        errors.append("reviewed_at cannot be in the future")
    if "semantic_facts" in expected:
        if reviewed_at_utc and reviewed_at_utc <= now and now - reviewed_at_utc > FACT_REVIEW_TTL:
            errors.append("semantic fact review is older than 24 hours")
        if review.get("fact_sources") != fact_sources:
            errors.append("review fact_sources do not match the task fingerprints")
    return errors


def fact_review_expiry(review: dict | None, pending: list[dict]) -> str | None:
    if not review or not any(item["id"] == "semantic_facts" for item in pending):
        return None
    try:
        reviewed_at = datetime.fromisoformat(
            str(review.get("reviewed_at") or "").replace("Z", "+00:00")
        )
        if reviewed_at.tzinfo is None:
            return None
    except ValueError:
        return None
    return (reviewed_at.astimezone(timezone.utc) + FACT_REVIEW_TTL).isoformat()


def validate(
    pack_path: Path,
    draft_path: Path,
    review_path: Path | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    pack_path, draft_path = private(pack_path), private(draft_path)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    draft = draft_path.read_text(encoding="utf-8")
    pack_sha = file_sha256(pack_path)
    draft_sha = file_sha256(draft_path)
    review = None
    review_sha = None
    if review_path is not None:
        review_path = private(review_path)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review_sha = file_sha256(review_path)
    contract = pack["content_contract"]
    missing_verbatim = []
    semantic_review = []
    for item in contract.get("required_facts") or []:
        fact = item if isinstance(item, str) else str(item.get("text") or "")
        mode = "semantic" if isinstance(item, str) else item.get("mode", "semantic")
        if mode == "verbatim" and normalized(fact) not in normalized(draft):
            missing_verbatim.append(fact)
        if fact:
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
            not structure_only_preserves_authored_text(
                source_text, draft, contract.get("structural_labels") or []
            )
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
    source_for_metrics = source_text if isinstance(source_text, str) else ""
    source_for_metrics, missing_removals = without_allowed_removals(
        source_for_metrics, contract.get("allowed_removals") or []
    )
    if missing_removals:
        protected_layer_errors.append("allowed_removals contains fragments absent from source_text")
    metrics = preservation_metrics(source_for_metrics, draft)
    work_profile = contract.get("work_profile")
    if work_profile in {"transcript_to_article", "develop_existing"}:
        for anchor in contract.get("preservation_anchors") or []:
            if normalized(anchor) not in normalized(draft):
                protected_layer_errors.append(f"missing preservation anchor: {anchor}")
        if metrics["source_significant_tokens"] >= 20 and metrics["token_coverage"] < float(contract.get("min_token_coverage") or 0):
            protected_layer_errors.append("draft token coverage is below the work-profile threshold")
        if metrics["source_visible_characters"] >= 200 and metrics["visible_length_ratio"] < float(contract.get("min_length_ratio") or 0):
            protected_layer_errors.append("draft visible-length ratio is below the work-profile threshold")
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
    pending = required_manual_reviews(contract, draft)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    manual_review_errors = review_errors(
        review,
        pending,
        pack_sha256=pack_sha,
        draft_sha256=draft_sha,
        fact_sources=contract.get("fact_sources") or [],
        now=current_time,
    )
    hard_errors = bool(missing_verbatim or unresolved_placeholders or protected_layer_errors)
    status = "needs_fix" if hard_errors else (
        "manual_review_required" if manual_review_errors else "pass"
    )
    return {
        "schema_version": "author-validation-v1",
        "status": status,
        "pack_sha256": pack_sha,
        "draft_sha256": draft_sha,
        "review_sha256": review_sha,
        "validated_at": current_time.isoformat(),
        "missing_verbatim": missing_verbatim,
        "unresolved_placeholders": unresolved_placeholders,
        "protected_layer_errors": protected_layer_errors,
        "inline_binding_review_required_once": inline_binding_review,
        "proofread_change_review_required_once": proofread_review,
        "rewrite_continuity_review_required_once": rewrite_review,
        "semantic_fact_review_required_once": [fact for fact in semantic_review if fact],
        "forbidden_claims_to_check_once": contract.get("forbidden_claims") or [],
        "preservation_metrics": metrics,
        "pending_manual_reviews": pending,
        "manual_review_errors": manual_review_errors,
        "fact_review_expires_at": fact_review_expiry(review, pending),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.pack, args.draft, args.review)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = private(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return {"pass": 0, "needs_fix": 1, "manual_review_required": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
