from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


LINE = re.compile(
    r"^(?P<index>\d+) (?P<name>.+) filled=(?P<filled>\d+) "
    r"distinct=(?P<distinct>\S+) types=(?P<types>.+)$"
)


def classify(index: int, name: str, filled: int) -> tuple[str, str, str]:
    lower = name.lower()
    if filled == 0:
        return "empty", "archive", "Колонка полностью пустая"
    if index <= 12:
        return "identity", "already_imported", "Основные контакты и данные импорта уже перенесены в CRM"
    if 13 <= index <= 133:
        return "legacy_calculator", "archive", "Промежуточные входы и расчёты старого калькулятора"
    if 134 <= index <= 139:
        return "technical_link", "archive", "Техническая переменная старой выдачи ссылок"
    if 140 <= index <= 146:
        return "legacy_test", "archive", "Результат старого теста; не используется новой системой"
    if lower.startswith("utm_") or lower in {"источник:", "источник: без источника", "первая активность", "yclid", "fbclid", "erid"}:
        return "attribution", "use_structured", "Перенести только в структурированную историю источников"
    if "тариф" in lower or lower in {"купил калории отдельно", "мк_уже_куплен"}:
        return "purchase_hint", "use_for_review", "Подсказка для ручной проверки исторической покупки"
    if "оплат" in lower or "цен" in lower or "скид" in lower:
        return "legacy_sales", "archive", "Промежуточный расчёт старой оплаты или скидки"
    if "рассыл" in lower or "этап" in lower or lower == "msgid":
        return "legacy_funnel", "archive", "Техническое состояние старой рассылки LeadTeh"
    if lower.startswith("вопрос_") or lower in {"ответ_по_стриму", "вопрос подписчика"}:
        return "legacy_questionnaire", "archive", "Ответ старой анкеты; сохранить только в исходном архиве"
    if "таблиц" in lower or "пригласитель" in lower or "номер_ссыл" in lower:
        return "google_or_link", "archive", "Служебная ссылка старой Google/LeadTeh-связки"
    if lower in {"пусто", "текст", "etext", "is_api", "paysupported", "код ответа", "ссылка", "дата"}:
        return "technical", "archive", "Служебная или устаревшая переменная"
    return "legacy_other", "review", "Нужно показать в аудите; в рабочую CRM автоматически не переносить"


def build(source: Path) -> list[dict]:
    result: list[dict] = []
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        match = LINE.match(raw_line)
        if not match:
            continue
        index = int(match.group("index"))
        name = match.group("name")
        filled = int(match.group("filled"))
        category, action, reason = classify(index, name, filled)
        result.append(
            {
                "index": index,
                "name": name,
                "filled": filled,
                "distinct": match.group("distinct"),
                "types": match.group("types"),
                "category": category,
                "action": action,
                "reason": reason,
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    catalog = build(args.source)
    if len(catalog) != 227:
        raise SystemExit(f"Expected 227 variables, got {len(catalog)}")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"variables": len(catalog)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
