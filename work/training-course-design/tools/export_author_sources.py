"""Export a curated, verbatim training-course source set from the private author catalog."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


DB = Path(r"C:\private\edabalans-content-authoring\author-catalog.sqlite")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sources" / "author-posts"


SELECTIONS: dict[str, str] = {
    "telegram:1878297271:663": "Главный тренировочный стрим: таймкоды и публичный контекст",
    "telegram:1878297271:665": "Авторская позиция: нагрузка зависит от цели и подготовки",
    "telegram:1878297271:673": "Мост: тренировки, аппетит и питание",
    "telegram:1878297271:232": "План как условие результата",
    "telegram:1878297271:228": "Нагрузка и риск перегнуть палку",
    "telegram:1878297271:210": "Гибкость и растяжка",
    "telegram:1878297271:208": "Разминка и заминка",
    "telegram:1878297271:199": "Почему люди начинают и бросают",
    "telegram:1878297271:200": "Практическая подготовка старта",
    "telegram:1878297271:115": "Домашние тренировки: правила организации",
    "telegram:1878297271:96": "Выбор между бегом и залом через задачу",
    "telegram:1878297271:145": "Восстановление и тренировочная динамика",
    "telegram:1878297271:149": "Алкоголь и тренировки",
    "telegram:1878297271:226": "Мост: бег, шаги и калории",
    "telegram:1878297271:82": "История и смысл выносливости",
    "telegram:1878297271:29": "Время тренировки и соблюдение",
    "telegram:1878297271:262": "Авторская самопрезентация и интонация",
    "telegram:1878297271:572": "Личный тренировочный опыт и доказательность",
    "telegram:1878297271:645": "Личный спортивный контекст перед стримом",
    "telegram:1878297271:656": "Личный спортивный контекст",
    "telegram:1878297271:657": "Личный спортивный контекст",
    "telegram:1878297271:658": "Личный спортивный контекст",
    "pikabu:10840474": "Как выбрать тренировки для обычного человека",
    "pikabu:10779442": "Челлендж-инструкция: начать и не бросить",
    "pikabu:10756513": "Как продолжить после начала",
    "pikabu:10425659": "Домашние тренировки: полная статья",
    "pikabu:10778250": "Бег или зал: полная статья",
    "pikabu:10797468": "Интенсивность и жиросжигающая зона",
    "pikabu:10379941": "Велосипед: маршрут от нуля к длинной дистанции",
    "pikabu:10715268": "Восстановление между тренировками",
    "pikabu:10797523": "Мотивация к тренировкам",
    "pikabu:10757775": "Формирование привычек",
    "pikabu:13436070": "Мост: потеря мышц при похудении",
    "pikabu:14102926": "Мост: ходьба и похудение",
    "pikabu:13785403": "Калорийный контекст: ошибки старта",
    "pikabu:13894066": "Калорийный контекст: начать считать",
    "pikabu:13277231": "Калорийный контекст: сроки похудения",
    "pikabu:13741138": "Калорийный контекст: план снижения веса",
}


def safe_yaml(value: str | None) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def output_path(catalog_id: str, source: str) -> Path:
    number = catalog_id.rsplit(":", 1)[-1]
    if source == "telegram_channel":
        filename = f"{int(number):04d}.md"
        folder = "telegram"
    else:
        filename = f"{re.sub(r'[^0-9A-Za-z_-]+', '-', number)}.md"
        folder = source
    return OUTPUT / folder / filename


def main() -> None:
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in SELECTIONS)
    rows = connection.execute(
        f"""
        SELECT catalog_id, source, source_url, published_at, headline, text_plain,
               context_json, media_json, signals_json, roles_json, reuse_catalog
        FROM content_cards
        WHERE catalog_id IN ({placeholders})
        """,
        tuple(SELECTIONS),
    ).fetchall()
    found = {row["catalog_id"] for row in rows}
    missing = sorted(set(SELECTIONS) - found)
    if missing:
        raise RuntimeError(f"Missing catalog ids: {missing}")

    catalog_rows: list[tuple[str, str, str, str, str]] = []
    for row in sorted(rows, key=lambda item: (item["source"], item["published_at"] or "", item["catalog_id"])):
        target = output_path(row["catalog_id"], row["source"])
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata = (
            "---\n"
            f"catalog_id: {safe_yaml(row['catalog_id'])}\n"
            f"source: {safe_yaml(row['source'])}\n"
            f"source_url: {safe_yaml(row['source_url'])}\n"
            f"published_at: {safe_yaml(row['published_at'])}\n"
            f"headline: {safe_yaml(row['headline'])}\n"
            f"course_role: {safe_yaml(SELECTIONS[row['catalog_id']])}\n"
            f"reuse_catalog: {safe_yaml(row['reuse_catalog'])}\n"
            "verbatim_source: true\n"
            "---\n\n"
        )
        body = row["text_plain"] or ""
        target.write_text(metadata + body.rstrip() + "\n", encoding="utf-8")
        relative = target.relative_to(OUTPUT).as_posix()
        catalog_rows.append(
            (
                row["source"],
                row["published_at"] or "",
                row["headline"] or "Без заголовка",
                SELECTIONS[row["catalog_id"]],
                relative,
            )
        )

    catalog = [
        "# Выгруженные авторские публикации",
        "",
        "Полные тексты сохранены дословно из приватного авторского каталога. Это источники и фактура, а не автоматически актуальные правила курса.",
        "",
        "| Источник | Дата | Материал | Роль в разработке | Локальная копия |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source, published_at, headline, role, relative in catalog_rows:
        catalog.append(f"| {source} | {published_at[:10]} | {headline.replace('|', ' / ')} | {role} | [{relative}]({relative}) |")
    catalog.append("")
    (OUTPUT / "catalog.md").write_text("\n".join(catalog), encoding="utf-8")
    print(json.dumps({"exported": len(rows), "catalog": str(OUTPUT / 'catalog.md')}, ensure_ascii=False))


if __name__ == "__main__":
    main()
