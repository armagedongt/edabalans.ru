from app.importers.apply_tag_rules_v2 import (
    ARCHIVE_FAMILIES,
    CONTENT_MERGES,
    INTENSIVE_COMPLETE,
    LOTTERY_OPENED,
    PURCHASE_SOURCES,
)


def test_owner_approved_purchase_components() -> None:
    assert "Сама 3 недели" in PURCHASE_SOURCES["Мастер-класс"]
    assert "МК+Сопровождение" in PURCHASE_SOURCES["Калории"]
    assert "МК+Сопровождение" in PURCHASE_SOURCES["Консультация"]
    assert "МК «Стандартный»" in PURCHASE_SOURCES["Рецепты"]
    assert "МК «Стандартный»" not in PURCHASE_SOURCES["Калории"]


def test_owner_approved_content_merges_and_archives() -> None:
    assert {"Стрим - Вредная еда", "Стрим - Стрим «Вредная» еда"} <= (
        CONTENT_MERGES["Пост - Стрим - Вредная еда"]
    )
    assert {"Пост - Эмоции", "Пост - Эмоциональный голод"} <= (
        CONTENT_MERGES["Пост - Эмоциональный голод"]
    )
    assert "Материал - Видео" in ARCHIVE_FAMILIES
    assert "Пост - Подарок от 12 изменений" in ARCHIVE_FAMILIES


def test_owner_approved_intensive_and_lottery_rules() -> None:
    assert "Открыт День 4" in INTENSIVE_COMPLETE
    assert "Открыл Интенсив день 5" not in INTENSIVE_COMPLETE
    assert "Интенсив в закреп теперь" not in INTENSIVE_COMPLETE
    assert "Заходил в скидку" in LOTTERY_OPENED
