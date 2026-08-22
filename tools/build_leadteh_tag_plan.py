from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sqlite3
from pathlib import Path


CONTENT_EXACT = {
    "Пристегните ремни": "Интенсив - Введение",
    "Отправил стрим": "Стрим - Вредная еда",
    "Отправил стрим 2": "Стрим - Вредная еда - продолжение",
    "отзыв Анна": "Пост - Отзыв Анна",
    "Можно Эмоции все. (до 13 сент)": "Пост - Эмоции",
    "Отзыв Любовь Брокколи": "Пост - Отзыв Любовь Брокколи",
    "12 изменений": "Пост - 12 изменений",
    "Словарь": "Пост - Словарь",
    "Оземпик": "Пост - Оземпик",
    "Скорость похудения": "Пост - Скорость похудения",
    "Ошибки в похудении": "Пост - Ошибки в похудении",
    "Главный принцип 👍": "Пост - Главный принцип похудения",
    "Где справедливость": "Пост - Где справедливость",
    "Сначала Шаги": "Пост - Шаги",
}

SOURCE_EXACT = {
    "Шевяков", "Шевяков 27.09.2024", "Шевяков 25.01.2025", "Выражения",
    "Выражения 04.09.2024", "Мышь", "Соковых", "Соковых 01.02.2025",
    "Помылёва", "Еда Вино и Свечи", "Еда Вино и Свечи 22.01.2025",
    "Агрономы", "Квартирохозяйка", "Людочка ПП", "Шопоголик",
    "Старые посевы", "ЯД Реклама интенсива ШАГИ", "ВК Реклама Япония",
    "ВК Реклама 18 навыков", "ЯД посевы в ТГ",
    "Молянов", "Здоровье и Красота Роман", "Японцы", "Фентези", "ПК", "Макс", "сайт",
}

TARIFF_EXACT = {
    "Сама 8 недель", "Сама 3 недели", "МК доступ 2 мес", "Калории Доступ 2 мес",
    "Просто Мастер-класс", "МК + я сама", "МК+Сопровождение",
    "МК + консультация", "МК + обратная связь", "Мастер-класс + Калории",
    "Калории + обратная связь", "Калории + консультация", "Только Только Калории",
    "МК «Стандартный»", "МК «С консультацией»", "МК «Минимальный»",
}

TRUE_PURCHASE_TAGS = {"МК Оплатил", "Калории Оплатил"}

OBSOLETE_EXACT = {
    "Сахар_Оплатил", "Доп_оплата", "Доп_оплата1", "Оплата сопро. 1 мес.",
    "Оплатил Разбор Питания", "Не оплатил хватит сладкого", "Скидка Решительным",
    "Заходил в скидку", "СКИДКА открыта", "Скидка 40% на 7 дней", "Пусто",
    "пусто", "fffffff", "111effrfrfrfr", "сбой", "стоп", "Прокладка",
}

CONTENT_MORE = {
    "Подборка из второго дня": "Пост - Подборка из второго дня",
    "НЕ с похудения": "Пост - Не с похудения",
    "Блиц": "Пост - Блиц",
    "жир": "Пост - Жир",
    "Подарок от 12 изм": "Пост - Подарок от 12 изменений",
    "Конспект голосового": "Пост - Конспект голосового",
    "Видел видеоПриветствие": "Материал - Видео-приветствие",
    "Видел Истории": "Материал - Истории",
    "Открыл Истории": "Материал - Истории",
    "Смотрел Новый": "Материал - Новый материал",
    "Смотрел подборку постов": "Материал - Подборка постов",
    "Открыл подборку постов": "Материал - Подборка постов",
    "Смотрел Посты": "Материал - Подборка постов",
    "Смотрел Статьи": "Материал - Подборка статей",
    "Открыл Подарок от 12 изм": "Пост - Подарок от 12 изменений",
    "Смотрел Видео": "Материал - Видео",
    "Смотрел Шортсы Начало": "Материал - Шортсы - начало",
    "Смотрел Шортсы Конец": "Материал - Шортсы - конец",
    "Приветствие - Первые посты": "Материал - Первые посты",
    "Приветствие - Что здесь полезного": "Материал - Что здесь полезного",
    "Приветствие - Обо мне": "Материал - Обо мне",
}

FUNNEL_MORE = {
    "Контент-маркетинг Новые 2025", "Ушел в закреп", "Есть закреп?", "Есть ссылка",
    "Попал в таблицу", "Первое посещение Новое", "stop_golod", "первый круг",
    "В канал", "после 9 сентября", "Хочу Историю", "101 вопрос Хочу запись",
    "МК Номер телефона", "В МК из Четвертого дня", "В МК из второго дня",
    "Написал в лс продажа", "писал в личку", "Уже был до рекламы",
    "Заходил в подборку из презентации", "Новый закреп БОТА", "Новые Консультации",
    "Не закреп 25", "Не закреп 48", "ХОЧУ новый МК", "Картинка ссылка", "Маша блок",
    "Ирина Ошибка", "нет логина", "нет отзыва фишер", "Начал Хватит Сладкого",
    "хватит сладкого ТЕСТ да", "хватит сладкого ТЕСТ нет", "Стрим ВОПРОСЫ Из Дня #4",
    "Стрим тренировки НАЖАД Меню", "Нажимал купить Калории", "Сначала План",
}

