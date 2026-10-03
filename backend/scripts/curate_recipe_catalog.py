"""Build a reversible recipe-product catalog from the raw Calorizator SQLite file.

The raw database is never modified.  Every source row is copied to an immutable
JSONL snapshot and receives one curation-log decision.  Canonical unbranded
products are averaged from compatible source rows and marked with `` *``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

REQUIRED = ("protein", "fat", "carbohydrate", "kcal")

EXCLUDED_CATEGORIES = {
    "Burger King",
    "KFC",
    "McDonalds (Вкусно и точка)",
    "Детское питание",
    "Кондитерские изделия",
    "Напитки алкогольные",
    "Первые блюда",
    "Салаты",
    "Снэки",
    "Спортивное и дополнительное питание",
    "Торты",
    "Японская кухня",
}

READY_PREFIXES = {
    "азу",
    "баскет",
    "бефстроганов",
    "бифштекс",
    "блины",
    "блюдо",
    "борщ",
    "бургер",
    "вареники",
    "вафли",
    "винегрет",
    "гедза",
    "голубцы",
    "гуляш",
    "дамплинги",
    "драники",
    "зразы",
    "запеканка",
    "котлета",
    "котлеты",
    "лазанья",
    "наггетсы",
    "окрошка",
    "макзавтрак",
    "омлет",
    "оладушки",
    "пельмени",
    "пицца",
    "плов",
    "рагу",
    "рассольник",
    "ризотто",
    "ролл",
    "салат",
    "салаты",
    "самса",
    "солянка",
    "сэндвич",
    "суп",
    "суши",
    "сырник",
    "торт",
    "тефтели",
    "фрикадельки",
    "чебупели",
    "чебупицца",
    "хинкали",
    "харчо",
    "щи",
}

READY_NAME_FRAGMENTS = {
    "бургер кинг",
    "вкусно и точка",
    "готово!",
    "kfc",
    "mcdonald",
    "с картофельным пюре",
    "с рисом и овощами",
}

READY_STARTS = {
    "зразы ",
    "картофельное пюре",
    "куриные зразы ",
    "манная каша ",
    "овощное рагу ",
    "овсяная каша ",
    "рисовая каша ",
    "тефтели ",
}

ALCOHOL_PREFIXES = {
    "абсент",
    "бренди",
    "бурбон",
    "вермут",
    "вино",
    "виски",
    "водка",
    "глинтвейн",
    "грог",
    "джин",
    "коньяк",
    "ликер",
    "ликёр",
    "настойка",
    "пиво",
    "ром",
    "текила",
}

COMPOSITE_PHRASES = {
    "в маринаде",
    "из топленого молока",
    "из топлёного молока",
    "на молоке",
    "с базиликом",
    "с грибами",
    "с хлопьями",
    "с печеньем",
    "с мюсли",
    "с морковью",
    "с кокосом",
    "с кусочками",
    "с клетчаткой",
    "с злаками",
    "с семенами",
    "с трюфелем",
    "с укропом",
    "с чесноком",
    "со вкусом",
    "быстрый завтрак",
}

SWEET_DAIRY_WORDS = {
    "абрикос",
    "банан",
    "ванил",
    "вишн",
    "голубик",
    "груш",
    "земляник",
    "изюм",
    "инжир",
    "клубник",
    "клетчат",
    "манго",
    "малин",
    "мюсли",
    "орех",
    "персик",
    "сладк",
    "фрукт",
    "черник",
    "чернослив",
    "шоколад",
    "яблок",
    "ягод",
}

BABY_BRANDS = {
    "агуша",
    "бабушкино лукошко",
    "гербер",
    "малютка",
    "спеленок",
    "спелёнок",
    "тема",
    "тёма",
    "фрутоняня",
    "хайнц",
    "heinz",
}

SPECIAL_PRODUCT_PREFIXES = {
    "биойогурт",
    "биотворог",
    "творожная масса",
    "творожок",
    "сырок",
}

BRAND_HINTS = {
    "агуша",
    "активиа",
    "беллакт",
    "бондюэль",
    "вкусвилл",
    "данон",
    "домик в деревне",
    "индилайт",
    "макфа",
    "мистраль",
    "простоквашино",
    "петелинка",
    "петруха",
    "растишка",
    "савушкин",
    "слобода",
    "самсон",
    "тема",
    "фрутоняня",
    "хайнц",
    "чудо",
    "ясно солнышко",
}

WHOLE_CATEGORIES = {
    "Грибы",
    "Крупы и каши",
    "Масла и жиры",
    "Молочные продукты",
    "Мука и мучные изделия",
    "Мясные продукты",
    "Овощи и зелень",
    "Орехи и сухофрукты",
    "Рыба и морепродукты",
    "Сыры и творог",
    "Фрукты",
    "Ягоды",
    "Яйца",
}

WHOLE_FIRST_WORDS = {
    "абрикос",
    "авокадо",
    "ананас",
    "апельсин",
    "арахис",
    "арбуз",
    "баклажан",
    "банан",
    "баранина",
    "брокколи",
    "булгур",
    "виноград",
    "вишня",
    "говядина",
    "горох",
    "горошек",
    "гречка",
    "груша",
    "индейка",
    "кабачок",
    "капуста",
    "картофель",
    "клубника",
    "клюква",
    "кукуруза",
    "курица",
    "лен",
    "манго",
    "макароны",
    "масло",
    "миндаль",
    "морковь",
    "мука",
    "нут",
    "овсянка",
    "огурец",
    "перец",
    "перловка",
    "персик",
    "помидор",
    "рис",
    "свекла",
    "свинина",
    "сельдерей",
    "смородина",
    "соль",
    "соя",
    "сыр",
    "творог",
    "томат",
    "тунец",
    "тыква",
    "фасоль",
    "финики",
    "хлопья",
    "чечевица",
    "яблоко",
    "яйцо",
}

BROAD_NAMES = {
    "грибы",
    "крупа",
    "мясо",
    "овощи",
    "орехи",
    "рыба",
    "сыр",
    "фрукты",
    "ягоды",
}

DAIRY_FAMILIES = {
    "ацидофилин",
    "варенец",
    "йогурт",
    "кефир",
    "молоко",
    "пахта",
    "простокваша",
    "ряженка",
    "сливки",
    "сметана",
    "творог",
}

GENERIC_DROP_WORDS = {
    "безлактозный",
    "гост",
    "классик",
    "классический",
    "натуральная",
    "натуральное",
    "натуральный",
    "отборный",
    "традиционная",
    "традиционное",
    "традиционный",
    "ультрапастеризованное",
    "ультрапастеризованный",
}

STATE_WORDS = {
    "без кожи",
    "вареная",
    "вареное",
    "вареный",
    "варёная",
    "варёное",
    "варёный",
    "жареная",
    "жареное",
    "жареный",
    "замороженная",
    "замороженное",
    "замороженный",
    "консервированная",
    "консервированное",
    "консервированный",
    "копченая",
    "копченое",
    "копченый",
    "маринованная",
    "маринованное",
    "маринованный",
    "на пару",
    "отварная",
    "отварное",
    "отварной",
    "свежая",
    "свежее",
    "свежий",
    "соленая",
    "соленое",
    "соленый",
    "солёная",
    "солёное",
    "солёный",
    "сухая",
    "сухое",
    "сухой",
    "тушеная",
    "тушеное",
    "тушеный",
}

FAT_STANDARDS = {
    "творог": (0.0, 1.0, 2.0, 5.0, 9.0, 12.0, 18.0),
    "молоко": (0.0, 1.0, 1.5, 2.5, 3.2, 4.0),
    "кефир": (0.0, 1.0, 2.5, 3.2),
    "йогурт": (0.0, 1.0, 1.5, 2.0, 3.2, 5.0, 10.0),
    "сметана": (10.0, 15.0, 20.0, 25.0, 30.0),
    "сливки": (10.0, 20.0, 33.0, 35.0),
    "ряженка": (1.0, 2.5, 3.2, 4.0, 6.0),
}

PERCENT_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*%")
WORD_RE = re.compile(r"[0-9a-zа-я%]+", re.IGNORECASE)


@dataclass(frozen=True)
class Product:
    source_url: str
    name: str
    category: str | None
    protein: float
    fat: float
    carbohydrate: float
    kcal: float


def normalized(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value)
        .casefold()
        .replace("ё", "е")
        .replace("’", "'")
        .split()
    )


def words(value: str) -> list[str]:
    return WORD_RE.findall(normalized(value))


def read_products(path: Path) -> list[Product]:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    nutrients: dict[str, dict[str, float]] = defaultdict(dict)
    for row in connection.execute(
        "SELECT source_url, field_code, value_number FROM product_nutrients"
    ):
        if row["field_code"] in REQUIRED and row["value_number"] is not None:
            nutrients[row["source_url"]][row["field_code"]] = float(row["value_number"])
    result: list[Product] = []
    for row in connection.execute(
        "SELECT source_url, name, category FROM products ORDER BY source_url"
    ):
        values = nutrients[row["source_url"]]
        if set(REQUIRED) - values.keys():
            continue
        result.append(
            Product(
                source_url=row["source_url"],
                name=" ".join(row["name"].split()),
                category=row["category"],
                protein=values["protein"],
                fat=values["fat"],
                carbohydrate=values["carbohydrate"],
                kcal=values["kcal"],
            )
        )
    return result


def format_percent(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return (f"{value:.1f}").replace(".", ",")


def percent_in(name: str) -> float | None:
    match = PERCENT_RE.search(name)
    return float(match.group(1).replace(",", ".")) if match else None


def bucket_percent(family: str, value: float | None) -> float | None:
    if value is None:
        return None
    standards = FAT_STANDARDS.get(family)
    if not standards:
        return value
    nearest = min(standards, key=lambda item: (abs(item - value), item))
    tolerance = 0.6 if value < 7 else 1.1
    return nearest if abs(nearest - value) <= tolerance else value


def has_fragment(value: str, fragments: Iterable[str]) -> bool:
    text = normalized(value)
    return any(fragment in text for fragment in fragments)


def is_brand_like(name: str) -> bool:
    text = normalized(name)
    return bool(re.search(r"[A-Za-z]", name)) or any(hint in text for hint in BRAND_HINTS)


def dairy_canonical(product: Product) -> tuple[str, str] | None:
    text = normalized(product.name)
    tokens = words(product.name)
    if not tokens or tokens[0] not in DAIRY_FAMILIES:
        return None
    family = tokens[0]
    if has_fragment(text, COMPOSITE_PHRASES):
        if family == "творог" and is_brand_like(product.name):
            return ("brand", "брендовый творожный продукт с добавками")
        return ("exclude", "составной молочный продукт")
    sweet = has_fragment(text, SWEET_DAIRY_WORDS) or "мед" in tokens
    if sweet:
        if family == "творог" and (is_brand_like(product.name) or len(tokens) >= 3):
            return ("brand", "сладкий брендовый творожный продукт")
        return ("exclude", "молочный продукт с наполнителем")

    kind = ""
    if family == "творог":
        if "мягк" in text:
            kind = " мягкий"
        elif "зернен" in text or "зернист" in text:
            kind = " зернёный"
        elif "альбуминов" in text:
            kind = " альбуминовый"
    elif family == "йогурт":
        plain = has_fragment(
            text,
            ("натуральн", "классическ", "традицион", "белый", "греческ", "соев", "питьев"),
        ) or text == "йогурт"
        if not plain:
            return ("exclude", "йогурт с отдельной рецептурой или наполнителем")
        if "греческ" in text:
            kind = " греческий"
            if "питьев" in text:
                kind += " питьевой"
        elif "питьев" in text:
            kind = " питьевой"
        elif "соев" in text:
            kind = " соевый"
        else:
            kind = " натуральный"
    elif family == "молоко":
        milk_types = (
            ("сгущ", " сгущённое"),
            ("сух", " сухое"),
            ("коз", " козье"),
            ("овеч", " овечье"),
            ("кобыл", " кобылье"),
            ("верблюж", " верблюжье"),
            ("соев", " соевое"),
            ("овсян", " овсяное"),
            ("рисов", " рисовое"),
            ("кокос", " кокосовое"),
            ("кешью", " из кешью"),
            ("орех", " ореховое"),
            ("кунжут", " кунжутное"),
            ("буйвол", " буйволиное"),
            ("кисл", " кислое"),
            ("белков", " белковое"),
            ("имбир", " имбирное"),
            ("топлен", " топлёное"),
            ("топлён", " топлёное"),
        )
        for fragment, label in milk_types:
            if fragment in text:
                kind = label
                break
        if "сух" in text and "обезжир" in text:
            kind = " сухое обезжиренное"
        elif "сух" in text and "цельн" in text:
            kind = " сухое цельное"
        elif "сух" in text and "соев" in text:
            kind = " соевое сухое"
        elif "сух" in text and "кедров" in text:
            kind = " кедровое сухое"
        elif "сух" in text and "кокос" in text:
            kind = " кокосовое сухое"
        elif "сух" in text and "овсян" in text:
            kind = " овсяное сухое"
        elif "сгущ" in text and "кокос" in text:
            kind = " кокосовое сгущённое"
        if "сгущ" in text and "нежир" in text:
            kind = " сгущённое нежирное"
        if "с сахар" in text:
            kind += " с сахаром"
        elif "без сахар" in text and "сгущ" in text:
            kind += " без сахара"
        if is_brand_like(product.name) and any(
            plant in kind
            for plant in (
                "кедров",
                "кешью",
                "кокос",
                "кунжут",
                "овсян",
                "орех",
                "рисов",
                "соев",
            )
        ):
            return ("brand", "брендовый растительный напиток с отдельной рецептурой")

    elif family == "сливки":
        if "кокос" in text and "сух" in text:
            kind = " кокосовые сухие"
        elif "кокос" in text:
            kind = " кокосовые"
        elif "соев" in text:
            kind = " соевые"
        elif "сух" in text and "высокожир" in text:
            kind = " сухие высокожирные"
        elif "сух" in text:
            kind = " сухие"
        elif "взбит" in text:
            kind = " взбитые"
        elif "сгущ" in text:
            kind = " сгущённые"
            if "с сахар" in text:
                kind += " с сахаром"

    value = bucket_percent(family, percent_in(product.name))
    if family == "творог" and value is None:
        if "обезжир" in text:
            value = 0.0
        elif "нежир" in text:
            value = 2.0
        elif "полужир" in text:
            value = 9.0
        elif "жирный" in text:
            value = 18.0
    label = family.capitalize() + kind
    if value is not None:
        label += f" {format_percent(value)}%"
    return ("canonical", label + " *")


def grain_canonical(product: Product) -> tuple[str, str] | None:
    text = normalized(product.name)
    if text.startswith(("хлопья 4 злака", "хлопья четыре злака")):
        return ("brand", "смесь хлопьев: состав зависит от производителя")
    if text.startswith("овсяные хлопья"):
        if any(fragment in text for fragment in ("с нутом", "пшеничными отрубями")):
            return ("brand", "смесь хлопьев с дополнительным сырьём")
        if "отруб" in text:
            return ("canonical", "Овсяные хлопья с отрубями *")
        if "быстр" in text or "тонк" in text or "№2" in product.name:
            return ("canonical", "Овсяные хлопья быстрого приготовления *")
        return ("canonical", "Овсяные хлопья традиционные *")
    if text.startswith(("гречка", "гречневая крупа")):
        if " с " in text or " на " in text:
            return ("exclude", "готовая или составная гречка")
        state = " отварная" if has_fragment(text, ("варен", "варён", "отвар", "каша")) else " сухая"
        if "зелен" in text:
            return ("canonical", f"Гречка зелёная{state} *")
        return ("canonical", f"Гречка{state} *")
    if text.startswith("гречневая каша"):
        if has_fragment(
            text,
            ("с маслом", "с молоком", "на молоке", "с мясом", "с грибами"),
        ):
            return ("exclude", "готовая гречневая каша с добавками")
        if product.kcal > 220 or product.carbohydrate > 40:
            return ("exclude", "сухая готовая гречневая каша")
        return ("canonical", "Гречка отварная *")
    if text.startswith("рис ") or text == "рис":
        if has_fragment(text, ("с овощ", "с гриб", "готово!", "смесь")):
            return ("exclude", "готовый или составной рис")
        if has_fragment(
            text,
            (
                "color mix",
                "mix",
                "четыре риса",
                "для жарки",
                "здоровье",
                "ширатаки",
            ),
        ) or "+" in text or ("дикий" in text and "парбоилд" in text):
            return ("brand", "отдельный сорт, смесь или готовая рецептура риса")
        state = " отварной" if has_fragment(text, ("варен", "варён", "отвар", "готов")) else " сухой"
        if ("длинноз" in text) and has_fragment(text, ("пропар", "золотист")):
            kind = " белый длиннозёрный пропаренный"
        else:
            kinds = (
                ("для суши", " для суши"),
                ("фушигон", " для суши"),
                ("суши", " для суши"),
                ("карнароли", " карнароли"),
                ("ризотто", " арборио"),
                ("нишики", " для суши"),
                ("басмати", " басмати"),
                ("жасмин", " жасмин"),
                ("нешлиф", " бурый"),
                ("бур", " бурый"),
                ("коричнев", " бурый"),
                ("дикий", " дикий"),
                ("черн", " чёрный"),
                ("красн", " красный"),
                ("кругл", " белый круглозёрный"),
                ("длинноз", " белый длиннозёрный"),
                ("пропар", " белый пропаренный"),
                ("золотист", " белый пропаренный"),
                ("арборио", " арборио"),
            )
            kind = " белый"
            for fragment, label in kinds:
                if fragment in text:
                    kind = label
                    break
        return ("canonical", f"Рис{kind}{state} *")
    return None


def obvious_ready(product: Product) -> str | None:
    text = normalized(product.name)
    first = words(product.name)[0] if words(product.name) else ""
    if product.category in EXCLUDED_CATEGORIES:
        return f"категория не нужна в каталоге ингредиентов: {product.category}"
    if (
        any(brand in text for brand in BABY_BRANDS)
        and first not in {"биотворог", "сырок", "творог", "творожок"}
        and product.category != "Сыры и творог"
    ):
        return "детское питание"
    if first in ALCOHOL_PREFIXES:
        return "алкогольный напиток"
    if any(fragment in text for fragment in READY_NAME_FRAGMENTS):
        return "ресторанный или готовый продукт"
    if has_fragment(text, ("стрипс", "байтсы")):
        return "ресторанный или готовый продукт"
    if any(text.startswith(prefix) for prefix in READY_STARTS):
        return "готовое блюдо"
    if text.startswith("крем-суп"):
        return "готовый суп"
    if first in READY_PREFIXES:
        return "готовое блюдо"
    if any(fragment in text for fragment in ("масло репейное", "масло иланг", "масло шишек хмеля", "пачули")):
        return "непищевой продукт"
    if text in BROAD_NAMES:
        return "слишком общее название без конкретного продукта"
    return None


def special_product(product: Product) -> tuple[str, str] | None:
    text = normalized(product.name)
    if any(text.startswith(prefix) for prefix in SPECIAL_PRODUCT_PREFIXES):
        return ("brand", "отдельная готовая или брендовая рецептура")
    return None


def significant_name(name: str) -> str:
    text = normalized(name)
    text = PERCENT_RE.sub("", text)
    for word in sorted(GENERIC_DROP_WORDS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", "", text)
    return " ".join(text.split())


def generic_seed(product: Product) -> bool:
    if is_brand_like(product.name):
        return False
    tokens = words(product.name)
    if not 1 <= len(tokens) <= 3:
        return False
    if any(token.isdigit() for token in tokens):
        return False
    return not obvious_ready(product)


def whole_candidate(product: Product) -> bool:
    first = words(product.name)[0] if words(product.name) else ""
    return product.category in WHOLE_CATEGORIES or first in WHOLE_FIRST_WORDS


def nutrient_distance(left: Product, right: Product) -> float:
    return (
        abs(left.protein - right.protein) / 3
        + abs(left.fat - right.fat) / 3
        + abs(left.carbohydrate - right.carbohydrate) / 5
        + abs(left.kcal - right.kcal) / 40
    )


def state_tags(text: str) -> frozenset[str]:
    groups = {
        "boiled": ("варен", "варён", "отвар"),
        "fried": ("жарен", "жарён"),
        "frozen": ("заморож", "быстрозаморож"),
        "canned": ("консерв",),
        "marinated": ("маринован", "маринад"),
        "smoked": ("копчен", "копчён"),
        "dried": ("сушен", "сушён", "вялен", "вялён"),
        "dry": ("сухой", "сухая", "сухое"),
        "fresh": ("свеж", "сырой", "сырая", "сырое"),
    }
    return frozenset(
        key for key, fragments in groups.items() if any(item in text for item in fragments)
    )


def form_tags(text: str) -> frozenset[str]:
    groups = {
        "mince": ("фарш",),
        "fillet": ("филе",),
        "breast": ("грудк",),
        "thigh": ("бедр",),
        "wing": ("крыл",),
        "shoulder": ("лопатк",),
        "ham": ("окорок",),
        "steak": ("стейк",),
        "tenderloin": ("вырезк",),
        "wholegrain": ("цельнозер", "цельносмолот"),
        "top_flour": ("высшего сорта",),
        "first_flour": ("1-го сорта", "первого сорта"),
        "second_flour": ("2-го сорта", "второго сорта"),
        "durum": ("твердых сорт", "твёрдых сорт", "durum"),
        "bran": ("отруб",),
        "almond_flour": ("миндальн",),
        "buckwheat_flour": ("гречнев",),
        "chickpea_flour": ("нутов",),
        "coconut_flour": ("кокосов",),
        "corn_flour": ("кукурузн",),
        "oat_flour": ("овсян",),
        "rice_flour": ("рисов",),
        "rye_flour": ("ржан",),
        "wheat_flour": ("пшеничн",),
        "soft": ("мягк",),
        "grainy": ("зернен", "зернён", "зернист"),
    }
    return frozenset(
        key for key, fragments in groups.items() if any(item in text for item in fragments)
    )


def seed_match(product: Product, seeds: list[Product]) -> Product | None:
    product_tokens = set(words(significant_name(product.name)))
    if not product_tokens:
        return None
    candidates: list[tuple[int, float, Product]] = []
    first = words(product.name)[0]
    product_text = normalized(product.name)
    product_states = state_tags(product_text)
    product_forms = form_tags(product_text)
    for seed in seeds:
        seed_words = words(seed.name)
        if not seed_words or seed_words[0] != first:
            continue
        seed_tokens = set(words(significant_name(seed.name)))
        if not seed_tokens or not seed_tokens.issubset(product_tokens):
            continue
        seed_text = normalized(seed.name)
        if product_states != state_tags(seed_text):
            continue
        if product_forms != form_tags(seed_text):
            continue
        if any(
            marker in product_text and marker not in seed_text
            for marker in (" с ", " со ", " из ")
        ):
            continue
        distance = nutrient_distance(product, seed)
        if distance > 2.0:
            continue
        candidates.append((-len(seed_tokens), distance, seed))
    return min(candidates, default=(0, 0, None))[2]


def canonical_key(name: str) -> str:
    return normalized(name.removesuffix(" *"))


def outlier(member: Product, members: list[Product]) -> bool:
    if intrinsic_anomaly(member):
        return True
    if len(members) < 3:
        return False
    medians = {
        field: median(getattr(item, field) for item in members)
        for field in ("protein", "fat", "carbohydrate", "kcal")
    }
    for field in ("protein", "fat", "carbohydrate"):
        middle = medians[field]
        if abs(getattr(member, field) - middle) > max(2.0, middle * 0.30):
            return True
    return abs(member.kcal - medians["kcal"]) > max(30.0, medians["kcal"] * 0.20)


def intrinsic_anomaly(member: Product) -> bool:
    tokens = words(member.name)
    if not tokens or tokens[0] not in DAIRY_FAMILIES:
        return False
    declared = percent_in(member.name)
    if declared is not None and abs(member.fat - declared) > max(1.5, declared * 0.25):
        return True
    calculated = 4 * member.protein + 9 * member.fat + 4 * member.carbohydrate
    return abs(member.kcal - calculated) > 60 and (
        member.kcal > calculated * 1.5 or member.kcal < calculated * 0.65
    )


def averaged_product(name: str, members: list[Product]) -> dict[str, object] | None:
    valid = [member for member in members if not outlier(member, members)]
    if not valid:
        return None
    values = {
        field: sum(getattr(member, field) for member in valid) / len(valid)
        for field in ("protein", "fat", "carbohydrate", "kcal")
    }
    rounded = {
        "protein": round(values["protein"], 1),
        "fat": round(values["fat"], 1),
        "carbohydrate": round(values["carbohydrate"], 1),
        "kcal": round(values["kcal"]),
    }
    signature = json.dumps(
        {"canonical_key": canonical_key(name), **rounded},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]
    return {
        "source_url": f"curated://recipe-catalog/v1/{digest}",
        "name": name,
        **rounded,
        "member_count": len(members),
        "averaged_count": len(valid),
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def curate(products: list[Product]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    seeds = [
        product
        for product in products
        if generic_seed(product) and whole_candidate(product)
    ]
    groups: dict[str, list[Product]] = defaultdict(list)
    group_names: dict[str, str] = {}
    decisions: dict[str, dict[str, object]] = {}
    brands: list[Product] = []

    for product in products:
        reason = obvious_ready(product)
        result = ("exclude", reason) if reason else None
        if result is None:
            result = special_product(product) or dairy_canonical(product) or grain_canonical(product)
        if result is None:
            seed = seed_match(product, seeds)
            if whole_candidate(product) and seed and (
                is_brand_like(product.name) or normalized(seed.name) != normalized(product.name)
            ):
                result = ("canonical", seed.name + " *")
            elif generic_seed(product) and whole_candidate(product):
                result = ("canonical", product.name + " *")
            else:
                result = ("brand", "отдельная брендовая или специальная рецептура")

        action, target = result
        if action == "canonical":
            key = canonical_key(target)
            groups[key].append(product)
            group_names[key] = target
            decisions[product.source_url] = {
                "decision": "merge",
                "canonical_key": key,
                "canonical_name": target,
                "reason": "базовый продукт без значимой брендовой рецептуры",
            }
        elif action == "brand":
            brands.append(product)
            decisions[product.source_url] = {
                "decision": "keep_brand",
                "canonical_key": None,
                "canonical_name": product.name,
                "reason": target,
            }
        else:
            decisions[product.source_url] = {
                "decision": "exclude",
                "canonical_key": None,
                "canonical_name": None,
                "reason": target,
            }

    curated: list[dict[str, object]] = []
    canonical_urls: dict[str, str] = {}
    for key in sorted(groups):
        members = groups[key]
        if len(members) == 2 and nutrient_distance(members[0], members[1]) > 3.0:
            generic = [member for member in members if generic_seed(member)]
            if len(generic) == 1:
                compatible = generic
            else:
                exact = [
                    member
                    for member in members
                    if canonical_key(member.name) == key
                ]
                compatible = exact if len(exact) == 1 else []
            separated = [member for member in members if member not in compatible]
            for member in separated:
                brands.append(member)
                decisions[member.source_url].update(
                    decision="keep_brand",
                    reason="КБЖУ несовместимы со второй карточкой группы",
                    canonical_key=None,
                    canonical_name=member.name,
                )
            members = compatible
        if not members:
            continue
        row = averaged_product(group_names[key], members)
        if row is None:
            for member in members:
                decisions[member.source_url].update(
                    decision="exclude_outlier",
                    reason="единственный источник имеет подозрительные значения КБЖУ",
                    canonical_key=None,
                    canonical_name=None,
                )
            continue
        curated.append(row)
        canonical_urls[key] = str(row["source_url"])
        for member in members:
            if outlier(member, members):
                decisions[member.source_url].update(
                    decision="exclude_outlier",
                    reason="значения КБЖУ выбиваются из группы и не участвуют в среднем",
                )

    for product in brands:
        curated.append(
            {
                "source_url": product.source_url,
                "name": product.name,
                "protein": product.protein,
                "fat": product.fat,
                "carbohydrate": product.carbohydrate,
                "kcal": product.kcal,
                "member_count": 1,
                "averaged_count": 1,
            }
        )

    log: list[dict[str, object]] = []
    by_url = {product.source_url: product for product in products}
    for source_url in sorted(by_url):
        product = by_url[source_url]
        decision = decisions[source_url]
        key = decision.get("canonical_key")
        log.append(
            {
                **asdict(product),
                **decision,
                "canonical_source_url": canonical_urls.get(str(key)) if key else None,
            }
        )
    return sorted(curated, key=lambda row: normalized(str(row["name"]))), log


def build(source: Path, output: Path) -> dict[str, object]:
    products = read_products(source)
    curated, log = curate(products)
    original_rows = [asdict(product) for product in products]
    write_jsonl(output / "original-products.jsonl", original_rows)
    write_jsonl(output / "curation-log.jsonl", log)
    write_jsonl(output / "curated-products.jsonl", curated)
    decisions: dict[str, int] = defaultdict(int)
    decision_reasons: dict[str, int] = defaultdict(int)
    for row in log:
        decisions[str(row["decision"])] += 1
        decision_reasons[str(row["reason"])] += 1
    source_categories: dict[str, int] = defaultdict(int)
    source_families: dict[str, int] = defaultdict(int)
    active_families: dict[str, int] = defaultdict(int)
    for product in products:
        source_categories[product.category or "без категории"] += 1
        source_families[words(product.name)[0] if words(product.name) else "без названия"] += 1
    for row in curated:
        name_words = words(str(row["name"]))
        active_families[name_words[0] if name_words else "без названия"] += 1
    canonical_count = sum(
        str(row["source_url"]).startswith("curated://") for row in curated
    )
    brand_count = len(curated) - canonical_count
    summary = {
        "schema_version": 1,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_products": len(products),
        "active_products": len(curated),
        "net_reduction": len(products) - len(curated),
        "canonical_products": canonical_count,
        "brand_products": brand_count,
        "collapsed_source_rows": decisions["merge"] - canonical_count,
        "hidden_source_rows": decisions["exclude"] + decisions["exclude_outlier"],
        "decisions": dict(sorted(decisions.items())),
        "decision_reasons": dict(
            sorted(decision_reasons.items(), key=lambda item: (-item[1], item[0]))
        ),
        "source_categories": dict(
            sorted(source_categories.items(), key=lambda item: (-item[1], item[0]))
        ),
        "source_families": dict(
            sorted(source_families.items(), key=lambda item: (-item[1], item[0]))
        ),
        "active_families": dict(
            sorted(active_families.items(), key=lambda item: (-item[1], item[0]))
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.sqlite, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
