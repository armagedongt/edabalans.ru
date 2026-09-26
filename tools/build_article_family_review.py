"""Render the owner's single family review file without editing article bodies."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "content/author-voice/source-selection"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def build():
    registry = read(BASE / "article-source-registry.json")
    decisions = read(BASE / "article-owner-decisions.json")
    audit = read(ROOT / "work/blog-audit-20260917/catalog.json")
    manifest = read(ROOT / "content/blog/manifest.json")
    states = {key: state for state, ids in decisions["assignments"].items() for key in ids.split()}
    members, parents, original_family = {}, {}, {}
    for family in registry["canonical_blog"] + registry["deferred"]:
        for m in family["members"]:
            key = m["catalog_id"]
            members[key] = m
            parents[key] = key
            original_family[key] = family
    unknown = set(states) - set(members)
    if unknown:
        raise ValueError(f"Unknown decisions: {unknown}")

    def find(k):
        while parents[k] != k:
            k = parents[k]
        return k

    def join(ids):
        ids = list(dict.fromkeys(ids))
        for key in ids[1:]:
            parents[find(key)] = find(ids[0])

    for family in registry["canonical_blog"]:
        join([m["catalog_id"] for m in family["members"]])
    for group in decisions["family_groups"]:
        ids = group["ids"].split()
        if group.get("blog_slug"):
            family = next(f for f in registry["canonical_blog"] if f["canonical"]["slug"] == group["blog_slug"])
            ids += [m["catalog_id"] for m in family["members"]]
        join(ids)
    # Candidate edges group the review workspace only; they never establish duplicates.
    for pair in audit["version_pairs"]:
        if pair["a"] in members and pair["b"] in members:
            join([pair["a"], pair["b"]])
    grouped = {}
    for key in members:
        grouped.setdefault(find(key), []).append(key)
    defaults = {
        "private_product_material": "educational", "obsolete_product_archive": "old_educational",
        "deferred_not_now": "bank", "owner_review_later": "bank",
        "technical_or_service": "service", "incomplete_draft": "manual_review",
        "editorial_review": "family_review", "short_reserve": "family_review",
    }
    labels = {**decisions["states"], "published": "Уже в блоге", "service": "Служебное / постороннее"}
    effective = {}
    for key in members:
        f = original_family[key]
        effective[key] = states.get(key, "published" if f["disposition"] == "canonical_blog" else defaults[f["deferred_kind"]])
    lines = ["# Все статьи: семьи, решения и очередь подготовки", "", "Статус: current · Модуль: platform.content · Обновлено: 26.09.2026", "",
             "## Граница текущего этапа", "", decisions["execution_gate"], "", decisions["editing_constraint"], "",
             "Банк — не планируем брать. На подумать — отдельный ручной просмотр Сергея. Разбор семьи — отдельное сравнение версий, не банк. Учебное и старый архив — не открытые статьи. Существующие статьи блога не скрываются из-за ожидания разбора версий.", "",
             "Это единый обзор всех записей текущего известного корпуса, а не доказательство полноты всех аккаунтов. Группы с машинными пересечениями ниже — рабочие группы сравнения, не автоматически доказанные дубли. Полные исходники остаются в Библиотекаре и приватных снимках.", "",
             "Решения владельца хранятся в article-owner-decisions.json; этот файл пересобирается tools/build_article_family_review.py. Историческая категория deferred_kind не отменяет решения 26.09.2026.", "",
             "## Сводка", "", f"- Канонов блога: {len(registry['canonical_blog'])}.", f"- Записей источников в этом файле: {len(members)}.", f"- Рабочих семей/групп сравнения: {len(grouped)} (не все связи подтверждены).", "",
             "| Состояние источника | Количество |", "|---|---:|"]
    for state, count in sorted(Counter(effective.values()).items()):
        lines.append(f"| {labels[state]} | {count} |")
    lines += ["", "## Одобрено для будущей подготовки", "", "Это задания на следующий этап, не готовые Markdown и не разрешение запускать редактирование сейчас. Во всех случаях: полный источник → сравнение семьи и выбор основы → минимальная площадочная адаптация → медиа → проверки writer → отдельная команда выпуска.", ""]
    for key in sorted(k for k in states if states[k] == "publish_next"):
        m = members[key]
        lines.append(f"- {key}: [{m['title']}]({m['url']}).")
    lines += ["", "## Отдельные назначения и уточнения", ""]
    for key, note in decisions["special_notes"].items():
        lines.append(f"- **{key}**: {note}")
    for group in decisions["family_groups"]:
        lines.append(f"- **{group['ids']}**: {group['note']}")
    lines += ["", "## Проверка прежних изменений", "",
              "В этом этапе body-файлы и manifest блога не изменяются. История Git доказывает, что прежние материалы менялись: переносы Tilda/Pikabu в Markdown, объединённая статья о тренировках, удаления площадочных блоков и замена адресов медиа. Полная построчная проверка всех 44 статей против всех исходных редакций ещё не выполнена — утверждения «ничего не переписывалось» здесь нет.", "",
              "Проверенный пример: commit 645fc01 удалил у японцев блок «Актуально 365 дней в году!» с Dropbox-видео; у блица тот же commit удалил 6 строк. Commit 747d1c6 менял слой чтения/медиа. Материал training-combined-2023.md опубликован одним объединённым текстом: manifest перечисляет 3 источника. Для полной редакторской приёмки нужен отдельный diff с полными основами; этот этап пока не выполнен.", "",
              "Обнаружен отдельный редакторский риск: первый абзац training-combined-2023.md («Эта история началась на Pikabu с короткого бегового челленджа…») присутствует уже в публикационном commit a0cae6f, но его точная фраза не найдена в проверенном author-content-cards.jsonl. Это добавленный при сборке вводный текст, а не только удаление навигации. Проверить на следующем проходе и показать Сергею; сейчас не удалялся и не переписывался.", "",
              "## Все семьи и группы сравнения", ""]
    for num, ids in enumerate(sorted(grouped.values(), key=lambda ids: min(members[k]['title'].lower() for k in ids)), 1):
        canons = {original_family[k]["canonical"]["slug"]: original_family[k]["canonical"] for k in ids if original_family[k].get("canonical")}
        title = members[ids[0]]["title"]
        if canons:
            slug = next(iter(canons))
            title = next(a["title"] for a in manifest["articles"] if a["slug"] == slug)
        relevant = [g for g in decisions["family_groups"] if set(g["ids"].split()) & set(ids)]
        candidate_pairs = [p for p in audit["version_pairs"] if p["a"] in ids and p["b"] in ids]
        lines += [f"### F{num:03d}. {title}", ""]
        if canons:
            for canonical in canons.values():
                lines.append(f"Канон блога: [{canonical['slug']}]({canonical['url']}).")
        else:
            lines.append("Канона в блоге пока нет; выбор наиболее полной актуальной основы не завершён.")
        lines += ["", "| Источник | Название / ссылка | Решение |", "|---|---|---|"]
        seen_urls = set()
        for key in sorted(ids):
            m = members[key]
            seen_urls.add(m["url"].rstrip("/"))
            lines.append(f"| {key} · {m['source']} | [{m['title'].replace('|', '/')}]({m['url']}) | {labels[effective[key]]} |")
        for article in manifest["articles"]:
            if article["slug"] not in canons:
                continue
            provenance = article.get("source_provenance", {})
            for url in list(provenance.get("urls", [])) + ([provenance["url"]] if provenance.get("url") else []):
                if url.rstrip("/") not in seen_urls:
                    lines.append(f"| provenance блога | [Дополнительная исходная версия]({url}) | Сравнить вместе с остальными; не потерять сайт/Tilda |")
                    seen_urls.add(url.rstrip("/"))
        lines.append("")
        for group in relevant:
            lines.append(f"- Решение / задача ({group['evidence']}): {group['note']}")
        if candidate_pairs:
            lines.append("- Машинные кандидаты на сравнение (не доказанные дубли): " + ", ".join(p['a'] + ' ↔ ' + p['b'] for p in candidate_pairs) + ".")
        for key in ids:
            if key in decisions["special_notes"]:
                lines.append(f"- {key}: {decisions['special_notes'][key]}")
        lines.append("")
    lines += ["## Покрытие и оставшиеся границы", "", "Все 282 записи исходного аудита включены. Также включены источники из supplements и manifest. Telegram-анонсы и старые сообщения хранятся в существующей приватной карте article-channel-links.json; их не публикуем в Git и не редактируем. Свежая полнота Telegraph/Pikabu и наличие Дзен пока не подтверждены. Проверка всех текстов на полноту, фактическую актуальность и отсутствие переписывания — следующий отдельный этап, не результат этой каталогизации.", ""]
    assert {k for ids in grouped.values() for k in ids} == set(members)
    assert sum(len(ids) for ids in grouped.values()) == len(members)
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build()
    target = BASE / "ARTICLE_FAMILIES.md"
    if args.check:
        assert target.read_text(encoding="utf-8") == result, "ARTICLE_FAMILIES.md is stale"
    else:
        target.write_text(result, encoding="utf-8")
        print(target)