ACCESS_HINTS = {
    "НОВАЯ ПРОДАЖА", "Дал доступ", "Доступ Калории", "Доступ Рецепты",
    "Доступ Клуб 1-й мес", "Дал доступ к сахару сам", "Сопровождение",
    "Консультация", "Возврат", "Заявка на консультацию",
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", " ", value.lower()).strip()


def post_name(name: str) -> str:
    title = re.sub(r"^посты?\s*[:\-]?\s*", "", name, flags=re.IGNORECASE).strip()
    return f"Пост - {title[:1].upper() + title[1:] if title else name}"


def canonical_source(name: str) -> str:
    lower = name.lower()
    if "пикабу" in lower:
        return "Пикабу реклама" if "реклам" in lower else "Пикабу"
    if "без источника" in lower:
        return "Без источника"
    if "директ" in lower or lower.startswith("яд "):
        return "Яндекс Директ"
    if "моего канала" in lower or "канала нового" in lower:
        return "Свой Telegram-канал"
    if "ютуб" in lower:
        return "YouTube"
    if "вк" in lower:
        return "ВКонтакте реклама"
    if "посев" in lower or name in SOURCE_EXACT:
        return "Посевы Telegram"
    if "telegraph" in lower:
        return "Telegraph"
    return name


def classify(name: str, current_category: str) -> dict[str, str | None]:
    lower = name.lower()
    if name == "Первое посещение":
        return {"group": "routing", "action": "keep", "proposed_name": name,
                "reason": "Используется для отличия первого входа в главный сценарий"}
    if name in TRUE_PURCHASE_TAGS:
        return {"group": "purchase", "action": "convert_payment", "proposed_name": name,
                "reason": "Надёжный исторический признак подтверждённой покупки"}
    if name in CONTENT_EXACT:
        return {"group": "content", "action": "rename", "proposed_name": CONTENT_EXACT[name],
                "reason": "Материал подтверждён владельцем проекта"}
    if name in CONTENT_MORE:
        return {"group": "content", "action": "rename", "proposed_name": CONTENT_MORE[name],
                "reason": "Историческая отметка о просмотренном материале"}
    if name in FUNNEL_MORE:
        return {"group": "funnel", "action": "archive", "proposed_name": name,
                "reason": "Промежуточное действие старого сценария LeadTeh"}
    if name in ACCESS_HINTS:
        return {"group": "access_hint", "action": "use_for_review", "proposed_name": name,
                "reason": "Подсказка для ручной проверки старых покупок и доступов"}
    if name in SOURCE_EXACT or current_category == "source":
        return {"group": "source", "action": "convert_source", "proposed_name": canonical_source(name),
                "reason": "Перенести в источник клиента и убрать из активных тегов"}
    if name in {"Нажал выбор тарифа", "Заходил в повышение тарифа"}:
        return {"group": "funnel", "action": "archive", "proposed_name": name,
                "reason": "Действие в старом выборе тарифа, а не сам тариф"}
    if name in TARIFF_EXACT or re.search(r"(^|\s)(тариф|доступ \d+ мес)", lower):
        return {"group": "tariff", "action": "use_for_review", "proposed_name": name,
                "reason": "Подсказка о старом тарифе, не автоматическая выдача доступа"}
    if name in OBSOLETE_EXACT:
        return {"group": "obsolete", "action": "archive", "proposed_name": name,
                "reason": "Устаревшая техническая или коммерческая механика"}
    if current_category == "subscription":
        return {"group": "subscription", "action": "convert_state", "proposed_name": name,
                "reason": "Старые противоречивые теги заменить текущим статусом канала"}
    if current_category == "mailing_funnel":
        return {"group": "funnel", "action": "archive", "proposed_name": name,
                "reason": "Технический прогресс старой рассылки LeadTeh"}
    if current_category == "lottery" or "лотере" in lower:
        return {"group": "obsolete", "action": "archive", "proposed_name": name,
                "reason": "Завершённая и больше не используемая механика"}
    if current_category == "technical":
        return {"group": "technical", "action": "archive", "proposed_name": name,
                "reason": "Служебный тег старого LeadTeh"}
    if current_category == "purchase_signal":
        return {"group": "obsolete", "action": "archive", "proposed_name": name,
                "reason": "Старый шаг продажи; фактом покупки не является"}
    if "интенсив" in lower or re.search(r"(^|\s)(открыт|открыл|сам открыл) день", lower):
        return {"group": "intensive", "action": "archive", "proposed_name": name,
                "reason": "Прогресс старого интенсива; новый бот начнёт новую историю"}
    if re.search(r"(скидк|40%|повышени[ея] тариф|ссылк[уа] на оплат)", lower):
        return {"group": "obsolete", "action": "archive", "proposed_name": name,
                "reason": "Устаревшая скидка или промежуточный шаг оплаты"}
    if re.search(r"(не нажал|нажал далее|нажал меню|в главное меню|погнали)", lower):
        return {"group": "funnel", "action": "archive", "proposed_name": name,
                "reason": "Промежуточное действие старого сценария"}
    if re.search(r"(смотрел калории|хватит сладкого|8 марта нажал)", lower):
        return {"group": "obsolete", "action": "archive", "proposed_name": name,
                "reason": "Устаревший калькулятор, мини-курс или акция"}
    if name in {"День 2", "Сразу в день 3"}:
        return {"group": "intensive", "action": "archive", "proposed_name": name,
                "reason": "Прогресс старого интенсива"}
    if name in {"Сам Открыл План", "Нажал КТО Я", "Нажал купить МК", "Открыл новые цены МК",
                "нажал перейти в канал", "Нажал Готовый стрим И МК", "Нажал Готовый стрим кто я",
                "Нажал Готовый стрим", "Нажал Готовый стрим Ответил", "Нажал главное меню",
                "Нажал личные посты", "Приветствие не открыли"}:
        return {"group": "funnel", "action": "archive", "proposed_name": name,
                "reason": "Промежуточное действие старого сценария"}
    if name in {"Всё вместе + консультация"}:
        return {"group": "tariff", "action": "use_for_review", "proposed_name": name,
                "reason": "Подсказка о старом тарифе"}
    if name in {"Понравился Пост: Полуфабрикаты", "НЕ Понравился Пост: Полуфабрикаты", "Лайк подборка"}:
        return {"group": "content", "action": "rename", "proposed_name": "Пост - Полуфабрикаты" if "Полуфабрикаты" in name else "Материал - Подборка",
                "reason": "Действие подтверждает просмотр материала; реакцию отдельно не сохраняем"}
    if re.match(r"^посты?\b", lower):
        return {"group": "content", "action": "rename", "proposed_name": post_name(name),
                "reason": "Историческая отметка о просмотренном материале"}
    if "отзыв" in lower and not lower.startswith("нет "):
        return {"group": "content", "action": "rename", "proposed_name": f"Пост - {name}",
                "reason": "Отзыв использовался как самостоятельный материал"}
    if "стрим" in lower and not re.search(r"(нажал|меню|вопросы из)", lower):
        title = re.sub(r"^(отправил|смотрел|открыл)\s+", "", name, flags=re.IGNORECASE)
        return {"group": "content", "action": "rename", "proposed_name": f"Стрим - {title}",
                "reason": "Историческая отметка о просмотренном стриме"}
    if current_category == "content_action":
        return {"group": "content_review", "action": "review", "proposed_name": name,
                "reason": "Похоже на контент, но требуется отличить материал от шага сценария"}
    return {"group": "review", "action": "review", "proposed_name": name,
            "reason": "Смысл нельзя надёжно определить только по названию"}


def load_materials(path: Path) -> list[dict]:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    rows = [dict(row) for row in db.execute(
        "SELECT id,scenario_name,title,plain_text FROM archive_content_items ORDER BY scenario_name,id"
    )]
    db.close()
    return rows


def material_matches(name: str, proposed_name: str, materials: list[dict]) -> list[dict]:
    query = normalize(re.sub(r"^(пост|стрим|интенсив)\s*-\s*", "", proposed_name, flags=re.I))
    if not query:
        return []
    scored: list[tuple[float, dict]] = []
    for item in materials:
        title = normalize(item["title"] or "")
        scenario = normalize(item["scenario_name"] or "")
        text = normalize((item["plain_text"] or "")[:1000])
        score = max(
            difflib.SequenceMatcher(None, query, title).ratio() if title else 0,
            difflib.SequenceMatcher(None, query, scenario).ratio() * 0.85 if scenario else 0,
            0.88 if len(query) >= 5 and query in text else 0,
        )
        if score >= 0.58:
            scored.append((score, item))
    result = []
    seen: set[tuple[str, str]] = set()
    for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True):
        key = (item["title"] or "", item["scenario_name"] or "")
        if key in seen:
            continue
        seen.add(key)
        result.append({"id": item["id"], "title": item["title"],
                       "scenario": item["scenario_name"], "score": round(score, 2)})
        if len(result) == 3:
            break
    return result


def build(tags_path: Path, catalog_path: Path) -> list[dict]:
    materials = load_materials(catalog_path)
    with tags_path.open(encoding="utf-8-sig", newline="") as stream:
        tags = list(csv.DictReader(stream))
    plan = []
    for tag in tags:
        proposal = classify(tag["name"], tag["category"])
        matches = material_matches(tag["name"], str(proposal["proposed_name"]), materials) if proposal["group"] in {"content", "content_review"} else []
        plan.append({
            "id": tag["id"], "code": tag["code"], "current_name": tag["name"],
            "current_category": tag["category"], "users": int(tag["users"]),
            **proposal, "material_matches": matches,
        })
    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    plan = build(args.tags, args.catalog)
    if len(plan) != 397:
        raise SystemExit(f"Expected 397 tags, got {len(plan)}")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary: dict[str, int] = {}
    for item in plan:
        summary[str(item["group"])] = summary.get(str(item["group"]), 0) + 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
