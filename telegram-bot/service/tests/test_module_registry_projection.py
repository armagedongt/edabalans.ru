from __future__ import annotations

import json

import pytest

from app.graph import TELEGRAM_MODULES, load_global_modules


def test_generated_global_modules_are_loaded_in_canonical_order() -> None:
    expected = [
        ("start_attribution", "Старт и атрибуция", 10, "messaging.telegram.attribution"),
        ("welcome_intensive", "Welcome: запуск и первые четыре дня", 20, "messaging.telegram.intensive"),
        ("prepurchase_nurture", "Основная рассылка до покупки", 30, "messaging.telegram.prepurchase"),
        ("postpurchase_masterclass", "После покупки мастер-класса", 40, "messaging.telegram.postpurchase"),
        ("postmasterclass_nurture", "После завершения мастер-класса", 50, "messaging.telegram.postmasterclass"),
        ("broadcasts", "Разовые рассылки", 60, "messaging.telegram.broadcasts"),
        ("inbox", "Входящие сообщения и ответы", 70, "messaging.telegram.direct-support"),
        ("lottery", "Лотерея", 80, "planned.telegram-lottery"),
        ("quiz", "Тесты и опросы", 90, "planned.telegram-quiz"),
    ]
    assert [
        (module["code"], module["name"], module["order"], module["module_id"])
        for module in TELEGRAM_MODULES
    ] == expected
    assert all(module["status"] and module["card"].endswith(f"{module['module_id']}.md") for module in TELEGRAM_MODULES)


def test_generated_global_modules_fail_closed_on_invalid_projection(tmp_path) -> None:
    path = tmp_path / "telegram-global-modules.json"
    path.write_text(
        json.dumps({"schema_version": 1, "modules": [{"code": "incomplete"}]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid entry"):
        load_global_modules(path)
