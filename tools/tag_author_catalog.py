"""Apply reversible, explainable first-pass editorial tags to author content cards."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


RULES: list[tuple[str, re.Pattern[str]]] = [
    ("calculator_or_form_step", re.compile(r"\b(введите|укажите|сколько вам полных лет|для расч[её]та|нажмите [«\"]?(?:рассчитать|загрузить)|расход калорий|энерго_?баланс|пульс в покое)\b", re.I)),
    ("subscription_or_update_notice", re.compile(r"\b(уведомлени\w*.*обновлен|подписк\w*.*уведомлен|любые обновления)\b", re.I)),
    ("reference_link_or_content_handoff", re.compile(r"\b(смотреть запись|читайте пост|перейти в канал|пара слов обо мне в канале|разговорник худеющего)\b", re.I)),
    ("live_event_or_availability_notice", re.compile(r"\b(прямому эфиру|свободных мест|скидок больше нет|запись будет готова|запрос принят)\b", re.I)),
    ("teaser_or_bridge", re.compile(r"\b(сейчас скажу|пост в тему|вот тут пост|просто оставлю их здесь)\b", re.I)),
    ("service_operation", re.compile(r"\b(оплат\w*|касс\w*|оферт\w*|политик\w*|юkassa|промо-?код|чек(?:\s+об\s+)?\s*оплат)\b", re.I)),
    ("sequence_navigation", re.compile(r"\b(меню|подборк\w*|следующ\w* пост|жмите кнопку|кнопк\w* далее|содержание)\b", re.I)),
    ("welcome_or_onboarding", re.compile(r"\b(всем привет|если вы тут первый раз|с чего начать|добро пожаловать)\b", re.I)),
    ("product_offer", re.compile(r"\b(мастер-?класс|интенсив|мини-?курс|тариф|приобрест[ьи]|забирайте курс|цена|скидк\w*)\b", re.I)),
    ("diagnostic_dialogue", re.compile(r"\b(вопрос\s*#?|тест\w*|как вы считаете|с чего мне начать|а как же|спросите вы)\b", re.I)),
    ("practical_plan", re.compile(r"\b(сделайте|план|совет\w*|правил\w*|шаг\w*|чек-?лист|начните|попробуйте)\b", re.I)),
    ("myth_reframe", re.compile(r"\b(миф\w*|не так|на самом деле|ошибк\w*|неправильн\w*|почему это не так|вредн\w*)\b", re.I)),
    ("personal_story", re.compile(r"\b(со мной|у меня история|я поехал|я пробежал|сам через это проходил|в моей жизни|побывал)\b", re.I)),
    ("positioning_proof", re.compile(r"\b(дневник\w* питания|опыт \d+|сотн\w* дневник|тысяч\w* час\w* консультац|я работал лично)\b", re.I)),
    ("announcement_or_reengagement", re.compile(r"\b(сегодня в номере|завтра вас жд[её]т|давно не писал|причина отсутствия|анонс)\b", re.I)),
]


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("catalog path must be outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, items: list[dict]) -> None:
    path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in items), encoding="utf-8")


def tag(card: dict) -> dict:
    searchable = "\n".join((card.get("headline") or "", card.get("text_plain") or "", json.dumps(card.get("context") or {}, ensure_ascii=False)))
    matched = [name for name, pattern in RULES if pattern.search(searchable)]
    compact = (card.get("text_plain") or "").strip()
    if not compact and card.get("media", {}).get("presence") == "present":
        matched.append("media_dependent_reference")
    elif compact and len(compact) <= 4:
        matched.append("micro_ui_marker")
    elif card.get("media", {}).get("presence") == "present" and len(compact) <= 140:
        matched.append("short_media_prompt")
    if re.fullmatch(r"[a-z]{6,}", compact, re.I):
        matched.append("garbage_or_placeholder")
    if not matched and len(compact) < 300:
        matched.append("short_context_fragment")
    # An actual explanatory post without a more specific content tag is still useful.
    if not matched and len(card.get("text_plain") or "") >= 300:
        matched.append("educational_explanation")
    confidence = "review_required" if not matched or "short_context_fragment" in matched or card["text_usability"] == "media_context_required" else "rule_based"
    return {**card, "editorial_roles_auto": matched, "editorial_tag_confidence": confidence}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    args = parser.parse_args()
    working = private(args.working)
    cards = [tag(card) for card in read_jsonl(working / "author-content-cards.jsonl")]
    write_jsonl(working / "author-content-tagged.jsonl", cards)
    report = {
        "cards": len(cards),
        "roles": dict(Counter(role for card in cards for role in card["editorial_roles_auto"])),
        "confidence": dict(Counter(card["editorial_tag_confidence"] for card in cards)),
        "untagged_ids": [card["catalog_id"] for card in cards if not card["editorial_roles_auto"]],
    }
    (working / "author-content-tags-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "untagged_ids"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
