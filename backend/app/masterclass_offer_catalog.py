from __future__ import annotations

from typing import TypedDict


class ProductFeature(TypedDict):
    name: str
    description: str


class OfferProduct(TypedDict):
    name: str
    description: str
    long_description: str
    resource: str
    standard: int
    status: str
    features: list[ProductFeature]


class OfferCardCopy(TypedDict):
    title: str
    description: str


# Runtime owner of every product field used by single offer cards and bundle rows.
# Pricing stages remain owned by PostgreSQL; this catalog owns product identity/copy.
OFFER_PRODUCTS: dict[str, OfferProduct] = {
    "recipes": {
        "name": "Система рецептов",
        "description": "Как научиться собирать здоровые тарелки быстро, просто и вкусно — от выбора продуктов до собственных блюд.",
        "long_description": "",
        "resource": "ACCESS_RECIPES",
        "standard": 3900,
        "status": "active",
        "features": [
            {"name": "Рецепты и конструктор блюд", "description": "Готовые сочетания и понятный способ собирать собственные блюда."},
            {"name": "Выбор продуктов и готовой еды", "description": "Ориентиры для магазина, доставки и еды вне дома."},
            {"name": "Вкус и организация готовки", "description": "Как сделать полезную еду удобной и действительно приятной."},
        ],
    },
    "calories": {
        "name": "Мини-курс «Калорийный»",
        "description": "Как научиться считать калории так, чтобы вам больше никогда не пришлось считать калории.",
        "long_description": "",
        "resource": "ACCESS_CALORIES",
        "standard": 3900,
        "status": "active",
        "features": [
            {"name": "Энергетический баланс без лишней математики", "description": "Понятная связь между питанием, расходом энергии и изменением веса."},
            {"name": "Порции, калории и БЖУ", "description": "Практические примеры без попытки превратить питание в бухгалтерию."},
            {"name": "Подсчёт как временный инструмент", "description": "Как получить навык и постепенно отказаться от постоянных расчётов."},
        ],
    },
    "training": {
        "name": "Мини-курс «С дивана до тренировок»",
        "description": "Как встать с дивана и начать получать от тренировок и удовольствие, и результат.",
        "long_description": "",
        "resource": "ACCESS_STRENGTH",
        "standard": 3900,
        "status": "planned",
        "features": [
            {"name": "Выбор цели и подходящего уровня", "description": "Стартовая точка с учётом опыта, самочувствия и возможностей."},
            {"name": "Минимальный рабочий объём", "description": "Сколько нагрузки действительно нужно для первых результатов."},
            {"name": "Начало без перегруза", "description": "Как встроить тренировки в жизнь и не бросить после первой недели."},
        ],
    },
    "recordings": {
        "name": "Записи консультаций других участников",
        "description": "Практические записи разборов питания и решений других участников.",
        "long_description": "",
        "resource": "ACCESS_CONSULTATION_RECORDINGS",
        "standard": 3900,
        "status": "planned",
        "features": [
            {"name": "Реальные ситуации участников", "description": "Примеры, в которых легко узнать собственные сложности."},
            {"name": "Разбор причин", "description": "Не только отдельные ошибки, но и логика, которая за ними стоит."},
            {"name": "Решения для своей ситуации", "description": "Подходы, которые можно перенести в собственное питание."},
        ],
    },
    "consultation": {
        "name": "Индивидуальная консультация",
        "description": "Сначала разбор дневника, затем обсуждение выводов звонком или голосовыми.",
        "long_description": "",
        "resource": "ACCESS_CONSULTATION",
        "standard": 8900,
        "status": "active",
        "features": [
            {"name": "Предварительный разбор дневника", "description": "Сергей заранее изучит записи и подготовит основные выводы."},
            {"name": "Обсуждение удобным способом", "description": "Звонок или голосовые сообщения — в зависимости от вашей ситуации."},
            {"name": "Ответы на личные вопросы", "description": "Рекомендации с учётом именно вашего питания и образа жизни."},
        ],
    },
}

DIGITAL_OFFER_PRODUCT_CODES = (
    "recipes",
    "calories",
    "training",
    "recordings",
)

OFFER_CARD_COPY: dict[str, OfferCardCopy] = {
    "digital_bundle": {
        "title": "Вообще всё, что вам может понадобиться",
        "description": "Все недостающие самостоятельные материалы одним комплектом.",
    },
    "consultation_bundle": {
        "title": "Максимальный комплект с консультацией",
        "description": "Индивидуальная консультация и все недостающие самостоятельные материалы одним комплектом.",
    },
}


def bundle_detail(product_code: str) -> ProductFeature:
    product = OFFER_PRODUCTS[product_code]
    return {"name": product["name"], "description": product["description"]}
