from __future__ import annotations

from copy import deepcopy
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.managed_documents import ensure_seed_document, publish_document
from app.models import ManagedDocumentVersion


DOCUMENT_TYPE = "product-catalog"
DOCUMENT_KEY = "core"
SCHEMA_VERSION = 1

# These links change behaviour (access and app launch), so they deliberately do
# not appear in the editorial editor. The product catalog owns public wording.
PRODUCT_CONNECTIONS = {
    "masterclass": {"resource": "ACCESS_MASTERCLASS", "app": "masterclass-course", "ready": True},
    "recipes": {"resource": "ACCESS_RECIPES", "app": None, "ready": False},
    "calories": {"resource": "ACCESS_CALORIES", "app": None, "ready": False},
    "training": {"resource": "ACCESS_STRENGTH", "app": None, "ready": False},
    "recordings": {"resource": "ACCESS_CONSULTATION_RECORDINGS", "app": None, "ready": False},
    "consultation": {"resource": "ACCESS_CONSULTATION", "app": None, "ready": False},
    "coaching": {"resource": "ACCESS_COACHING", "app": None, "ready": False},
    "intensive": {"resource": None, "app": None, "ready": False},
}

PRODUCT_CATALOG_SEED = {
    "schemaVersion": SCHEMA_VERSION,
    "products": [
        {"code": "masterclass", "shortName": "Мастер-класс", "fullName": "Мастер-класс по изменению питания и пищевых привычек", "descriptor": "Как простыми действиями изменить пищевые привычки и сбалансировать своё питание так, чтобы сделать похудение проще, а не тянуть его только на силе воли", "status": "active", "programReference": "21-дневная программа Мастер-класса", "ai": {"core": "Не курс с абстрактными правилами, а последовательная работа с реальным питанием и привычками.", "mechanics": "Дневник питания, вопросы и задания, оценка качества рациона, практические материалы и стратегия комфортного похудения.", "outcome": "Человек замечает закономерности своего питания и принимает решения не только потому, что «так надо».", "theses": "Сначала увидеть реальное питание; дневник — инструмент наблюдения, а не наказания; не переделывать всё за один день; привычки уменьшают зависимость от силы воли.", "pains": "Знаю, как правильно, но делаю иначе; мотивации хватает ненадолго; не понимаю, что реально мешает; хочу худеть без постоянного терпения.", "limits": "Не является медицинской услугой и не заменяет назначения врача."}},
        {"code": "recipes", "shortName": "Система рецептов", "fullName": "Система рецептов", "descriptor": "Как собирать здоровые, сытные и вкусные тарелки из привычных продуктов", "status": "active", "programReference": "Программа Системы рецептов", "ai": {"core": "Не просто каталог, а система самостоятельной сборки еды.", "mechanics": "Рецепты, выбор продуктов и готовой еды, конструктор блюд, вкус, организация кухни и готовки.", "outcome": "Человек понимает, как собрать нормальную тарелку из доступных продуктов или готовой еды.", "theses": "Здоровая еда не равна отдельной ПП-кухне; важен принцип сборки; готовая еда допустима; рецепты учат мыслить, а не только смешивать.", "pains": "Не знаю, что готовить; еда надоедает; полезное кажется пресным; не хочу проводить много времени на кухне.", "limits": "Состав и ключевые пункты берутся из программы продукта."}},
        {"code": "calories", "shortName": "Калорийный курс", "fullName": "Мини-курс «Калорийный»", "descriptor": "Как научиться считать калории так, чтобы вам больше никогда не пришлось считать калории", "status": "active", "programReference": "Программа Мини-курса «Калорийный»", "ai": {"core": "Подсчёт калорий — обучающий этап, а не пожизненная система контроля.", "mechanics": "Энергетический баланс, порции, оценка еды и собственных потребностей.", "outcome": "Человек понимает, как постепенно отказаться от постоянного приложения и подсчёта.", "theses": "Калории — инструмент, а не образ жизни; запись еды не равна навыку управления весом; цель — сделать подсчёт ненужным.", "pains": "Не понимаю, сколько есть; устал взвешивать; боюсь перестать считать; давно считаю, но завишу от приложения.", "limits": "Состав и ключевые пункты берутся из программы продукта."}},
        {"code": "training", "shortName": "Курс по тренировкам", "fullName": "Мини-курс «С мягкого дивана до регулярных тренировок»", "descriptor": "Как выбрать свой уровень тренировок и встроить регулярные занятия в жизнь без лишнего перегруза", "status": "planned", "programReference": "Будущая программа курса по тренировкам", "ai": {"core": "Выбор результата и реалистичного уровня тренировок вместо одной «идеальной» программы.", "mechanics": "Направления и три уровня: минимальный рабочий, любительский и более серьёзный.", "outcome": "Человек понимает, какой результат получит за свои усилия и время.", "theses": "Не всем нужны тренировки пять раз в неделю; цели требуют разного объёма; цена следующего уровня должна быть понятна заранее.", "pains": "Не понимаю, с чего начать; не знаю, сколько тренировок нужно; не хочу посвящать спорту всю жизнь.", "limits": "Продукт готовится; состав и программа будут утверждены отдельно."}},
        {"code": "recordings", "shortName": "Записи разборов", "fullName": "Записи консультаций других участников", "descriptor": "Как разбирать реальные ситуации с питанием и находить подходящие решения", "status": "planned", "programReference": "Будущая программа записей разборов", "ai": {"core": "", "mechanics": "", "outcome": "", "theses": "", "pains": "", "limits": "Содержание продукта ещё не утверждено."}},
        {"code": "consultation", "shortName": "Консультация", "fullName": "Разбор дневника питания и индивидуальная консультация", "descriptor": "Как разобрать дневник питания и получить индивидуальную консультацию", "status": "active", "programReference": "Сценарий индивидуальной консультации", "ai": {"core": "Сначала разбирается дневник, затем обсуждаются выводы удобным способом.", "mechanics": "Предварительный разбор дневника и индивидуальное обсуждение звонком или голосовыми сообщениями.", "outcome": "Человек получает разбор своей ситуации и ответы на личные вопросы.", "theses": "Основание консультации — реальная история питания, а не общий совет.", "pains": "Хочу понять свою ситуацию и задать личные вопросы.", "limits": "Не является медицинской услугой и не заменяет назначения врача."}},
        {"code": "coaching", "shortName": "Сопровождение", "fullName": "Индивидуальное сопровождение", "descriptor": "Как получать регулярную поддержку при внедрении изменений в питание", "status": "planned", "programReference": "Будущая программа индивидуального сопровождения", "ai": {"core": "", "mechanics": "", "outcome": "", "theses": "", "pains": "", "limits": "Содержание продукта ещё не утверждено."}},
        {"code": "intensive", "shortName": "Бесплатный интенсив", "fullName": "Бесплатный интенсив «Последнее похудение»", "descriptor": "Как начать разбираться в похудении без жёстких ограничений", "status": "active", "programReference": "Программа бесплатного интенсива «Последнее похудение»", "ai": {"core": "Бесплатная вводная программа о плане похудения и базовых ошибках.", "mechanics": "Учебные материалы и практические задания.", "outcome": "Человек понимает первые шаги и недостающие навыки.", "theses": "Похудение начинается не с жёстких ограничений.", "pains": "Не понимаю, с чего начать и почему прежние попытки не держатся.", "limits": "Не является индивидуальной консультацией."}},
    ],
    "tariffs": [
        {"code": "MASTERCLASS_BASIC", "name": "Минимальный", "descriptor": "Мастер-класс и все основные инструменты.", "products": ["masterclass"], "status": "active"},
        {"code": "MASTERCLASS_RECIPES", "name": "Стандартный", "descriptor": "Мастер-класс вместе с Системой рецептов.", "products": ["masterclass", "recipes"], "status": "active"},
        {"code": "MASTERCLASS_CONSULT", "name": "С консультацией", "descriptor": "Полный тариф с индивидуальным разбором.", "products": ["masterclass", "recipes", "consultation"], "status": "active"},
    ],
}

