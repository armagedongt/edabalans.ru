from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RELATED = {
    "skrytye-zapory-i-banalnyy-syuzhet": ["mozhno-li-pit-vo-vremya-edy", "pravila-bezopasnosti-za-shvedskim-stolom", "glikemicheskiy-indeks-eto-lishnee"],
    "dieta-sryv-i-matematika": ["tri-oshibki-v-nachale-pohudeniya", "sdelat-pohudenie-proshche", "net-vremeni-obyasnyat-prosto-hudey"],
    "eti-dolbannye-10000-shagov": ["hodit-chtoby-hudet", "kak-nachat-trenirovki-i-ne-brosit", "kak-ya-100000-shagov-reshil-proyti"],
    "professionalnyy-edok": ["pravila-bezopasnosti-za-shvedskim-stolom", "pp-recepty-eto-ploho", "dieta-sryv-i-matematika"],
    "net-vremeni-obyasnyat-prosto-hudey": ["sdelat-pohudenie-proshche", "tri-oshibki-v-nachale-pohudeniya", "poterya-myshc-pri-pohudenii"],
    "poterya-myshc-pri-pohudenii": ["kak-nachat-trenirovki-i-ne-brosit", "sdelat-pohudenie-proshche", "hodit-chtoby-hudet"],
    "tri-oshibki-v-nachale-pohudeniya": ["net-vremeni-obyasnyat-prosto-hudey", "sdelat-pohudenie-proshche", "hodit-chtoby-hudet"],
    "sdelat-pohudenie-proshche": ["tri-oshibki-v-nachale-pohudeniya", "net-vremeni-obyasnyat-prosto-hudey", "hodit-chtoby-hudet"],
    "hodit-chtoby-hudet": ["eti-dolbannye-10000-shagov", "poterya-myshc-pri-pohudenii", "kak-nachat-trenirovki-i-ne-brosit"],
    "hochesh-hudet-esh-kartoshku": ["glikemicheskiy-indeks-eto-lishnee", "pp-recepty-eto-ploho", "pravila-bezopasnosti-za-shvedskim-stolom"],
    "kak-sdelat-celnozernovoy-ris-sedobnym": ["dva-sousa-krasnoe-i-beloe", "pp-recepty-eto-ploho", "hochesh-hudet-esh-kartoshku"],
    "dva-sousa-krasnoe-i-beloe": ["kak-sdelat-celnozernovoy-ris-sedobnym", "pp-recepty-eto-ploho", "pravila-bezopasnosti-za-shvedskim-stolom"],
    "pravila-bezopasnosti-za-shvedskim-stolom": ["pp-recepty-eto-ploho", "dva-sousa-krasnoe-i-beloe", "mozhno-li-pit-vo-vremya-edy"],
    "mozhno-li-pit-vo-vremya-edy": ["skrytye-zapory-i-banalnyy-syuzhet", "pravila-bezopasnosti-za-shvedskim-stolom", "saharozamenitel-vyzyvaet-rak-net"],
    "saharozamenitel-vyzyvaet-rak-net": ["glikemicheskiy-indeks-eto-lishnee", "pp-recepty-eto-ploho", "mozhno-li-pit-vo-vremya-edy"],
    "kak-ya-100000-shagov-reshil-proyti": ["eti-dolbannye-10000-shagov", "hodit-chtoby-hudet", "kak-nachat-trenirovki-i-ne-brosit"],
    "glikemicheskiy-indeks-eto-lishnee": ["hochesh-hudet-esh-kartoshku", "saharozamenitel-vyzyvaet-rak-net", "pp-recepty-eto-ploho"],
    "pp-recepty-eto-ploho": ["glikemicheskiy-indeks-eto-lishnee", "hochesh-hudet-esh-kartoshku", "dva-sousa-krasnoe-i-beloe"],
    "kak-nachat-trenirovki-i-ne-brosit": ["hodit-chtoby-hudet", "eti-dolbannye-10000-shagov", "poterya-myshc-pri-pohudenii"],
    "a-mne-trener-posovetoval": ["kak-nachat-trenirovki-i-ne-brosit", "poterya-myshc-pri-pohudenii", "sdelat-pohudenie-proshche"],
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


manifest_path = ROOT / "manifest.json"
manifest = read_json(manifest_path)

for item in manifest["items"]:
    slug = item["slug"]
    validation = read_json(ROOT / "machine" / f"{slug}.validation.json")
    review_path = ROOT / "machine" / f"{slug}.review.json"
    review = read_json(review_path) if review_path.exists() else {}
    review_checks = review.get("checks") or []
    review_valid = (
        review.get("schema_version") == "author-review-v1"
        and bool(review_checks)
        and all(check.get("result") == "pass" for check in review_checks)
        and validation.get("review_sha256") == file_sha256(review_path)
    ) if review_path.exists() else False
    item["validation_status"] = validation["status"]
    item["review_status"] = "pass" if review_valid and validation["status"] == "pass" else "hold"
    item["publish_ready"] = item["validation_status"] == "pass" and item["review_status"] == "pass"
    item["suggested_cta"] = item["cta"]
    item["related_candidates"] = RELATED[slug]
    item["editorial_status"] = "ready" if item["publish_ready"] else "review_hold"
    item.pop("hold_reason", None)

manifest["finalized_at"] = datetime.now(timezone.utc).isoformat()
manifest["summary"] = {
    "total": len(manifest["items"]),
    "public_candidates": sum(item["visibility"] == "public" for item in manifest["items"]),
    "internal": sum(item["visibility"] == "internal" for item in manifest["items"]),
    "publish_ready": sum(item["publish_ready"] for item in manifest["items"]),
    "factcheck_hold": sum(not item["publish_ready"] for item in manifest["items"]),
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

handoff = [
    "# Редакционный handoff: подтверждённая партия 20.09.2026",
    "",
    "## Итог партии",
    "",
    f'- Собрано {manifest["summary"]["total"]} Markdown-материалов: {manifest["summary"]["public_candidates"]} публичных кандидатов и {manifest["summary"]["internal"]} служебный.',
    f'- Writer validation/review pass: {manifest["summary"]["publish_ready"]}. На фактчек-модерации: {manifest["summary"]["factcheck_hold"]}.',
    "- Сергей подтвердил сохранение исходной формулировки про гликемический индекс и диабет; решение записано в machine artifact, текст не менялся.",
    "- Все исходные изображения скачаны из exact source, преобразованы в WebP и привязаны локальными путями; внешних hotlink-картинок в статьях нет.",
    "- Площадочные CTA, просьбы о плюсах/подписке/комментариях, старые Telegram- и рекламные хвосты удалены. Упоминание Pikabu сохранено только там, где площадка является фактом самой истории.",
    "- «Как начать тренировки и не бросить» собрано из двух частей истории/челленджа и отдельного материала с восемью советами; все три provenance сохранены.",
    "- Содержательные научные правки в авторский текст не вносились. Решения и первичные источники находятся в `factcheck-notes.md`.",
    "- Новые URL не отправлены в production: действующий Blog API редактирует только зарегистрированные существующие slug и возвращает 404 для новых. Нужен ранее отложенный контур создания статьи/серверного реестра; статическая подмена manifest намеренно не использовалась.",
    "",
]

for item in manifest["items"]:
    status = "готов к интеграции" if item["publish_ready"] else "фактчек-модерация"
    visibility = "служебный" if item["visibility"] == "internal" else "публичный"
    handoff.extend([
        f'## {item["title"]}',
        "",
        f'- Статус: {visibility}; {status}.',
        f'- Slug: `{item["slug"]}`; рубрика: {item["category"]}; CTA-рекомендация: `{item["cta"]}`.',
        f'- Источники: {", ".join(item["sources"])}.',
        f'- Удалено площадочных строк: {len(item.get("removed_platform_tail") or [])}.',
        f'- Локальных WebP: {len(item.get("media") or [])}; hero: `{item.get("hero") or "нет"}`; card: `{item.get("card") or "нет"}`.',
        f'- Validation: `{item["validation_status"]}`; review: `{item["review_status"]}`.',
    ])
    if item.get("hold_reason"):
        handoff.append(f'- Блокер: {item["hold_reason"]}')
    handoff.append("")

(ROOT / "editorial-handoff.md").write_text("\n".join(handoff), encoding="utf-8")

decision = {
    "schema_version": "author-factcheck-decision-v1",
    "slug": "hochesh-hudet-esh-kartoshku",
    "status": "owner_accepted_as_written",
    "blocking_excerpt": "Если вы едите адекватную порцию картофеля в составе сбалансированного приема пищи, то его гликемическим индексом можно пренебречь даже диабетикам",
    "classification": "level_2_with_safety_risk",
    "owner_decision": "Оставить формулировку без изменений.",
    "decided_at": "2026-09-20",
    "body_changed": False,
    "details": "factcheck-notes.md",
}
(ROOT / "machine" / "hochesh-hudet-esh-kartoshku.factcheck-decision.json").write_text(
    json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8"
)
