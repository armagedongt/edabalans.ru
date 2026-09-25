"""Build the editorial disposition registry for long-form author materials.

The registry is a navigation/decision layer. It never stores full source bodies and
does not replace the server Knowledge Library. Inputs are the accepted blog
manifest, confirmed cross-platform family decisions, and the latest read-only
long-form audit snapshot.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "content/blog/manifest.json"
CONFIRMED_FAMILIES_PATH = (
    ROOT / "content/author-voice/source-selection/blog-source-families.json"
)
AUDIT_PATH = ROOT / "work/blog-audit-20260917/catalog.json"
SUPPLEMENTS_PATH = ROOT / "content/author-voice/source-selection/article-source-supplements.json"
REGISTRY_PATH = (
    ROOT / "content/author-voice/source-selection/article-source-registry.json"
)
REPORT_PATH = (
    ROOT / "content/author-voice/source-selection/article-source-registry.md"
)

BLOG_BASE = "https://blog.похудение-это-есть.рф/articles/"


# Explicit owner decisions from the article review. These are routing decisions,
# not editorial rewrites and not permissions to disclose paid material.
OWNER_OVERRIDES: dict[str, tuple[str, str]] = {
    "A004": ("deferred_not_now", "«10 000 и 1 шаг» пока не брать."),
    "A007": ("deferred_not_now", "Ответ про питание на работе не подходит."),
    "A011": ("deferred_not_now", "«Как стать толстым ЗОЖником» убрать в сторону."),
    "A013": ("deferred_not_now", "План на велосипеде не подходит."),
    "A022": ("deferred_not_now", "Материал про перекусы пока убрать."),
    "A026": ("deferred_not_now", "Способы восстановления пока не брать."),
    "A032": ("deferred_not_now", "Материал про мотивацию пока не брать."),
    "A033": ("deferred_not_now", "Тренировки для обычного человека пока не брать."),
    "A040": ("owner_review_later", "Владелец пока не помнит материал; нужен отдельный просмотр."),
    "A042": ("deferred_not_now", "Каши и похудение пока не брать."),
    "A055": ("deferred_not_now", "Последствия похудения на 40 кг пока не брать."),
    "A068": ("deferred_not_now", "«Идеальный завтрак» убрать в сторону."),
    "A080": ("deferred_not_now", "«Никому не рассказывайте» не брать."),
    "A107": ("deferred_not_now", "«10 000 и 1 шаг» пока не брать."),
    "A119": ("incomplete_draft", "«100 способов сжечь жир» недоделано."),
    "A124": ("obsolete_product_archive", "Решение Сергея 25.09.2026: «Пять вкусов еды» — неактуальный архив старого МК. Сохранить исходник; не предлагать для публикации и не использовать как актуальную авторскую основу."),
    "A131": ("private_product_material", "Рецепт цельнозернового риса не публиковать в открытом блоге."),
    "A143": ("private_product_material", "Два соуса — закрытые рецепты Мастер-класса."),
    "A158": ("deferred_not_now", "«Как стать толстым ЗОЖником» убрать в сторону."),
    "A163": ("obsolete_product_archive", "Решение Сергея 25.09.2026: «Кухонные дела» — неактуальный архив старого МК. Сохранить исходник; не предлагать для публикации и не использовать как актуальную авторскую основу."),
    "A175": ("deferred_not_now", "Материал про перекусы пока убрать."),
    "A189": ("private_product_material", "Материал Мастер-класса."),
    "A199": ("deferred_not_now", "Синдром отложенной жизни пока не брать."),
    "A203": ("obsolete_product_archive", "Решение Сергея 25.09.2026: «Средиземноморская диета» (Telegraph /Sredizemnomorskaya-dieta-12-07) — неактуальный архив старого МК. Сохранить исходник; не предлагать для публикации и не использовать как актуальную авторскую основу."),
    "A212": ("incomplete_draft", "«Витамин N» — черновик."),
    "A216": ("private_product_material", "Материал Мастер-класса."),
    "A222": ("private_product_material", "Материал Мастер-класса."),
    "A229": ("deferred_not_now", "«Идеальный завтрак» убрать в сторону."),
    "A230": ("owner_review_later", "Владелец пока не помнит материал; нужен отдельный просмотр."),
    "A234": ("private_product_material", "Материал Мастер-класса."),
    "A249": ("private_product_material", "Материал Мастер-класса."),
    "A251": ("private_product_material", "Материал Мастер-класса."),
    "A255": ("obsolete_product_archive", "Решение Сергея 25.09.2026: «Правило Гарвардской Здоровой Тарелки» — неактуальный архив старого МК. Сохранить исходник; не предлагать для публикации и не использовать как актуальную авторскую основу."),
    "A276": ("deferred_not_now", "Материал про перекусы пока убрать."),
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_urls(article: dict[str, Any]) -> list[str]:
    provenance = article.get("source_provenance") or {}
    urls = list(provenance.get("urls") or [])
    if provenance.get("url"):
        urls.append(provenance["url"])
    return list(dict.fromkeys(url.rstrip("/") for url in urls if url))


def source_external_ids(article: dict[str, Any]) -> list[str]:
    provenance = article.get("source_provenance") or {}
    values = [str(value) for value in provenance.get("external_ids") or []]
    source_id = str(article.get("source_id") or "")
    if source_id:
        values.append(source_id)
    return list(dict.fromkeys(values))


def compact_source(row: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "catalog_id": row["key"],
        "source": row["source"],
        "external_id": str(row["external_id"]),
        "title": row["title"],
        "url": row["url"],
        "published_at": row.get("published_at"),
        "characters": row.get("characters"),
        "role": role,
        "provenance": row.get("provenance"),
        "text_sha256": row.get("text_sha256"),
    }


def classify_deferred(row: dict[str, Any]) -> tuple[str, str]:
    if row["key"] in OWNER_OVERRIDES:
        return OWNER_OVERRIDES[row["key"]]
    decision = row.get("decision") or ""
    if "учебный материал курса" in decision:
        return "private_product_material", "Учебный материал курса; не публиковать автоматически."
    if "служебный/продающий или посторонний формат" in decision:
        return "technical_or_service", "Служебная, продающая, техническая или посторонняя страница."
    if "черновик/заметка" in decision:
        return "incomplete_draft", "Черновик или заметка; нужна проверка законченности."
    if "Резерв 3000–3999" in decision:
        return "short_reserve", "Материал 3000–3999 знаков; сначала оценить самостоятельную пользу."
    return "editorial_review", "Полный материал; нужна редакторская оценка семьи, пользы и актуальности."


def build() -> tuple[dict[str, Any], str]:
    manifest = load_json(MANIFEST_PATH)
    audit = load_json(AUDIT_PATH)
    confirmed = load_json(CONFIRMED_FAMILIES_PATH)
    supplements = load_json(SUPPLEMENTS_PATH)

    rows = audit["articles"]
    by_key = {row["key"]: row for row in rows}
    by_external: dict[str, list[dict[str, Any]]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_external.setdefault(str(row["external_id"]), []).append(row)
        by_url[row["url"].rstrip("/")] = row

    accepted_by_source_id: dict[str, dict[str, Any]] = {}
    for family in confirmed.get("families", []):
        blog_canon = family.get("blog_canon") or {}
        source_id = str(blog_canon.get("source_id") or family.get("preferred_basis") or "")
        if source_id:
            accepted_by_source_id[source_id] = family
        for member in family.get("members", []):
            external_id = str(member.get("external_id") or "")
            if external_id:
                accepted_by_source_id.setdefault(external_id, family)

    assigned: set[str] = set()
    published_families: list[dict[str, Any]] = []

    for article in manifest["articles"]:
        matched: dict[str, tuple[dict[str, Any], str]] = {}
        for url in source_urls(article):
            if url in by_url:
                matched[by_url[url]["key"]] = (by_url[url], "direct_source")
        for external_id in source_external_ids(article):
            for row in by_external.get(external_id, []):
                matched[row["key"]] = (row, "direct_source")

        accepted_family = accepted_by_source_id.get(str(article["source_id"]))
        if not accepted_family:
            accepted_family = next(
                (
                    family
                    for family in confirmed.get("families", [])
                    if (family.get("blog_canon") or {}).get("slug") == article["slug"]
                ),
                None,
            )
        if accepted_family:
            for member in accepted_family.get("members", []):
                row = by_key.get(member.get("catalog_id"))
                if row:
                    matched[row["key"]] = (row, member.get("role") or "confirmed_family_member")

        members = []
        for key, (row, role) in sorted(matched.items()):
            assigned.add(key)
            members.append(compact_source(row, role))
        if accepted_family:
            for member in accepted_family.get("members", []):
                if member.get("catalog_id") not in by_key:
                    members.append(dict(member))

        provenance = article.get("source_provenance") or {}
        if not members and provenance.get("platform") == "tilda":
            members.append(
                {
                    "catalog_id": f"tilda-page:{provenance['page_id']}",
                    "source": "tilda",
                    "external_id": str(provenance["page_id"]),
                    "title": article["title"],
                    "url": provenance.get("url"),
                    "published_at": None,
                    "characters": None,
                    "role": "direct_source",
                    "provenance": {
                        "project_id": provenance.get("project_id"),
                        "html_sha256": provenance.get("html_sha256"),
                        "retrieved_at": provenance.get("retrieved_at"),
                    },
                }
            )

        candidate_keys = sorted(
            {
                candidate
                for key in matched
                for candidate in (by_key[key].get("matching_candidates") or [])
                if candidate not in matched
            }
        )
        published_families.append(
            {
                "family_id": f"blog:{article['slug']}",
                "title": article["title"],
                "disposition": "canonical_blog",
                "canonical": {
                    "source_id": article["source_id"],
                    "slug": article["slug"],
                    "url": BLOG_BASE + article["slug"],
                    "body_file": f"content/blog/articles/{article['body_file']}",
                    "status": article["status"],
                },
                "members": members,
                "possible_duplicate_catalog_ids": candidate_keys,
                "family_evidence": "owner_confirmed" if accepted_family else "direct_provenance",
            }
        )

    deferred_families: list[dict[str, Any]] = []
    for row in rows:
        if row["key"] in assigned:
            continue
        subtype, reason = classify_deferred(row)
        deferred_families.append(
            {
                "family_id": f"deferred:{row['key']}",
                "title": row["title"],
                "disposition": "deferred",
                "deferred_kind": subtype,
                "reason": reason,
                "members": [compact_source(row, "unmerged_source")],
                "possible_duplicate_catalog_ids": row.get("matching_candidates") or [],
                "family_evidence": "single_source_pending_family_review",
            }
        )

    canonical_external_ids = {str(m.get("external_id")) for f in published_families for m in f["members"]}
    for source in supplements["sources"]:
        if source["external_id"] in canonical_external_ids:
            continue
        deferred_families.append({
            "family_id": "deferred:" + source["catalog_id"], "title": source["title"],
            "disposition": "deferred", "deferred_kind": source["deferred_kind"],
            "reason": source["reason"], "members": [{**source, "role": "unmerged_source"}],
            "possible_duplicate_catalog_ids": [], "family_evidence": "single_source_pending_family_review",
        })
    for alias in supplements["title_aliases"]:
        family = next(f for f in published_families + deferred_families
                      if any(m["catalog_id"] == alias["catalog_id"] for m in f["members"]))
        family["title_aliases"] = [alias["requested_title"]]
        if family["disposition"] == "deferred":
            family["owner_decision"] = alias["decision"]
            family["reason"] = alias["basis"]
    deferred_counts = Counter(item["deferred_kind"] for item in deferred_families)
    source_counts = Counter(row["source"] for row in rows)
    registry = {
        "schema_version": 1,
        "updated_at": "2026-09-25",
        "module_id": "platform.content",
        "scope": {
            "included": "Известные длинные авторские материалы Pikabu, Telegraph и VC.ru объёмом от 3000 знаков, а также опубликованные статьи собственного блога и подтверждённые Tilda-основы.",
            "excluded": "Редакторский разбор самостоятельных коротких постов. Telegram-анонсы, ссылки и длинные версии связываются с семьями статей в приватном производном отчёте.",
            "source_snapshot": "work/blog-audit-20260917/catalog.json",
            "source_snapshot_limits": [
                "Свежий Telegraph getPageList без токена не подтверждён; известные страницы были проверены поштучно 17.09.2026.",
                "Полнота текущего профиля Pikabu после даты локального корпуса не подтверждена.",
                "В проверенном локальном корпусе источников Дзен не найдено; это пробел discovery, а не доказательство отсутствия публикаций.",
                "Производная навигационная карта зарегистрирована в Knowledge Library; кандидаты на совпадение не превращены в подтверждённые связи семей.",
            ],
        },
        "library_sync": {
            "status": "navigation_registered",
            "target": "edabalans Knowledge Library",
            "uri": "knowledge://resource/article-family-routing",
            "action": "Пересобирать внутреннюю навигационную карту после изменения канонов; спорные пары оставлять в очереди сравнения. Сообщения автоматически не редактируются.",
        },
        "rules": {
            "content_forms": "Два представления единого каталога: long_material и short_post. Площадка Telegram не определяет тип; длинная статья может целиком помещаться в сообщении.",
            "telegram_relations": "references_article означает анонс/ссылку, previous_version — подтверждённую старую редакцию; semantic_overlap_candidate требует сравнения. Анонс не становится дублем статьи.",
            "publication_evidence": "Отдельно учитывать наличие полного текста, анонс в канале, шаблон бота и подтверждённую отправку. Не найдено в снимке не означает никогда не публиковалось.",
            "private_link_map": "tools/build_article_channel_links.py создаёт приватную карту сообщений, версий и будущих замен. Сообщения автоматически не редактируются; перед заменой нужны свежий текст и однозначный опубликованный канон.",
            "two_buckets": "Каждая известная статья находится либо в canonical_blog, либо в deferred. Третьего пользовательского состояния нет.",
            "blog_canon": "Опубликованная запись content/blog/manifest.json — канон семьи. Внешние публикации являются проявлениями и не перезаписывают блог автоматически.",
            "safe_family_merge": "В одну семью объединяются только подтверждённые источники. Возможное текстовое пересечение хранится как possible_duplicate_catalog_ids и требует проверки.",
            "private_boundary": "Материалы Мастер-класса и курсов остаются в deferred/private_product_material и не получают разрешение на открытую публикацию.",
            "raw_sources": "Реестр хранит ссылки, идентификаторы, хеши и решения, но не копирует full source и не заменяет серверный Knowledge Library.",
        },
        "summary": {
            "known_external_source_records": len(rows),
            "additional_intensive_sources": len(supplements["sources"]),
            "external_sources": dict(sorted(source_counts.items())),
            "canonical_blog_families": len(published_families),
            "canonical_linked_external_records": len(assigned),
            "deferred_families": len(deferred_families),
            "deferred_by_kind": dict(sorted(deferred_counts.items())),
            "candidate_duplicate_pairs": len(audit.get("version_pairs") or []),
        },
        "canonical_blog": sorted(published_families, key=lambda item: item["title"].lower()),
        "deferred": sorted(deferred_families, key=lambda item: item["title"].lower()),
    }

    catalog_ids_in_canon = {
        member["catalog_id"]
        for family in registry["canonical_blog"]
        for member in family["members"]
        if member["catalog_id"].startswith("A")
    }
    catalog_ids_deferred = {
        member["catalog_id"]
        for family in registry["deferred"]
        for member in family["members"]
        if member["catalog_id"].startswith("A")
    }
    expected_catalog_ids = set(by_key)
    if catalog_ids_in_canon & catalog_ids_deferred:
        raise ValueError("A source record is present in both canonical_blog and deferred")
    if catalog_ids_in_canon | catalog_ids_deferred != expected_catalog_ids:
        missing = expected_catalog_ids - (catalog_ids_in_canon | catalog_ids_deferred)
        extra = (catalog_ids_in_canon | catalog_ids_deferred) - expected_catalog_ids
        raise ValueError(f"Registry does not partition the audit catalog: missing={missing}, extra={extra}")
    expected_blog_ids = {str(article["source_id"]) for article in manifest["articles"]}
    actual_blog_ids = {
        str(family["canonical"]["source_id"]) for family in registry["canonical_blog"]
    }
    if actual_blog_ids != expected_blog_ids:
        raise ValueError("Registry does not cover every manifest-backed blog article exactly once")
    if any(not family["members"] for family in registry["canonical_blog"]):
        raise ValueError("Every canonical blog family must retain at least one source manifestation")

    lines = [
        "# Единый реестр семей длинных статей",
        "",
        "Статус: `current`  ",
        "Модуль: `platform.content`  ",
        "Обновлено: 25.09.2026",
        "",
        "Машиночитаемый канон решений — [`article-source-registry.json`](article-source-registry.json). Полные тексты остаются в собственных источниках и серверном Knowledge Library; этот реестр хранит только маршрутизацию, provenance и семейные связи.",
        "",
        "## Сводка",
        "",
        f"- В блоге: **{len(published_families)}** канонические семьи.",
        f"- В известном внешнем корпусе: **{len(rows)}** проявления — Pikabu {source_counts['pikabu']}, Telegraph {source_counts['telegraph']}, VC.ru {source_counts['vc.ru']}.",
        f"- Уже привязано к канонам блога: **{len(assigned)}** внешних проявлений.",
        f"- Дополнительно прочитано статей старого интенсива: **{len(supplements['sources'])}**; подтверждённые источники канона не создают вторую семью.",
        f"- Отложено как отдельные безопасные семьи до подтверждения дублей: **{len(deferred_families)}**.",
        f"- Возможных пар пересечения: **{len(audit.get('version_pairs') or [])}**; это очередь проверки, а не автоматически склеенные дубли.",
        "- Короткие посты имеют отдельное представление; ссылки из канала и длинные Telegram-версии связаны с семьями через приватную карту `article-channel-links.json` (см. ARTICLE_SOURCE_LINKING.md).",
        "",
        "## Канон в блоге",
        "",
        "| Статья | Канон | Привязанные внешние проявления | Возможные версии на проверку |",
        "|---|---|---:|---:|",
    ]
    for family in registry["canonical_blog"]:
        canonical = family["canonical"]
        lines.append(
            f"| {family['title'].replace('|', '/')} | [blog:{canonical['slug']}]({canonical['url']}) | {len(family['members'])} | {len(family['possible_duplicate_catalog_ids'])} |"
        )

    lines += [
        "",
        "## Отложенный корпус по типам",
        "",
        "| Тип | Количество | Что означает |",
        "|---|---:|---|",
    ]
    descriptions = {
        "editorial_review": "Полная статья-кандидат: проверить семейство, пользу, актуальность и выбрать основу.",
        "short_reserve": "Материал 3000–3999 знаков: сначала решить, является ли самостоятельной статьёй.",
        "private_product_material": "Курс или Мастер-класс: не публиковать автоматически.",
        "obsolete_product_archive": "Неактуальный архив старого МК: сохранить для истории, не предлагать к публикации и не использовать как актуальную авторскую основу.",
        "technical_or_service": "Техническая страница, сценарий, услуга, продажная или посторонняя сущность.",
        "incomplete_draft": "Черновик/заметка: не считать готовой статьёй.",
        "deferred_not_now": "Владелец прямо решил пока не брать.",
        "owner_review_later": "Нужен отдельный просмотр владельцем.",
    }
    for kind, count in sorted(deferred_counts.items()):
        lines.append(f"| `{kind}` | {count} | {descriptions[kind]} |")

    lines += [
        "",
        "## Все отложенные материалы",
        "",
        "| ID | Источник | Материал | Статус | Возможные версии |",
        "|---|---|---|---|---:|",
    ]
    for family in registry["deferred"]:
        member = family["members"][0]
        title = family["title"].replace("|", "/")
        lines.append(
            f"| {member['catalog_id']} | {member['source']} | [{title}]({member['url']}) | `{family['deferred_kind']}` | {len(family['possible_duplicate_catalog_ids'])} |"
        )

    lines += [
        "",
        "## Непокрытые источники и синхронизация",
        "",
        "- В текущем локальном корпусе нет источников Дзен. Нужен отдельный discovery по аккаунту/экспорту, если такие публикации существуют.",
        "- Производная карта зарегистрирована в серверном Библиотекаре: `knowledge://resource/article-family-routing`. Она хранит маршруты, ссылки и очередь сравнения; неподтверждённые пары не повышены до доказанных дублей.",
        "- Telegraph: известные 211 страниц были перечитаны 17.09.2026, но свежий список аккаунта без токена не подтверждён.",
        "- Pikabu: использованы серверная библиотека и локальные полные корпуса; публикации после даты снимка требуют следующего refresh.",
        "",
    ]
    return registry, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail when committed outputs differ")
    args = parser.parse_args()
    registry, report = build()
    json_text = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    report_text = report + "\n"
    if args.check:
        if not REGISTRY_PATH.exists() or REGISTRY_PATH.read_text(encoding="utf-8") != json_text:
            raise SystemExit("article-source-registry.json is stale")
        if not REPORT_PATH.exists() or REPORT_PATH.read_text(encoding="utf-8") != report_text:
            raise SystemExit("article-source-registry.md is stale")
        return 0
    REGISTRY_PATH.write_text(json_text, encoding="utf-8")
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(json.dumps(registry["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