AI_FIELDS = {"core", "mechanics", "outcome", "theses", "pains", "limits"}
PRODUCT_FIELDS = {"shortName", "fullName", "descriptor", "status", "programReference", "ai"}
TARIFF_FIELDS = {"name", "descriptor", "status"}
ALLOWED_STATUSES = {"active", "planned", "archived"}


def active_product_catalog(db: Session) -> ManagedDocumentVersion:
    return ensure_seed_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY, schema_version=SCHEMA_VERSION, payload=PRODUCT_CATALOG_SEED)


def catalog_payload(db: Session) -> dict:
    return deepcopy(active_product_catalog(db).payload)


def catalog_index(db: Session) -> tuple[dict[str, dict], dict[str, dict]]:
    payload = catalog_payload(db)
    return ({item["code"]: item for item in payload["products"]}, {item["code"]: item for item in payload["tariffs"]})


def product_public(db: Session, code: str) -> dict:
    products, _ = catalog_index(db)
    try:
        item = products[code]
    except KeyError as exc:
        raise KeyError(f"unknown catalog product: {code}") from exc
    return {"code": code, "name": item["fullName"], "short_name": item["shortName"], "description": item["descriptor"], "status": item["status"], **PRODUCT_CONNECTIONS[code]}


def tariff_public(db: Session, code: str) -> dict | None:
    _, tariffs = catalog_index(db)
    item = tariffs.get(code)
    if item is None:
        return None
    return {"code": code, "name": item["name"], "description": item["descriptor"], "products": list(item["products"]), "status": item["status"]}


