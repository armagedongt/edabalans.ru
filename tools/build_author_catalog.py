"""Create source-preserving local content cards for the authoring corpus."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path

URL = re.compile(r"https?://[^\s\"<>]+|tg://\S+", re.I)
HTML = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("catalog path must be outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def plain(value: str) -> str:
    return SPACE.sub(" ", html.unescape(HTML.sub(" ", value))).strip()


def signals(text: str) -> list[str]:
    lower = text.lower()
    found = []
    if "?" in text:
        found.append("question_or_hook")
    if any(x in lower for x in ("читайте", "читать", "переходите", "открывайте", "подпис", "купить", "запис", "начать")):
        found.append("cta_or_navigation")
    if any(x in text for x in ("1️⃣", "2️⃣", "→", "✅", "❌")):
        found.append("structured_list_or_steps")
    if "<blockquote>" in text or "«" in text:
        found.append("quote_or_dialogue")
    return found


def placement_hypotheses(scenario: str | None) -> list[str]:
    """Low-risk hints from a scenario name; they are not editorial classifications."""
    value = (scenario or "").lower()
    found = []
    if any(x in value for x in ("оплат", "скидк", "промо", "консультац")):
        found.append("sales_or_conversion")
    if any(x in value for x in ("рассыл", "главный сценарий")):
        found.append("broadcast_or_reengagement")
    if any(x in value for x in ("интенсив", "мини-курс", "день #")):
        found.append("educational_sequence")
    if any(x in value for x in ("меню", "подборка", "словарь")):
        found.append("navigation_or_content_collection")
    if any(x in value for x in ("тест", "калькулятор", "анкета")):
        found.append("diagnostic_or_interactive")
    return found


def voice_eligibility(text: str, scenario: str | None) -> str:
    """A filtering default for voice samples; never a retention/deletion rule."""
    value = (scenario or "").lower()
    if len(plain(text)) < 40:
        return "review_required_low_context"
    if any(x in value for x in ("оплат", "оферт", "чек", "политик", "промо-код")):
        return "not_default_service_text"
    return "candidate"


def media_hypothesis(text: str, headline: str) -> str | None:
    """Describe only the likely rhetorical role from nearby authored text."""
    quote = plain(text)[:220].strip() or plain(headline)[:220].strip()
    if not quote:
        return None
    return f"Предположение: медиа, вероятно, иллюстрирует или обыгрывает мысль «{quote}»."


def telegram_links(item: dict) -> list[str]:
    """Preserve visible URLs and Telegram Desktop text-link entity targets."""
    found = URL.findall(item.get("text_content") or "")
    for block in item.get("blocks") or []:
        for entity in block.get("entities") or []:
            target = entity.get("href") or entity.get("url")
            if target:
                found.append(target)
    if item.get("cta_url"):
        found.append(item["cta_url"])
    return list(dict.fromkeys(found))


def card_from_telegram(item: dict) -> dict:
    text = item.get("text_content") or ""
    has_text = bool(plain(text))
    # The saved Telegram export does not expose attachment metadata.  This is an
    # explicit uncertainty, not a claim that a message has no media.
    return {
        "catalog_id": item["external_id"],
        "source": "telegram_channel",
        "source_url": item.get("canonical_url"),
        "published_at": item.get("published_at"),
        "headline": item.get("title"),
        "text_source": text,
        "text_plain": plain(text),
        "text_usability": "media_context_required" if not has_text else "text_available",
        "context": {"channel": item.get("author_name"), "message_blocks": len(item.get("blocks") or [])},
        "links": telegram_links(item),
        "media": {
            "presence": "unknown_from_source",
            "note": "В исходной выгрузке Telegram нет признака вложения; часть смысла могла быть в медиа.",
        },
        "automatic_signals": signals(text),
        # A textless Telegram record may still be meaningful media, but it cannot
        # be a default text-search result until its media context is inspected.
        "reuse_catalog": "included" if has_text else "retained_context",
        "voice_reference_eligibility": voice_eligibility(text, None),
        "working_status": "candidate",
    }


def card_from_bot(item: dict) -> dict:
    text = item.get("body_source") or ""
    has_media = bool(item.get("media_kind") or item.get("media_path"))
    exclusion_reason = item.get("exclusion_reason")
    reuse_catalog = "linked_duplicate" if exclusion_reason == "duplicate_or_link_only" else "retained_context" if exclusion_reason else "included"
    voice = (
        "not_default_exact_duplicate" if exclusion_reason == "duplicate_or_link_only"
        else "review_required_noncontent" if exclusion_reason
        else voice_eligibility(text, item.get("origin_scenario_name"))
    )
    return {
        "catalog_id": item["code"],
        "source": "bot_constructor",
        "source_url": None,
        "published_at": item.get("created_at"),
        "headline": item.get("title"),
        "text_source": text,
        "text_plain": plain(text),
        "text_usability": "media_context_required" if not plain(text) else "text_available",
        "context": {
            "scenario": item.get("origin_scenario_name"),
            "scenario_id": item.get("origin_scenario_id"),
            "labels": item.get("labels") or [],
            "related_versions": item.get("related_versions") or [],
            "duplicate_of": item.get("duplicate_of"),
            "source_record_status": item.get("working_status") or "candidate",
        },
        "links": URL.findall(text),
        "media": {
            "presence": "present" if has_media else "not_recorded",
            "kind": item.get("media_kind"),
            "path": item.get("media_path"),
            "note": "Медиа не анализируется автоматически; при наличии может дополнять смысл текста.",
            "hypothesis": media_hypothesis(text, item.get("title") or "") if has_media else None,
        },
        "automatic_signals": signals(text),
        "placement_hypotheses": placement_hypotheses(item.get("origin_scenario_name")),
        "reuse_catalog": reuse_catalog,
        "voice_reference_eligibility": voice,
        "working_status": item.get("working_status") or "candidate",
    }


def card_from_site(item: dict) -> dict:
    """Keep public site text source-linked, without treating Tilda as product canon."""
    text = item.get("plain_text") or ""
    kind = item.get("page_kind_auto") or "needs_editorial_review"
    content_kinds = {
        "article_or_editorial", "free_intensive", "free_intensive_lesson",
        "sales_or_offer", "ad_landing_short",
    }
    is_content = kind in content_kinds and len(plain(text)) >= 100
    digest = hashlib.sha256(str(item.get("url") or "").encode("utf-8")).hexdigest()[:20]
    return {
        "catalog_id": f"tilda:{digest}",
        "source": "tilda_site",
        "source_url": item.get("url"),
        "published_at": None,
        "headline": item.get("title"),
        "text_source": text,
        "text_plain": plain(text),
        "text_usability": "text_available" if plain(text) else "media_context_required",
        "context": {
            "site_page_kind": kind,
            "headings": item.get("headings") or [],
            "meta_description": item.get("meta_description"),
            "raw_html_file": item.get("raw_html_file"),
            "site_snapshot": "public read-only collection",
        },
        "links": item.get("links") or [],
        "media": {
            "presence": "present" if item.get("media_links") else "not_recorded",
            "links": item.get("media_links") or [],
            "note": "Медиа не анализируется автоматически; ссылки сохранены рядом с текстом страницы.",
            "hypothesis": media_hypothesis(text, item.get("title") or "") if item.get("media_links") else None,
        },
        "automatic_signals": signals(text),
        "reuse_catalog": "included" if is_content else "retained_context",
        "voice_reference_eligibility": "candidate" if is_content and len(plain(text)) >= 500 else "review_required_low_context",
        "working_status": "candidate" if is_content else "retained_context",
    }


def card_from_telegraph(item: dict) -> dict:
    """Keep Telegraph articles source-linked, including view count at export time."""
    text = item.get("text_plain") or ""
    url = item.get("url") or ""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    media = item.get("media_links") or []
    return {
        "catalog_id": f"telegraph:{digest}",
        "source": "telegraph",
        "source_url": url,
        "published_at": None,
        "headline": item.get("title"),
        "text_source": text,
        "text_plain": plain(text),
        "text_usability": "text_available" if plain(text) else "media_context_required",
        "context": {
            "telegraph_path": item.get("path"),
            "author_name": item.get("author_name"),
            "author_url": item.get("author_url"),
            "description": item.get("description"),
            "views_at_export": item.get("views"),
            "views_error": item.get("views_error"),
            "content_nodes_preserved": True,
        },
        "links": URL.findall(text),
        "media": {
            "presence": "present" if media else "not_recorded",
            "links": media,
            "note": "Ссылки на медиа сохранены. Их смысл не установлен по изображению; гипотеза основана только на соседнем тексте.",
            "hypothesis": media_hypothesis(text, item.get("title") or "") if media else None,
        },
        "automatic_signals": signals(text),
        "reuse_catalog": "included" if len(plain(text)) >= 100 else "retained_context",
        "voice_reference_eligibility": "candidate" if len(plain(text)) >= 500 else "review_required_low_context",
        "working_status": "candidate" if len(plain(text)) >= 100 else "retained_context",
    }


def card_from_pikabu(item: dict, account: str) -> dict:
    """Keep Pikabu stories and performance signals without claiming foreign text as voice."""
    text = item.get("text") or ""
    author_name = item.get("author_name")
    is_own_story = bool(author_name) and author_name.casefold() == account.casefold()
    has_text = bool(plain(text))
    media = item.get("media") or []
    metrics = item.get("metrics") or {}
    if is_own_story and len(plain(text)) >= 100:
        reuse_catalog = "included"
        voice = "candidate" if len(plain(text)) >= 500 else "review_required_low_context"
        working_status = "candidate"
        authorship = "own_published"
    elif is_own_story:
        reuse_catalog = "retained_context"
        voice = "review_required_low_context"
        working_status = "retained_context"
        authorship = "own_published"
    else:
        # These pages belong to Sergey's reply archive, but the page body itself
        # is the parent story. Keep that body as searchable conversation context;
        # only the separately attributed armagedongt reply may teach the voice.
        reuse_catalog = "retained_context"
        voice = "not_default_reply_parent_context"
        working_status = "reply_parent_context"
        authorship = "reply_parent_context"
    return {
        "catalog_id": f"pikabu:{item.get('external_id')}",
        "source": "pikabu",
        "source_url": item.get("canonical_url"),
        "published_at": item.get("published_at"),
        "headline": item.get("title"),
        "text_source": text,
        "text_plain": plain(text),
        "text_usability": "text_available" if has_text else "media_context_required",
        "context": {
            "author_name": author_name,
            "authorship_auto": authorship,
            "tags": item.get("tags") or [],
            "ending_text": item.get("ending_text"),
            "ending_kind": item.get("ending_kind"),
            "cta_text": item.get("cta_text"),
            "cta_url": item.get("cta_url"),
            "recommendations_status": item.get("recommendations_status"),
            "metrics_at_export": metrics,
            "comments_collected": bool(item.get("comments")),
            "foreign_story_may_have_own_reply": not is_own_story,
        },
        "links": item.get("links") or [],
        "media": {
            "presence": "present" if media else "not_recorded",
            "items": media,
            "note": "Медиа не анализируется автоматически; URL и позиция сохранены из снимка Pikabu.",
            "hypothesis": media_hypothesis(text, item.get("title") or "") if media else None,
        },
        "automatic_signals": signals(text),
        "reuse_catalog": reuse_catalog,
        "voice_reference_eligibility": voice,
        "working_status": working_status,
    }


def cards_from_pikabu_replies(item: dict, account: str) -> list[dict]:
    """Create voice-safe cards only for attributable replies by the profile owner."""
    rows = []
    for comment in item.get("comments") or []:
        # Pikabu's owner marker means "author of the parent story", not owner of
        # the profile we are collecting. Voice authorship must be attributable
        # to the explicit armagedongt account name.
        is_own = (comment.get("author_name") or "").casefold() == account.casefold()
        text = comment.get("text") or ""
        if not is_own or not plain(text):
            continue
        external_id = comment.get("external_id")
        rows.append({
            "catalog_id": f"pikabu-reply:{external_id}",
            "source": "pikabu",
            "source_url": comment.get("permalink") or item.get("canonical_url"),
            "published_at": comment.get("published_at"),
            "headline": f"Ответ Сергея к материалу: {item.get('title') or item.get('external_id')}",
            "text_source": text,
            "text_plain": plain(text),
            "text_usability": "text_available",
            "context": {
                "author_name": account,
                "authorship_auto": "own_reply",
                "parent_story_id": item.get("external_id"),
                "parent_story_url": item.get("canonical_url"),
                "parent_story_title": item.get("title"),
                "parent_story_author": item.get("author_name"),
                "parent_comment_id": comment.get("parent_external_id"),
                "comment_depth": comment.get("depth"),
                "comment_rating": comment.get("rating"),
                "comment_pluses": comment.get("pluses"),
                "comment_minuses": comment.get("minuses"),
            },
            "links": URL.findall(text),
            "media": {"presence": "not_recorded", "note": "В текстовом ответе медиа не зафиксировано."},
            "automatic_signals": signals(text),
            "reuse_catalog": "included",
            "voice_reference_eligibility": "candidate" if len(plain(text)) >= 120 else "review_required_low_context",
            "working_status": "candidate",
        })
    return rows


def link_exact_site_duplicates(cards: list[dict]) -> list[dict]:
    """Hide only full same-site copies (for example a UTM landing URL), never variants."""
    seen: dict[str, str] = {}
    result = []
    for card in cards:
        if card["source"] != "tilda_site" or card["reuse_catalog"] != "included":
            result.append(card)
            continue
        normalized = plain(card["text_plain"]).lower()
        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None
        if key and key in seen:
            result.append({
                **card,
                "reuse_catalog": "linked_duplicate",
                "voice_reference_eligibility": "not_default_exact_duplicate",
                "context": {**card["context"], "duplicate_of": seen[key]},
            })
        else:
            if key:
                seen[key] = card["catalog_id"]
            result.append(card)
    return result


def write_jsonl(path: Path, items: list[dict]) -> None:
    path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in items), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    parser.add_argument("--site-pages", type=Path, help="Private JSONL produced by collect_public_site.py")
    parser.add_argument("--telegraph-pages", type=Path, help="Private JSONL produced by collect_telegraph.py")
    parser.add_argument("--pikabu-posts", type=Path, help="Private JSON produced by pikabu_collect.py")
    parser.add_argument("--pikabu-replies", type=Path, help="Targeted private Pikabu snapshot containing owner replies")
    args = parser.parse_args()
    working = private(args.working)
    telegram = read_jsonl(working / "telegram-channel.jsonl")
    bot = read_jsonl(working / "bot-candidates.jsonl") + read_jsonl(working / "bot-excluded.jsonl")
    site = read_jsonl(private(args.site_pages)) if args.site_pages else []
    telegraph = read_jsonl(private(args.telegraph_pages)) if args.telegraph_pages else []
    pikabu_payload = json.loads(private(args.pikabu_posts).read_text(encoding="utf-8")) if args.pikabu_posts else {}
    pikabu = pikabu_payload.get("items") or []
    pikabu_account = ((pikabu_payload.get("source") or {}).get("account") or "armagedongt")
    replies_payload = json.loads(private(args.pikabu_replies).read_text(encoding="utf-8")) if args.pikabu_replies else {}
    reply_cards = [
        card
        for item in replies_payload.get("items") or []
        for card in cards_from_pikabu_replies(item, pikabu_account)
    ]
    cards = (
        [card_from_telegram(item) for item in telegram]
        + [card_from_bot(item) for item in bot]
        + [card_from_site(item) for item in site]
        + [card_from_telegraph(item) for item in telegraph]
        + [card_from_pikabu(item, pikabu_account) for item in pikabu]
        + reply_cards
    )
    cards = link_exact_site_duplicates(cards)
    write_jsonl(working / "author-content-cards.jsonl", cards)
    low_context = [
        {
            "catalog_id": card["catalog_id"],
            "source": card["source"],
            "source_url": card["source_url"],
            "headline": card["headline"],
            "text_plain": card["text_plain"],
            "review_reason": "media_context_required" if card["text_usability"] == "media_context_required" else "very_short_text",
            "context": card["context"],
            "media": card["media"],
        }
        for card in cards
        if card["text_usability"] == "media_context_required" or len(card["text_plain"]) < 40
    ]
    write_jsonl(working / "author-content-review-low-context.jsonl", low_context)
    report = {
        "cards": len(cards),
        "by_source": dict(Counter(card["source"] for card in cards)),
        "media_presence": dict(Counter(card["media"]["presence"] for card in cards)),
        "signal_counts": dict(Counter(signal for card in cards for signal in card["automatic_signals"])),
        "text_usability": dict(Counter(card["text_usability"] for card in cards)),
        "voice_reference_eligibility": dict(Counter(card["voice_reference_eligibility"] for card in cards)),
        "low_context_review": dict(Counter(item["review_reason"] for item in low_context)),
        "bot_placement_hypotheses": dict(Counter(hint for card in cards for hint in card.get("placement_hypotheses", []))),
    }
    (working / "author-content-cards-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
