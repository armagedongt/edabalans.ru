"""Build a private, source-linked author-voice corpus from the local catalog.

The command is deliberately deterministic and does not call an LLM. It performs
cheap filtering, provenance checks, exact clustering, candidate ranking and
fragment extraction so that semantic review spends context only on useful text.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCHEMA_VERSION = "1.0"
ANALYSIS_VERSION = "voice-v1-local-prep-20260826"
HTML_TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"[ \t\r\f\v]+")
URL = re.compile(r"https?://\S+|tg://\S+", re.I)
SENTENCE = re.compile(r"(?<=[.!?…])\s+")
PRODUCT = re.compile(r"\b(мастер-?класс|интенсив|калорийн\w* курс|консультац\w*|сопровожд\w*|каталог\w* рецепт)\b", re.I)
CTA = re.compile(r"\b(жмите|нажимайте|переходите|открывайте|читайте|пишите|забирайте|приходите|выбирайте|худеть|записаться|купить)\b", re.I)
PAIN = re.compile(r"\b(не получается|срыв\w*|голод\w*|тяга\w*|устал\w*|надоело|боюсь|страшно|стыд\w*|вина|сил\w* вол|вес.*верн|не можете|не получается)\b", re.I)
OBJECTION = re.compile(r"\b(спросите вы|а как же|можно возразить|может показаться|кажется|скажете|но ведь|внимание[, ]+вопрос)\b", re.I)
REFRAME = re.compile(r"\b(на самом деле|не [^.?!]{2,100}, а |вместо [^.?!]{2,100}[—–-]|дело не в|проблема не в|только вот|вот и получается)\b", re.I)
PRACTICE = re.compile(r"\b(сделайте|попробуйте|начните|выберите|добавьте|уберите|шаг|правил\w*|что делать|как выбрать|план)\b", re.I)
PROOF = re.compile(r"\b(исследован\w*|источник|по данным|дневник\w*|ккал|белк\w*|жир\w*|\d+[.,]?\d*\s*(?:%|кг|г|ккал|дн|лет))\b", re.I)
PERSONAL = re.compile(r"\b(я |мне |меня |мой |моя |мои |у меня|со мной|мы )", re.I)
HUMOR = re.compile(r"\b(успех|епона|хрен|хуй|пиздец|жирно|ну вы поняли|простите|лох\w*|подошв\w*|монастыр\w*)\b|[😂😅🤣]", re.I)


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("private voice artifacts must stay outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def visible_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(?:p|div|li|h[1-6]|blockquote)>", "\n", value, flags=re.I)
    value = HTML_TAG.sub("", value)
    lines = [SPACE.sub(" ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def normalized_hash(text: str) -> str | None:
    # Replace URLs before punctuation is stripped; after stripping, the URL
    # regex can no longer recognize a link and link-only copies look different.
    compact = URL.sub(" ", text.casefold())
    compact = re.sub(r"\W+", " ", compact, flags=re.UNICODE).strip()
    if not compact:
        return None
    compact = URL.sub(" url ", compact)
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


def artifacts_ready(output: Path, names: tuple[str, ...], sqlite_name: str) -> bool:
    """A checkpoint is reusable only while every required artifact is usable."""
    paths = [output / name for name in names]
    if any(not path.is_file() or path.stat().st_size == 0 for path in paths):
        return False
    index = output / sqlite_name
    if not index.is_file() or index.stat().st_size == 0:
        return False
    try:
        with closing(sqlite3.connect(f"file:{index.as_posix()}?mode=ro", uri=True)) as db:
            healthy = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            has_fts = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'voice_fts'").fetchone() is not None
            return healthy and has_fts
    except sqlite3.Error:
        return False


def paragraphs(card: dict) -> list[str]:
    text = visible_text(card.get("text_source") or card.get("text_plain") or "")
    parts = [part.strip() for part in re.split(r"\n{1,}", text) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in SENTENCE.split(text) if part.strip()]
    return parts


def surface(card: dict) -> str:
    source = card["source"]
    if source == "telegram_channel":
        return "telegram_channel"
    if source == "bot_constructor":
        return "bot_sequence"
    if source == "pikabu":
        return "pikabu_article"
    if source == "tilda_site":
        kind = (card.get("context") or {}).get("site_page_kind") or "unknown"
        return "tilda_article" if kind in {"article_or_editorial", "free_intensive_lesson"} else "tilda_landing"
    if source == "telegraph":
        return "telegraph_article_or_draft"
    return source


def authorship(card: dict) -> str:
    context = card.get("context") or {}
    if context.get("authorship_auto"):
        return context["authorship_auto"]
    if card["source"] in {"telegram_channel", "bot_constructor", "tilda_site", "telegraph"}:
        return "template_or_service" if card["reuse_catalog"] == "retained_context" else "own_published"
    return "authorship_uncertain"


def era(card: dict) -> str:
    value = card.get("published_at") or ""
    match = re.match(r"(20\d{2})", value)
    if not match:
        return "undated"
    year = int(match.group(1))
    if year <= 2023:
        return "early_2023_or_older"
    if year == 2024:
        return "middle_2024"
    return "current_2025_plus"


def dominant_job(card: dict) -> str:
    text = card.get("text_plain") or ""
    roles = set(card.get("editorial_roles_auto") or [])
    context = card.get("context") or {}
    scenario = (context.get("scenario") or "").casefold()
    if roles.intersection({"service_operation", "calculator_or_form_step", "subscription_or_update_notice", "micro_ui_marker", "garbage_or_placeholder"}):
        return "service"
    if roles.intersection({"sequence_navigation", "reference_link_or_content_handoff", "welcome_or_onboarding"}) and len(text) < 1000:
        return "navigation"
    product_hits = len(PRODUCT.findall(text))
    if "product_offer" in roles and (len(text) < 1400 or product_hits >= 3):
        return "sales"
    if any(token in scenario for token in ("продаж", "оплат", "скидк", "консультац")) and product_hits:
        return "sales"
    if "personal_story" in roles or (len(PERSONAL.findall(text[:1200])) >= 3 and len(text) >= 350):
        return "personal"
    if ("diagnostic_dialogue" in roles or text.count("?") >= 3) and len(text) < 1400:
        return "engagement"
    if len(text) >= 300:
        return "education"
    return "navigation" if CTA.search(text) else "service"


def composition(card: dict, job: str) -> list[str]:
    parts = paragraphs(card)
    if not parts:
        return []
    result: list[str] = []
    first = parts[0]
    whole = card.get("text_plain") or ""
    if "?" in first or REFRAME.search(first) or len(first) <= 180:
        result.append("hook")
    if PERSONAL.search(first):
        result.append("scene_or_personal_entry")
    if PAIN.search(whole[: max(500, len(whole) // 3)]):
        result.append("pain_recognition")
    if OBJECTION.search(whole):
        result.append("objection")
    if REFRAME.search(whole):
        result.append("reframe")
    if PROOF.search(whole):
        result.append("proof_or_specifics")
    if job == "education" or len(whole) >= 1200:
        result.append("explanation")
    if PRACTICE.search(whole):
        result.append("practical_value")
    tail = " ".join(parts[-3:])
    if PRODUCT.search(tail):
        result.append("product_bridge")
    if CTA.search(tail):
        result.append("cta")
    if "?" in parts[-1] and "cta" not in result:
        result.append("engagement_question")
    if not result:
        result.append(job)
    return list(dict.fromkeys(result))


def linkout_status(card: dict) -> str | None:
    if card["source"] != "telegram_channel":
        return None
    reviewed = (card.get("context") or {}).get("linkout_status_reviewed")
    if reviewed:
        return reviewed
    links = card.get("links") or []
    has_pikabu = any("pikabu.ru" in str(link).casefold() for link in links) or "pikabu" in (card.get("text_plain") or "").casefold()
    if not has_pikabu:
        return None
    length = len(card.get("text_plain") or "")
    if length < 550:
        return "linkout_teaser_only"
    if length < 1400:
        return "linkout_with_original_value"
    return "standalone_with_reference"


def tone_dials(text: str) -> dict:
    words = re.findall(r"[\wёЁ-]+", text, flags=re.UNICODE)
    sentences = [part for part in SENTENCE.split(text) if part.strip()]
    return {
        "energy": min(4, text.count("!") + text.count("?") // 2),
        "sharpness": min(4, len(HUMOR.findall(text))),
        "technical_depth": min(4, len(PROOF.findall(text)) // 2),
        "personal_presence": min(4, len(PERSONAL.findall(text)) // 3),
        "sales_intensity": min(4, len(PRODUCT.findall(text)) // 2 + (1 if CTA.search(text) else 0)),
        "mean_sentence_words": round(len(words) / max(1, len(sentences)), 1),
    }


def quality_score(card: dict, job: str, composition_map: list[str], author: str) -> int:
    text = card.get("text_plain") or ""
    value = 0
    value += {"pikabu": 5, "telegram_channel": 5, "tilda_site": 3, "bot_constructor": 3, "telegraph": 2}.get(card["source"], 1)
    value += 4 if 700 <= len(text) <= 7000 else 2 if len(text) >= 350 else 0
    value += min(4, len(composition_map) // 2)
    value += 2 if len(paragraphs(card)) >= 4 else 0
    value += 1 if job in {"education", "personal", "sales"} else 0
    value -= 8 if author not in {"own_published", "own_draft", "owner_approved_edit", "own_reply"} else 0
    value -= 6 if card["reuse_catalog"] != "included" else 0
    value -= 4 if card.get("text_usability") == "media_context_required" else 0
    value -= 3 if job == "service" else 0
    value -= 2 if linkout_status(card) == "linkout_teaser_only" else 0
    value -= 2 if era(card) == "early_2023_or_older" else 1 if era(card) == "middle_2024" else 0
    return value


def voice_decision(card: dict, author: str, job: str, exact_duplicate: bool) -> tuple[str, str]:
    text = card.get("text_plain") or ""
    if author == "reply_parent_context":
        return "excluded_reply_parent_context", "Исходный пост сохранён как контекст ответа, но голосу учит только ответ armagedongt."
    if exact_duplicate or card["reuse_catalog"] == "linked_duplicate":
        return "excluded_exact_duplicate", "Точная копия остаётся связанной с основной версией."
    if author == "template_or_service" or job == "service":
        return "excluded_service", "Служебная или техническая карточка не является голосовым эталоном."
    if card["reuse_catalog"] == "retained_context":
        return "retained_context", "Карточка остаётся в каталоге, но требует контекста или проверки."
    if len(text) < 250:
        return "fragment_only", "Текст полезен только как короткий функциональный фрагмент."
    if linkout_status(card) in {"linkout_teaser_only", "linkout_with_original_value"}:
        return "fragment_only", "Ссылочная подводка учит хуку/переходу/CTA, но не телу полного поста."
    return "eligible", "Авторский самостоятельный текст пригоден для семантического review."


def fragment_kind(value: str, position: int, total: int) -> str:
    if position == 0:
        return "hook_or_opening"
    if position >= total - 2 and CTA.search(value):
        return "cta_or_ending"
    if position >= total - 3 and PRODUCT.search(value):
        return "product_bridge"
    if PAIN.search(value):
        return "pain_or_recognition"
    if OBJECTION.search(value):
        return "objection"
    if REFRAME.search(value):
        return "reframe_or_transition"
    if PROOF.search(value):
        return "proof_or_example"
    if PRACTICE.search(value):
        return "practical_action"
    if HUMOR.search(value):
        return "humor_or_sharpness"
    return "explanation_or_body"


def select_exemplars(cards: list[dict], assessments: dict[str, dict]) -> list[dict]:
    source_targets = {
        "education": {"pikabu": 12, "telegram_channel": 10, "tilda_site": 3, "telegraph": 3},
        "sales": {"telegram_channel": 7, "bot_constructor": 7, "tilda_site": 4, "telegraph": 2},
        "personal": {"pikabu": 6, "telegram_channel": 6, "bot_constructor": 1, "telegraph": 1},
        "engagement": {"telegram_channel": 5, "bot_constructor": 4, "pikabu": 1},
        "navigation": {"telegram_channel": 4, "bot_constructor": 4},
    }
    selected: list[dict] = []
    seen_hashes: set[str] = set()
    for job, targets in source_targets.items():
        for source, quota in targets.items():
            pool = [card for card in cards if assessments[card["catalog_id"]]["voice_use"] == "eligible" and assessments[card["catalog_id"]]["dominant_job"] == job and card["source"] == source]
            pool.sort(key=lambda card: (-assessments[card["catalog_id"]]["quality_score"], card["catalog_id"]))
            added = 0
            for card in pool:
                assessment = assessments[card["catalog_id"]]
                digest = assessment.get("normalized_text_hash")
                if digest and digest in seen_hashes:
                    continue
                selected.append({
                    "exemplar_id": f"ex:{card['catalog_id']}",
                    "catalog_id": card["catalog_id"],
                    "source": card["source"],
                    "source_url": card.get("source_url"),
                    "headline": card.get("headline"),
                    "text": visible_text(card.get("text_source") or card.get("text_plain") or ""),
                    "dominant_job": job,
                    "composition_map": assessment["composition_map"],
                    "surface_context": assessment["surface_context"],
                    "quality_score": assessment["quality_score"],
                    "semantic_status": "candidate_for_strong_model_review",
                    "limitations": ["media_context_not_analyzed"] if (card.get("media") or {}).get("presence") == "present" else [],
                })
                added += 1
                if digest:
                    seen_hashes.add(digest)
                if added >= quota:
                    break
    return selected


def build_fragments(exemplars: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for exemplar in exemplars:
        parts = [part.strip() for part in exemplar["text"].splitlines() if part.strip()]
        if len(parts) <= 1:
            parts = [part.strip() for part in SENTENCE.split(exemplar["text"]) if part.strip()]
        for position, value in enumerate(parts):
            if len(value) < 25 or len(value) > 1200:
                continue
            kind = fragment_kind(value, position, len(parts))
            if kind == "explanation_or_body" and position not in {1, len(parts) // 2}:
                continue
            before = parts[position - 1][-300:] if position else ""
            after = parts[position + 1][:300] if position + 1 < len(parts) else ""
            digest = hashlib.sha256(f"{exemplar['catalog_id']}:{position}:{value}".encode("utf-8")).hexdigest()[:20]
            rows.append({
                "fragment_id": f"frag:{digest}",
                "catalog_id": exemplar["catalog_id"],
                "source": exemplar["source"],
                "source_url": exemplar.get("source_url"),
                "fragment_kind": kind,
                "text": value,
                "context_before": before,
                "context_after": after,
                "dominant_job": exemplar["dominant_job"],
                "composition_recipe": exemplar["composition_map"],
                "cluster_id": exemplar["catalog_id"],
                "media_dependency": "possible" if "media_context_not_analyzed" in exemplar["limitations"] else "none_recorded",
                "semantic_status": "candidate_for_strong_model_review",
            })
    return rows


def build_index(path: Path, assessments: list[dict], exemplars: list[dict], fragments: list[dict]) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            DROP TABLE IF EXISTS assessments;
            DROP TABLE IF EXISTS exemplars;
            DROP TABLE IF EXISTS fragments;
            DROP TABLE IF EXISTS voice_fts;
            CREATE TABLE assessments (catalog_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
            CREATE TABLE exemplars (exemplar_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE fragments (fragment_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE VIRTUAL TABLE voice_fts USING fts5(kind UNINDEXED, item_id UNINDEXED, catalog_id UNINDEXED, headline, text, tags, tokenize='unicode61 remove_diacritics 2');
        """)
        for row in assessments:
            db.execute("INSERT INTO assessments VALUES (?, ?)", (row["catalog_id"], json.dumps(row, ensure_ascii=False)))
        for row in exemplars:
            db.execute("INSERT INTO exemplars VALUES (?, ?, ?)", (row["exemplar_id"], row["catalog_id"], json.dumps(row, ensure_ascii=False)))
            db.execute("INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)", ("exemplar", row["exemplar_id"], row["catalog_id"], row.get("headline") or "", row["text"], " ".join([row["dominant_job"], row["surface_context"], *row["composition_map"]])))
        for row in fragments:
            db.execute("INSERT INTO fragments VALUES (?, ?, ?)", (row["fragment_id"], row["catalog_id"], json.dumps(row, ensure_ascii=False)))
            db.execute("INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)", ("fragment", row["fragment_id"], row["catalog_id"], "", row["text"], " ".join([row["fragment_kind"], row["dominant_job"], *row["composition_recipe"]])))
        db.execute("INSERT INTO voice_fts(voice_fts) VALUES ('optimize')")
        db.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", type=Path, required=True, help="Private enriched author cards JSONL")
    parser.add_argument("--output", type=Path, required=True, help="Private voice version directory")
    parser.add_argument("--linkout-review", type=Path, help="Safe semantic review map for Telegram linkouts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    cards_path = private(args.cards)
    output = private(args.output)
    output.mkdir(parents=True, exist_ok=True)
    digest = source_digest(cards_path)
    linkout_review = {}
    if args.linkout_review:
        payload = json.loads(args.linkout_review.read_text(encoding="utf-8"))
        linkout_review = payload.get("items") or {}
        digest = hashlib.sha256(f"{digest}:{source_digest(args.linkout_review)}".encode("utf-8")).hexdigest()
    state_path = output / "analysis-state.json"
    if state_path.exists() and not args.force:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (
            state.get("source_sha256") == digest
            and state.get("analysis_version") == ANALYSIS_VERSION
            and artifacts_ready(
                output,
                ("source-assessments.jsonl", "exemplar-bank.jsonl", "rhetorical-slots.jsonl", "corpus-report.json"),
                "voice-index.sqlite",
            )
        ):
            print(json.dumps({"status": "cache_hit", "output": str(output), "source_sha256": digest}, ensure_ascii=False))
            return 0

    cards = read_jsonl(cards_path)
    for card in cards:
        reviewed = linkout_review.get(card["catalog_id"])
        if reviewed:
            card.setdefault("context", {})["linkout_status_reviewed"] = reviewed
    hash_groups: dict[str, list[str]] = defaultdict(list)
    for card in cards:
        digest_text = normalized_hash(card.get("text_plain") or "")
        if digest_text:
            hash_groups[digest_text].append(card["catalog_id"])
    source_priority = {"pikabu": 0, "telegram_channel": 1, "tilda_site": 2, "bot_constructor": 3, "telegraph": 4}
    card_by_id = {card["catalog_id"]: card for card in cards}
    canonical_by_hash = {
        key: min(ids, key=lambda item: (source_priority.get(card_by_id[item]["source"], 9), item))
        for key, ids in hash_groups.items()
    }

    assessment_rows: list[dict] = []
    for card in cards:
        digest_text = normalized_hash(card.get("text_plain") or "")
        exact_ids = hash_groups.get(digest_text, []) if digest_text else []
        exact_duplicate = len(exact_ids) > 1 and card["catalog_id"] != canonical_by_hash[digest_text]
        author = authorship(card)
        job = dominant_job(card)
        comp = composition(card, job)
        decision, reason = voice_decision(card, author, job, exact_duplicate)
        assessment_rows.append({
            "schema_version": SCHEMA_VERSION,
            "analysis_version": ANALYSIS_VERSION,
            "catalog_id": card["catalog_id"],
            "source": card["source"],
            "source_url": card.get("source_url"),
            "headline": card.get("headline"),
            "authorship": author,
            "surface_context": surface(card),
            "era": era(card),
            "dominant_job": job,
            "composition_map": comp,
            "tone_dials": tone_dials(card.get("text_plain") or ""),
            "linkout_status": linkout_status(card),
            "normalized_text_hash": digest_text,
            "exact_cluster_ids": exact_ids,
            "related_versions": (card.get("context") or {}).get("related_versions") or [],
            "voice_use": decision,
            "voice_use_reason": reason,
            "reuse_use": card.get("reuse_catalog"),
            "media_status": (card.get("media") or {}).get("presence"),
            "quality_score": quality_score(card, job, comp, author),
            "semantic_status": "needs_strong_model_review" if decision in {"eligible", "fragment_only"} else "deterministic_exclusion",
        })
    by_id = {row["catalog_id"]: row for row in assessment_rows}
    exemplars = select_exemplars(cards, by_id)
    fragments = build_fragments(exemplars)
    write_jsonl(output / "source-assessments.jsonl", assessment_rows)
    write_jsonl(output / "exemplar-bank.jsonl", exemplars)
    write_jsonl(output / "rhetorical-slots.jsonl", fragments)
    build_index(output / "voice-index.sqlite", assessment_rows, exemplars, fragments)
    report = {
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "cards": len(cards),
        "sources": dict(Counter(row["source"] for row in assessment_rows)),
        "authorship": dict(Counter(row["authorship"] for row in assessment_rows)),
        "voice_use": dict(Counter(row["voice_use"] for row in assessment_rows)),
        "dominant_jobs": dict(Counter(row["dominant_job"] for row in assessment_rows)),
        "linkout_status": dict(Counter(row["linkout_status"] for row in assessment_rows if row["linkout_status"])),
        "exact_duplicate_cards": sum(1 for row in assessment_rows if len(row["exact_cluster_ids"]) > 1),
        "exact_clusters": sum(1 for ids in hash_groups.values() if len(ids) > 1),
        "exemplar_candidates": len(exemplars),
        "fragment_candidates": len(fragments),
    }
    (output / "corpus-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    state = {
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "source_sha256": digest,
        "source_cards": len(cards),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint": "local_preparation_complete",
        "strong_model_review": "pending",
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "built", "output": str(output), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