def validate_catalog(proposed: dict, current: dict) -> dict:
    if not isinstance(proposed, dict) or len(json.dumps(proposed, ensure_ascii=False).encode()) > 500_000:
        raise HTTPException(422, "Каталог имеет неверный формат или слишком большой размер")
    if set(proposed) != set(current):
        raise HTTPException(422, "Структуру каталога нельзя менять этим редактором")
    result = deepcopy(proposed)
    for kind, allowed in (("products", PRODUCT_FIELDS), ("tariffs", TARIFF_FIELDS)):
        if not isinstance(result.get(kind), list) or len(result[kind]) != len(current[kind]):
            raise HTTPException(422, "Добавление, удаление и перестановка выполняются отдельной задачей")
        if [item.get("code") for item in result[kind]] != [item.get("code") for item in current[kind]]:
            raise HTTPException(422, "Коды и порядок элементов нельзя менять")
        for item, old in zip(result[kind], current[kind], strict=True):
            if set(item) != set(old) or any(key not in allowed | {"code", "products"} for key in item):
                raise HTTPException(422, "Набор полей каталога нельзя менять")
            for key in old:
                if key not in allowed and item.get(key) != old.get(key):
                    raise HTTPException(422, f"Системное поле {key} нельзя менять")
            for key in allowed - {"ai"}:
                if key in item:
                    item[key] = str(item.get(key) or "").strip()
                    if len(item[key]) > 20_000:
                        raise HTTPException(422, "Текст поля слишком длинный")
            if kind == "products":
                if set(item.get("ai") or {}) != AI_FIELDS:
                    raise HTTPException(422, "Набор внутренних полей ИИ нельзя менять")
                item["ai"] = {key: str(item["ai"].get(key) or "").strip() for key in AI_FIELDS}
                if not item["fullName"] or not item["descriptor"].startswith("Как"):
                    raise HTTPException(422, "Укажите полное название и дескрипшн, начинающийся с «Как»")
            elif not item["name"]:
                raise HTTPException(422, "Укажите название тарифа")
            if item["status"] not in ALLOWED_STATUSES:
                raise HTTPException(422, "Статус может быть только active, planned или archived")
    return result


def publish_product_catalog(db: Session, *, payload: dict, expected_version: int, admin: str) -> ManagedDocumentVersion:
    current = active_product_catalog(db)
    return publish_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY, schema_version=SCHEMA_VERSION, payload=validate_catalog(payload, current.payload), expected_version=expected_version, admin=admin)
