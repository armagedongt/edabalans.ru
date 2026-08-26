"""Create a reversible, private classification of Telegram Saved Messages.

The tool deliberately uses transparent heuristics only.  It never reads media,
does not modify the Telegram export, and marks uncertain author/meaning cases for
human or stronger-model review.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


URL = re.compile(r"https?://[^\s<>]+|tg://\S+", re.I)
HREF = re.compile(r'''href=["']([^"']+)["']''', re.I)
SPACE = re.compile(r"\s+")
HTML_TAG = re.compile(r"<[^>]+>")
TECHNICAL = re.compile(
    r"^(?:/\w+|https?://\S+$|\d{4}-\d{2}-\d{2}|пароль|логин|код\s+(?:доступа|ответа)|"
    r"utm[ _-]|api[ _-]?key|техническ|задача\s+(?:в|для)\s+(?:разработ|бот))",
    re.I,
)
NUTRITION = re.compile(
    r"похуд|лишн\w*\s+вес|снижен\w*\s+вес|вес\s+(?:уходит|стоит|сниз|набор|тела)|"
    r"весом\b|калори|питан|еда\b|продукт|белок|жир(?:ы|а)?\b|углевод|"
    r"сладк|голод|сытост|дефицит|трениров|спорт|мышц|здоров|переедан|диет",
    re.I,
)
CONTENT = re.compile(
    r"(?:пост|контент|хук|заголов|рилс|reels|сторис|стори|cta|призыв|подводк|"
    r"аудитори|подписч|продаж|оффер|креатив|шаблон|структур|рубри|идея\b)",
    re.I,
)
READY = re.compile(r"(?:\n|[.!?])\s*(?:\n|[А-ЯЁA-Z0-9])")


def private_path(path: Path) -> Path:
    """Reject both input and output paths inside the repository."""
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("saved-notes paths must be outside Git")
    return resolved


def text_source(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for part in value:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            label = str(part.get("text") or "")
            href = part.get("href")
            parts.append(f'<a href="{html.escape(str(href), quote=True)}">{label}</a>' if href else label)
    return "".join(parts)


def plain(value: str) -> str:
    return SPACE.sub(" ", html.unescape(HTML_TAG.sub(" ", value))).strip()


def has_media(message: dict[str, Any]) -> tuple[bool, str | None]:
    if message.get("photo"):
        return True, "photo"
    for key in ("video_file", "voice_message", "video_message", "audio_file", "file"):
        if message.get(key):
            return True, key.removesuffix("_file")
    return False, None


def poll_source(message: dict[str, Any]) -> str:
    poll = message.get("poll")
    if not isinstance(poll, dict):
        return ""
    question = str(poll.get("question") or poll.get("title") or "")
    answers = poll.get("answers") or poll.get("options") or []
    answer_text = [str(answer.get("text") if isinstance(answer, dict) else answer) for answer in answers]
    return "\n".join(part for part in [question, *answer_text] if part)


def source_url(message: dict[str, Any], source: str) -> str | None:
    saved = message.get("saved_from")
    if isinstance(saved, str) and saved.startswith(("http://", "https://", "tg://")):
        return saved
    match = HREF.search(source) or URL.search(source)
    return match.group(1) if match and match.lastindex else match.group(0) if match else None


def classify(message: dict[str, Any], text: str, media: bool) -> tuple[str, str, str, bool]:
    """Return classification, reason, voice eligibility and review flag."""
    short = len(text) < 80
    external = bool(message.get("forwarded_from"))
    if external:
        return "external_reference", "Есть признак пересылки; текст не считается голосом автора.", "not_voice_source", media or short
    if not text:
        return "unknown_review", "Нет доступного текста; смысл может быть в медиа.", "review_required", True
    if TECHNICAL.search(text):
        return "technical_or_service", "Текст похож на команду, доступ или техническую заметку.", "not_voice_source", False
    relevant = bool(NUTRITION.search(text) or CONTENT.search(text))
    if not relevant:
        return "personal_or_off_topic", "Не найден признак темы питания или контентной механики.", "not_voice_source", short or media
    if short:
        return "nutrition_or_content_idea", "Короткая релевантная заметка сохранена как идея, а не как готовый текст.", "review_required", True
    if CONTENT.search(text) and not NUTRITION.search(text):
        return "template_or_mechanic", "Текст описывает контентный приём, шаблон или механику.", "review_required" if media else "candidate", media
    if len(text) >= 500 or READY.search(text):
        return "authored_ready_post", "Развёрнутый релевантный авторский текст без признака пересылки.", "review_required" if media else "candidate", media
    return "authored_draft_or_fragment", "Релевантный авторский фрагмент без признака законченного поста.", "review_required" if media else "candidate", media


def normalized_for_duplicate(text: str) -> str:
    return SPACE.sub(" ", URL.sub("<url>", text)).strip().lower()


def first_source_line(source: str) -> str:
    """Keep line boundaries here: they are evidence for related post variants."""
    first = html.unescape(HTML_TAG.sub(" ", source)).splitlines()[0] if source else ""
    return SPACE.sub(" ", first).strip().lower()


def make_card(message: dict[str, Any]) -> dict[str, Any] | None:
    source = text_source(message.get("text"))
    if not source:
        source = poll_source(message)
    text = plain(source)
    media, kind = has_media(message)
    if not text and not media:
        return None
    classification, reason, voice, review = classify(message, text, media)
    published = message.get("date")
    return {
        "source": "telegram_saved_notes",
        "source_chat_name": "Saved Messages",
        "source_chat_id": str(message.get("saved_from_id") or "") or None,
        "message_id": message.get("id"),
        "published_at": published,
        "source_url": source_url(message, source),
        "text_source": source,
        "text_plain": text,
        "has_media": media,
        "media_kind_or_unknown": kind if media else "not_recorded",
        "forwarded_from": message.get("forwarded_from"),
        "author_hint": message.get("from"),
        "reply_context": message.get("reply_to_message_id"),
        "classification": classification,
        "classification_reason": reason,
        "voice_eligibility": voice,
        "related_message_ids": [],
        "duplicate_of": None,
        "variant_group": None,
        "needs_review": review,
    }


def assign_relationships(cards: list[dict[str, Any]]) -> None:
    seen: dict[tuple[str, str], int] = {}
    variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        text = card["text_plain"]
        if not text:
            continue
        digest = hashlib.sha256(normalized_for_duplicate(text).encode("utf-8")).hexdigest()
        key = (card["classification"], digest)
        if key in seen:
            card["duplicate_of"] = seen[key]
            card["needs_review"] = True
        else:
            seen[key] = card["message_id"]
        # A stable first line is a conservative way to link possible revisions
        # without treating them as duplicates.
        first_line = first_source_line(card["text_source"])
        if len(first_line) >= 20 and card["duplicate_of"] is None:
            variants[first_line].append(card)
    for group_cards in variants.values():
        # Identical text is a duplicate relationship, never a one-card variant.
        distinct_texts = {normalized_for_duplicate(card["text_plain"]) for card in group_cards}
        if len(group_cards) > 1 and len(distinct_texts) > 1:
            ids = [card["message_id"] for card in group_cards]
            group = f"first-line:{hashlib.sha256(','.join(map(str, ids)).encode()).hexdigest()[:12]}"
            for card in group_cards:
                card["variant_group"] = group
                card["related_message_ids"] = [value for value in ids if value != card["message_id"]]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def build_report(cards: list[dict[str, Any]], skipped: int, source_count: int, output: Path) -> dict[str, Any]:
    counts = Counter(card["classification"] for card in cards)
    report = {
        "source": "telegram_saved_notes",
        "source_message_records": source_count,
        "saved_cards": len(cards),
        "skipped_empty_or_service": skipped,
        "coverage_ok": len(cards) + skipped == source_count,
        "classification_counts": dict(sorted(counts.items())),
        "voice_eligibility_counts": dict(sorted(Counter(card["voice_eligibility"] for card in cards).items())),
        "with_media": sum(card["has_media"] for card in cards),
        "exact_duplicates": sum(card["duplicate_of"] is not None for card in cards),
        "variant_groups": len({card["variant_group"] for card in cards if card["variant_group"]}),
        "review_queue": sum(card["needs_review"] for card in cards),
        "files": {name: str(output / name) for name in OUTPUTS},
    }
    return report


OUTPUTS = (
    "all-messages.jsonl", "author-relevant-candidates.jsonl", "content-ideas.jsonl",
    "external-references.jsonl", "context-or-excluded.jsonl", "review-queue.jsonl",
)


def run(source: Path, output: Path) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("type") != "saved_messages" or not isinstance(payload.get("messages"), list):
        raise ValueError("expected a Telegram Desktop Saved Messages export")
    output.mkdir(parents=True, exist_ok=True)
    cards = [card for message in payload["messages"] if (card := make_card(message)) is not None]
    assign_relationships(cards)
    by_class = defaultdict(list)
    for card in cards:
        by_class[card["classification"]].append(card)
    write_jsonl(output / "all-messages.jsonl", cards)
    write_jsonl(output / "author-relevant-candidates.jsonl", [card for card in cards if card["classification"] in {"authored_ready_post", "authored_draft_or_fragment", "nutrition_or_content_idea", "template_or_mechanic"}])
    write_jsonl(output / "content-ideas.jsonl", [card for card in cards if card["classification"] in {"nutrition_or_content_idea", "template_or_mechanic"}])
    write_jsonl(output / "external-references.jsonl", by_class["external_reference"])
    write_jsonl(output / "context-or-excluded.jsonl", [card for card in cards if card["classification"] in {"personal_or_off_topic", "technical_or_service", "unknown_review"}])
    write_jsonl(output / "review-queue.jsonl", [card for card in cards if card["needs_review"]])
    report = build_report(cards, len(payload["messages"]) - len(cards), len(payload["messages"]), output)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Разбор сохранённых Telegram-заметок", "", "Результат создан локально вне Git. Автоклассификация осторожная: очередь review не является удалением.", "", "## Количества", ""]
    lines += [f"- {name}: {count}" for name, count in report["classification_counts"].items()]
    lines += ["", f"Покрытие: {report['saved_cards']} карточек + {report['skipped_empty_or_service']} пустых/сервисных = {report['source_message_records']} исходных записей.", f"Очередь ручной проверки: {report['review_queue']}. Точных дублей: {report['exact_duplicates']}; групп возможных вариантов: {report['variant_groups']}.", "", "## Характерные примеры для проверки", ""]
    examples: list[dict[str, Any]] = []
    for classification in sorted({card["classification"] for card in cards}):
        examples.extend([card for card in cards if card["classification"] == classification and card["text_plain"]][:2])
    for card in examples[:15]:
        excerpt = SPACE.sub(" ", card["text_plain"])[:180]
        lines.append(f"- `{card['classification']}`, message_id {card['message_id']}: {excerpt} — {card['classification_reason']}")
    lines += ["", "## Следующий вход в авторский каталог", "", f"Подключать только `{output / 'author-relevant-candidates.jsonl'}`. Идеи для отдельного поиска: `{output / 'content-ideas.jsonl'}`."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify a private Telegram Saved Messages export without media analysis")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(private_path(args.source), private_path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
