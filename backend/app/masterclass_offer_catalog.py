from __future__ import annotations

from typing import TypedDict

from sqlalchemy.orm import Session

from app.product_catalog_service import product_public


class ProductFeature(TypedDict):
    code: str
    name: str
    description: str


class ProductProgramItem(TypedDict):
    title: str
    description: str


class OfferProduct(TypedDict):
    name: str
    description: str
    long_description: str
    resource: str
    standard: int
    status: str
    features: list[ProductFeature]
    presentation_intro: str
    presentation_program: list[ProductProgramItem]


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
            {"code": "recipes", "name": "Рецепты и конструктор блюд", "description": "Готовые сочетания и понятный способ собирать собственные блюда."},
            {"code": "recipes", "name": "Выбор продуктов и готовой еды", "description": "Ориентиры для магазина, доставки и еды вне дома."},
            {"code": "recipes", "name": "Вкус и организация готовки", "description": "Как сделать полезную еду удобной и действительно приятной."},
        ],
        "presentation_intro": "Это не сборник «правильных» рецептов, после которого снова приходится думать, что готовить. На конкретных продуктах и блюдах вы увидите, как собирать тарелку сытно, вкусно и без ощущения, что вы всё себе запретили.",
        "presentation_program": [
            {"title": "от готовых рецептов — к своим решениям", "description": "Разберёте 16 блюд не как список «можно/нельзя», а как понятные сочетания: что делает их сытными, вкусными и подходящими для снижения веса."},
            {"title": "продукты и готовая еда для обычной жизни", "description": "Соберёте ориентиры для дома, магазина, доставки и еды вне дома, чтобы питание не разваливалось в дни без идеального меню и лишнего времени."},
            {"title": "тарелка, которую можно повторять", "description": "Освоите три принципа тарелки и простые способы готовки, чтобы менять привычные блюда постепенно, есть с удовольствием и не возвращаться к запретам."},
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
            {"code": "calories", "name": "Энергетический баланс без лишней математики", "description": "Понятная связь между питанием, расходом энергии и изменением веса."},
            {"code": "calories", "name": "Порции, калории и БЖУ", "description": "Практические примеры без попытки превратить питание в бухгалтерию."},
            {"code": "calories", "name": "Подсчёт как временный инструмент", "description": "Как получить навык и постепенно отказаться от постоянных расчётов."},
        ],
        "presentation_intro": "Калории не должны становиться пожизненной обязанностью и поводом ненавидеть еду. Здесь это временный инструмент: сначала разобраться в своём балансе, затем принимать решения уверенно и без постоянных расчётов.",
        "presentation_program": [
            {"title": "Неделя 1 — учёт без напряжения", "description": "Поймёте, сколько энергии на самом деле даёт ваше обычное питание, без бесконечной бухгалтерии и потерь «на глаз». Это создаёт опору для снижения веса без очередной жёсткой диеты."},
            {"title": "Неделя 2 — личный расход и рабочий дефицит", "description": "Разберётесь, из чего складывается ваш расход энергии и какой дефицит помогает худеть, но оставляет силы на работу, семью, движение и нормальную еду."},
            {"title": "Неделя 3 — выход из постоянного подсчёта", "description": "Переведёте цифры в понятные ориентиры для порций и выбора блюд, чтобы использовать калории как навык, а не зависеть от приложения всю жизнь."},
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
            {"code": "training", "name": "Выбор цели и подходящего уровня", "description": "Стартовая точка с учётом опыта, самочувствия и возможностей."},
            {"code": "training", "name": "Минимальный рабочий объём", "description": "Сколько нагрузки действительно нужно для первых результатов."},
            {"code": "training", "name": "Начало без перегруза", "description": "Как встроить тренировки в жизнь и не бросить после первой недели."},
        ],
        "presentation_intro": "Тренировки не должны начинаться с героизма и заканчиваться через неделю. Материал помогает выбрать посильный старт, встроить движение в жизнь и получать от него заметный результат.",
        "presentation_program": [
            {"title": "спокойный старт с вашей точки", "description": "Выберете посильный вход, если тренировок давно не было или опыта почти нет, чтобы движение поддерживало похудение, а не становилось очередной неподъёмной обязанностью."},
            {"title": "нагрузка, которая даёт отдачу", "description": "Поймёте, какой минимум действительно работает для силы, самочувствия и расхода энергии — без попытки жить в спортзале."},
            {"title": "привычка вместо рывка", "description": "Соберёте понятный ритм и запасные варианты на занятые дни, чтобы не бросать после первой недели и видеть результат в долгую."},
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
            {"code": "recordings", "name": "Реальные ситуации участников", "description": "Примеры, в которых легко узнать собственные сложности."},
            {"code": "recordings", "name": "Разбор причин", "description": "Не только отдельные ошибки, но и логика, которая за ними стоит."},
            {"code": "recordings", "name": "Решения для своей ситуации", "description": "Подходы, которые можно перенести в собственное питание."},
        ],
        "presentation_intro": "Чужой разбор не заменяет личный, но часто помогает быстрее увидеть свою ситуацию со стороны. В записях важны не готовые советы, а ход мысли: почему проблема появилась и за что браться сначала.",
        "presentation_program": [
            {"title": "реальные ситуации вместо идеальных примеров", "description": "Посмотрите разборы дневников и типичных тупиков, в которых легко узнать собственные сложности с режимом, голодом, перееданием или «правильной» едой."},
            {"title": "почему решение работает", "description": "Увидите ход мысли: что проверять сначала, как отличать причину от следствия и почему один общий совет разным людям может не подойти."},
            {"title": "ориентиры для своего следующего шага", "description": "Заберёте не чужие предписания, а вопросы и способы наблюдения, которые помогут двигаться к снижению веса осознанно и без хаотичных экспериментов."},
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
            {"code": "consultation", "name": "Предварительный разбор дневника", "description": "Сергей заранее изучит записи и подготовит основные выводы."},
            {"code": "consultation", "name": "Обсуждение удобным способом", "description": "Звонок или голосовые сообщения — в зависимости от вашей ситуации."},
            {"code": "consultation", "name": "Ответы на личные вопросы", "description": "Рекомендации с учётом именно вашего питания и образа жизни."},
        ],
        "presentation_intro": "Сначала я спокойно разбираю ваш дневник и вопросы, а потом мы обсуждаем выводы удобным способом: звонком, голосовыми или текстом. Цель — не выдать универсальный список запретов, а понять, какие изменения дадут вам самый заметный результат.",
        "presentation_program": [
            {"title": "сначала — ваше питание, а не общий совет", "description": "Я заранее разбираю дневник, привычки, голод и текущую точку в похудении, чтобы не тратить встречу на универсальные рекомендации."},
            {"title": "затем — приоритеты и разговор", "description": "Обсуждаем, какие изменения дадут самый заметный результат именно сейчас и что пока не стоит усложнять. Формат подбираем по ситуации: созвон, голосовые или текст."},
            {"title": "в итоге — рабочий план для жизни", "description": "Получаете ответы на свои вопросы и следующий план шагов, который можно встроить в обычную жизнь, а не только выдержать несколько дней на силе воли."},
        ],
    },
}

