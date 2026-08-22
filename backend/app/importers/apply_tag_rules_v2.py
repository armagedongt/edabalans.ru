"""Apply the owner-approved second pass of LeadTeh tag normalization.

The operation is idempotent and reversible at the source-tag level: legacy tag
assignments are never deleted. By default the command runs as a dry run and rolls
the transaction back. Pass ``--apply`` to commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AttributionEvent, MessengerAccount, Payment, Product, Tag, UserTag


CATALOG = Path(__file__).resolve().parents[1] / "static" / "leadteh_tag_plan.json"
CONFIRMED = {"paid", "confirmed"}

COMPONENTS = {
    "Мастер-класс": "purchase",
    "Рецепты": "purchase",
    "Калории": "purchase",
    "Консультация": "purchase",
    "Тренировки": "purchase",
    "Записи консультаций": "purchase",
}

PURCHASE_SOURCES = {
    "Мастер-класс": {
        "МК + я сама", "Просто Мастер-класс", "Сама 3 недели", "Сама 8 недель",
        "МК «Минимальный»", "МК «Стандартный»", "МК «С консультацией»",
        "МК + обратная связь", "Мастер-класс + Калории", "МК + консультация",
        "МК+Сопровождение", "Всё вместе + консультация", "МК Оплатил",
    },
    "Рецепты": {"МК «Стандартный»", "МК «С консультацией»", "Доступ Рецепты"},
    "Калории": {
        "МК + обратная связь", "Мастер-класс + Калории", "МК + консультация",
        "МК+Сопровождение", "Всё вместе + консультация", "Калории + консультация",
        "Калории + обратная связь", "Только Только Калории", "Калории Оплатил",
        "Доступ Калории", "Оплатил отдельно Только Калории",
    },
    "Консультация": {
        "МК «С консультацией»", "МК + консультация", "МК+Сопровождение",
        "Всё вместе + консультация", "Калории + консультация", "Консультация",
        "Сопровождение", "Оплата сопро. 1 мес.", "Оплатил Разбор Питания",
    },
}

PRODUCT_COMPONENTS = {
    "MASTERCLASS_BASIC": {"Мастер-класс"},
    "MASTERCLASS_RECIPES": {"Мастер-класс", "Рецепты"},
    "MASTERCLASS_CONSULT": {"Мастер-класс", "Рецепты", "Консультация"},
    "RECIPES_ADDON": {"Рецепты"},
    "CALORIES_COURSE": {"Калории"},
    "CONSULTATION": {"Консультация"},
    "COACHING": {"Консультация"},
    "TRAINING_COURSE": {"Тренировки"},
}

CONTENT_MERGES = {
    "Пост - Введение к интенсиву": {"Интенсив - Введение"},
    "Пост - Видео - Приветствие": {"Материал - Видео-приветствие"},
    "Пост - Истории": {"Материал - Истории"},
    "Пост - Новый материал": {"Материал - Новый материал"},
    "Пост - Обо мне": {"Материал - Обо мне"},
    "Пост - Первые посты": {"Материал - Первые посты"},
    "Пост - Подборка постов": {"Материал - Подборка", "Материал - Подборка постов"},
    "Пост - Подборка статей": {"Материал - Подборка статей"},
    "Пост - Что здесь полезного": {"Материал - Что здесь полезного"},
    "Пост - Шортсы - Конец": {"Материал - Шортсы - конец"},
    "Пост - Шортсы - Начало": {"Материал - Шортсы - начало"},
    "Пост - Стрим - Вредная еда": {"Стрим - Вредная еда", "Стрим - Стрим «Вредная» еда"},
    "Пост - Стрим - Вредная еда - Продолжение": {"Стрим - Вредная еда - продолжение"},
    "Пост - Стрим - Калории": {"Стрим - Калории Из стрима"},
    "Пост - Стрим - Тренировки": {"Пост - Стрим Тренировки", "Стрим - Стрим тренировки Из Дня #4"},
    "Пост - Эмоциональный голод": {"Пост - Эмоции", "Пост - Эмоциональный голод"},
    "Пост - Маленькие шаги": {"Пост - Шаги", "Пост - Маленькие шаги"},
    "Пост - Видео - ПП и жир": {"Пост - Жир", "Пост - Видео ПП и жир"},
    "Пост - Цена похудения": {"Цена похудения"},
    "Пост - Скидка решительным": {"Скидка Решительным"},
    "Пост - Скидка 40% на 7 дней": {"Скидка 40% на 7 дней"},
    "Пост - Получил таблицу Diet Quality Score": {"Получил таблицу"},
}

ARCHIVE_FAMILIES = {
    "Материал - Видео", "Пост - Подарок от 12 изменений", "Доступ Клуб 1-й мес",
    "Заявка на консультацию", "НОВАЯ ПРОДАЖА", "Дал доступ",
    "Дал доступ к сахару сам", "МОБ", "23.10.2025 - 27.10.2025", "доступ",
    "Тест_начал", "Тест_закончил",
}

INTENSIVE_COMPLETE = {
    "Закончил фазу Интенсива", "Открыл Интенсив день 4", "Открыт День 4",
    "Сам Открыл День 4",
}

LOTTERY_RECEIVED = {"Лотерея Август 2024", "Лотерея Апрель 2025"}
LOTTERY_OPENED = {
    "Лотерея Август 2024 ОТКРЫЛ", "Лотерея Апрель Открыл", "Заходил в скидку",
    "СКИДКА открыта",
}


def code_for(name: str) -> str:
    value = re.sub(r"[^a-z0-9а-яё]+", "_", name.lower(), flags=re.I).strip("_")[:58]
    return f"rule2_{value}_{hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]}"


class Normalizer:
    def __init__(self, db):
        self.db = db
        self.tags = list(db.scalars(select(Tag)))
        self.by_name = {tag.name: tag for tag in self.tags}
        self.children: dict[object, set[object]] = defaultdict(set)
        for tag in self.tags:
            if tag.merged_into_tag_id:
                self.children[tag.merged_into_tag_id].add(tag.id)
        self.stats = defaultdict(int)

    def family_ids(self, names: set[str] | list[str]) -> set[object]:
        roots = {self.by_name[name].id for name in names if name in self.by_name}
        result = set(roots)
        queue = list(roots)
        while queue:
            for child in self.children.get(queue.pop(), set()):
                if child not in result:
                    result.add(child)
                    queue.append(child)
        return result

    def users_for(self, names: set[str] | list[str]) -> set[object]:
        ids = self.family_ids(names)
        if not ids:
            return set()
        return set(self.db.scalars(select(UserTag.user_id).where(UserTag.tag_id.in_(ids))))

    def ensure(self, name: str, category: str) -> Tag:
        tag = self.by_name.get(name)
        if tag is None:
            tag = Tag(code=code_for(name), name=name, category=category, status="active",
                      audit_action="keep", audit_reason="Каноническое правило владельца")
            self.db.add(tag)
            self.db.flush()
            self.tags.append(tag)
            self.by_name[name] = tag
            self.stats["tags_created"] += 1
        else:
            tag.category = category
            tag.status = "active"
            tag.merged_into_tag_id = None
            tag.archived_at = None
            tag.audit_action = "keep"
            tag.audit_reason = "Каноническое правило владельца"
        return tag

    def assign(self, name: str, category: str, users: set[object]) -> None:
        target = self.ensure(name, category)
        if not users:
            return
        existing = set(self.db.scalars(select(UserTag.user_id).where(
            UserTag.tag_id == target.id, UserTag.user_id.in_(users))))
        for user_id in users - existing:
            self.db.add(UserTag(user_id=user_id, tag_id=target.id, source="tag_rules_v2"))
            self.stats["assignments_created"] += 1

    def merge(self, target_name: str, category: str, source_names: set[str]) -> None:
        target = self.ensure(target_name, category)
        for name in source_names:
            source = self.by_name.get(name)
            if source is None or source.id == target.id:
                continue
            for child in self.tags:
                if child.merged_into_tag_id == source.id:
                    child.merged_into_tag_id = target.id
                    self.children[target.id].add(child.id)
            source.status = "merged"
            source.merged_into_tag_id = target.id
            source.audit_action = "merge"
            source.audit_reason = f"Объединено владельцем в «{target_name}»"
            source.archived_at = None
            self.children[target.id].add(source.id)
            self.stats["tags_merged"] += 1

    def archive(self, names: set[str] | list[str], reason: str) -> None:
        for name in names:
            tag = self.by_name.get(name)
            if tag is None:
                continue
            tag.status = "archived"
            tag.merged_into_tag_id = None
            tag.audit_action = "archive"
            tag.audit_reason = reason
            tag.archived_at = datetime.now(timezone.utc)
            self.stats["tags_archived"] += 1


def apply(*, dry_run: bool = True) -> dict[str, int | bool]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    groups: dict[str, set[str]] = defaultdict(set)
    for item in catalog:
        groups[item["group"]].add(item["current_name"])

    with SessionLocal() as db:
        n = Normalizer(db)

        # Materials: flatten old aliases onto the final canonical name.
        for target, sources in CONTENT_MERGES.items():
            n.merge(target, "content", sources)
        n.archive(ARCHIVE_FAMILIES, "Архивировано по решению владельца")

        # Product component tags are a visible, simple mirror for the owner and bot.
        component_users: dict[str, set[object]] = defaultdict(set)
        for component, sources in PURCHASE_SOURCES.items():
            component_users[component] |= n.users_for(sources)
        payment_rows = db.execute(
            select(Payment.user_id, Product.code)
            .join(Product, Product.id == Payment.product_id)
            .where(Payment.user_id.is_not(None), Payment.payment_status.in_(CONFIRMED))
        ).all()
        for user_id, product_code in payment_rows:
            for component in PRODUCT_COMPONENTS.get(product_code, set()):
                component_users[component].add(user_id)
        for component, users in component_users.items():
            n.assign(component, COMPONENTS[component], users)

        # Every known buyer exits the pre-purchase sales sequence.
        buyers = set(db.scalars(select(Payment.user_id).where(
            Payment.user_id.is_not(None), Payment.payment_status.in_(CONFIRMED))))
        n.assign("Стоп - До покупки мастер-класса", "routing", buyers)
        n.ensure("Стоп - После покупки мастер-класса", "routing")
        n.merge("Стоп - До покупки мастер-класса", "routing", {"Стоп Рассылка"})

        # Old composite purchase/access hints become component tags, not duplicate labels.
        n.archive(groups["tariff"] | groups["purchase"] | {
            "Доступ Калории", "Доступ Рецепты", "Консультация", "Сопровождение",
            "Оплата сопро. 1 мес.", "Оплатил Разбор Питания",
            "Оплатил отдельно Только Калории",
        }, "Преобразовано в канонические компоненты покупки")
        # Reactivate canonical component definitions that shared a legacy name.
        for component, users in component_users.items():
            n.assign(component, COMPONENTS[component], users)
        n.archive({"Доступ Клуб 1-й мес", "Заявка на консультацию", "НОВАЯ ПРОДАЖА",
                   "Дал доступ", "Дал доступ к сахару сам"},
                  "Устаревшая подсказка доступа")

        sugar_users = n.users_for({"Сахар_Оплатил"}) - component_users["Мастер-класс"]
        n.assign("Купил сахар, не купил мастер-класс", "purchase", sugar_users)
        n.archive({"Сахар_Оплатил"}, "Старый продукт; сохранён только исторический сегмент")

        # Refund history remains visible; no particular payment is revoked without a product.
        n.merge("Возврат - Полный", "refund", {"Возврат"})
        n.ensure("Возврат - Частичный", "refund")

        # One positive result for the old intensive, no negative tag.
        n.assign("Старый интенсив - Пройден полностью", "intensive",
                 n.users_for(INTENSIVE_COMPLETE))
        n.archive(groups["intensive"], "Старый технический прогресс интенсива")
        n.ensure("Старый интенсив - Пройден полностью", "intensive")

        # Two lasting lottery facts; opening implies receiving.
        opened = n.users_for(LOTTERY_OPENED)
        received = n.users_for(LOTTERY_RECEIVED) | opened
        n.assign("Получил лотерею", "lottery", received)
        n.assign("Открыл лотерею", "lottery", opened)
        n.archive(LOTTERY_RECEIVED | LOTTERY_OPENED, "Преобразовано в историю лотереи")

        # Subscription tags remain visible. Resolve contradictory legacy state by priority.
        yes = n.users_for({"Подписка ДА"})
        was = n.users_for({"Подписка БЫЛ"}) - yes
        no = n.users_for({"Подписка НЕТ"}) - yes - was
        live_rows = db.execute(select(MessengerAccount.user_id, MessengerAccount.subscription_status)
                               .where(MessengerAccount.platform == "telegram")).all()
        for user_id, status in live_rows:
            normalized = (status or "").lower()
            if normalized in {"member", "administrator", "creator", "subscribed"}:
                yes.add(user_id); was.discard(user_id); no.discard(user_id)
            elif normalized in {"left", "kicked", "blocked", "unsubscribed"}:
                yes.discard(user_id); no.discard(user_id); was.add(user_id)
        n.assign("Подписан", "subscription", yes)
        n.assign("Отписался", "subscription", was)
        n.assign("Не подписан", "subscription", no)
        n.merge("Первое посещение - Уже подписан", "routing", {"Зашел подписанный"})
        n.merge("Подписался после просьбы бота", "routing", {"Сразу подписался"})
        n.archive(groups["subscription"] - {"Зашел подписанный", "Сразу подписался"},
                  "Заменено каноническим состоянием или архивировано как старый цикл")

        # The two-person `стоп` tag was an attribution link, not a mailing stop.
        stop_tag = n.by_name.get("стоп")
        if stop_tag:
            for user_id in n.users_for({"стоп"}):
                exists = db.scalar(select(AttributionEvent.id).where(
                    AttributionEvent.user_id == user_id,
                    AttributionEvent.event_type == "legacy_tag_source",
                    AttributionEvent.source_raw == "Стопор-ссылка",
                ))
                if not exists:
                    db.add(AttributionEvent(user_id=user_id, event_type="legacy_tag_source",
                                            source_raw="Стопор-ссылка"))
                    n.stats["sources_created"] += 1
            n.archive({"стоп"}, "Перенесено в источник «Стопор-ссылка»")

        db.flush()
        result = {**n.stats, "dry_run": dry_run}
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="commit changes")
    args = parser.parse_args()
    print(json.dumps(apply(dry_run=not args.apply), ensure_ascii=False, sort_keys=True))