DIGITAL_OFFER_PRODUCT_CODES = (
    "recipes",
    "calories",
    "training",
    "recordings",
)

# One module keeps one complete product catalog. The active presentation is a
# reversible instruction for the published site, not a second offers module or
# a second set of product copy. Revert to ``canonical`` when the full catalog
# should be shown again.
ACTIVE_OFFER_PRESENTATION = "site_short_v1"

SITE_SHORT_OFFER_PRESENTATION = {
    "code": "site_short_v1",
    "name": "Временная короткая витрина сайта",
    "digital_product_codes": ("recipes", "calories"),
    "consultation_addon_key": "site_short",
    "standalone_consultation_stages": ("review", "standard"),
}

OFFER_CARD_COPY: dict[str, OfferCardCopy] = {
    "digital_bundle": {
        "title": "Все самостоятельные программы",
        "description": "Все самостоятельные программы, доступные в этом предложении, одним комплектом.",
    },
    "consultation_bundle": {
        "title": "Все самостоятельные программы с консультацией",
        "description": "Все самостоятельные программы и индивидуальная консультация одним комплектом.",
    },
}


OFFER_PRODUCT_LINKS = {
    "recipes": ("recipes", 3900),
    "calories": ("calories", 3900),
    "training": ("training", 3900),
    "recordings": ("recordings", 3900),
    "consultation": ("consultation", 8900),
}


def offer_products(db: Session) -> dict[str, OfferProduct]:
    """Merge editable public catalog copy with fixed offer/runtime connections."""
    result: dict[str, OfferProduct] = {}
    for offer_code, (catalog_code, standard) in OFFER_PRODUCT_LINKS.items():
        public = product_public(db, catalog_code)
        result[offer_code] = {
            "name": public["name"],
            "description": public["description"],
            "long_description": "",
            "resource": public["resource"],
            "standard": standard,
            "status": public["status"],
            "features": OFFER_PRODUCTS[offer_code]["features"],
            "presentation_intro": OFFER_PRODUCTS[offer_code]["presentation_intro"],
            "presentation_program": OFFER_PRODUCTS[offer_code]["presentation_program"],
        }
    return result


def bundle_detail(product_code: str, products: dict[str, OfferProduct] = OFFER_PRODUCTS) -> ProductFeature:
    product = products[product_code]
    return {"code": product_code, "name": product["name"], "description": product["description"]}


def partial_bundle_copy(
    product_codes: list[str],
    products: dict[str, OfferProduct] = OFFER_PRODUCTS,
    *,
    includes_consultation: bool = False,
) -> OfferCardCopy:
    """Keep the temporary public bundle names until an owner-approved alternative exists."""
    return {
        "title": OFFER_CARD_COPY[
            "consultation_bundle" if includes_consultation else "digital_bundle"
        ]["title"],
        "description": (
            "Все самостоятельные программы и индивидуальная консультация одним комплектом."
            if includes_consultation
            else "Все самостоятельные программы одним комплектом."
        ),
    }
