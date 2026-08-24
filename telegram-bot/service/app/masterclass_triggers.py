from __future__ import annotations


TRIGGERS = [
    {
        "step_key": "pp_identity",
        "content_code": "tpl_postpurchase_identity",
        "title": "01 · После привязки — данные клиента",
        "trigger": "messenger_link_confirmed",
        "condition": "Telegram успешно привязан к покупателю мастер-класса",
        "recipient": "Клиент, который только что привязал Telegram",
        "purpose": "Показать email, тариф и дату покупки; дать ссылку на личный кабинет.",
    },
    {
        "step_key": "pp_questionnaire",
        "content_code": "tpl_postpurchase_questionnaire",
        "title": "02 · После привязки — анкета для пересылки",
        "trigger": "messenger_link_confirmed",
        "condition": "Сразу после блока с данными клиента",
        "recipient": "Тот же клиент",
        "purpose": "Прислать заполненную стартовую анкету и попросить переслать её Сергею.",
    },
    {
        "step_key": "pp_day_unopened_18h",
        "content_code": "tpl_postpurchase_day_unopened",
        "title": "03 · Новый день не открыт к 18:00",
        "trigger": "course_day_unopened_18h",
        "condition": "В 18:00 местного времени день доступен, но ещё ни разу не открыт",
        "recipient": "Клиент с привязанным Telegram и действующим доступом",
        "purpose": "Один раз напомнить о новом дне без утреннего сообщения и повторов.",
    },
    {
        "step_key": "pp_course_stalled_72h",
        "content_code": "tpl_postpurchase_tempo_late",
        "title": "04 · Давно не заходил в Мастер-класс",
        "trigger": "course_stalled_72h",
        "condition": "Нет новой активности 72 часа, курс не завершён, доступ действует",
        "recipient": "Клиент, который остановился",
        "purpose": "Мягко вернуть человека к следующему незавершённому месту.",
    },
    {
        "step_key": "pp_sales_early_missing",
        "content_code": "tpl_postpurchase_recipes_missing",
        "title": "04 · Рецепты открылись, но не куплены",
        "trigger": "sales_last_chance_due",
        "condition": "Этап early/second, ACCESS_RECIPES отсутствует, предложение ещё действует",
        "recipient": "Клиент без рецептов",
        "purpose": "Показать только актуальное персональное предложение рецептов.",
    },
    {
        "step_key": "pp_sales_early_owned",
        "content_code": "tpl_postpurchase_recipes_owned",
        "title": "05 · Рецепты уже куплены",
        "trigger": "sales_last_chance_due",
        "condition": "Рецепты куплены, но остаются другие разрешённые продукты",
        "recipient": "Клиент с рецептами",
        "purpose": "Не продавать рецепты повторно; при необходимости показать остальные продукты.",
    },
    {
        "step_key": "pp_review_consultation",
        "content_code": "tpl_postpurchase_review_consultation",
        "title": "06 · Саморевью, консультация куплена",
        "trigger": "closing_review_opened",
        "condition": "Открыто итоговое саморевью и есть ACCESS_CONSULTATION",
        "recipient": "Клиент с консультацией",
        "purpose": "Объяснить, как отправить саморевью и получить разбор.",
    },
    {
        "step_key": "pp_review_no_consultation",
        "content_code": "tpl_postpurchase_review_no_consultation",
        "title": "07 · Саморевью, консультация не куплена",
        "trigger": "closing_review_opened",
        "condition": "Открыто итоговое саморевью, ACCESS_CONSULTATION отсутствует",
        "recipient": "Клиент без консультации",
        "purpose": "Поддержать самостоятельное саморевью и показать актуальный разбор.",
    },
    {
        "step_key": "pp_final_offer",
        "content_code": "tpl_postpurchase_final_offer",
        "title": "08 · Финальное предложение",
        "trigger": "sales_last_chance_due",
        "condition": "Этап last_week, есть недостающие продукты, предложение ещё действует",
        "recipient": "Клиент с недостающими продуктами",
        "purpose": "Один раз показать итоговый комплект; после срока больше не отправлять.",
    },
    {
        "step_key": "pp_review_week_day2",
        "content_code": "tpl_postpurchase_review_week_1",
        "title": "09 · После саморевью — день 2",
        "trigger": "closing_review_opened + 2 days",
        "condition": "Есть действующий ACCESS_MASTERCLASS; событие первого открытия саморевью сохранено",
        "recipient": "Клиент на второй день после первого открытия саморевью",
        "purpose": "Первое сообщение недели закрепления результатов.",
    },
    {
        "step_key": "pp_review_week_day4",
        "content_code": "tpl_postpurchase_review_week_2",
        "title": "10 · После саморевью — день 4",
        "trigger": "closing_review_opened + 4 days",
        "condition": "Есть действующий ACCESS_MASTERCLASS; событие первого открытия саморевью сохранено",
        "recipient": "Клиент на четвёртый день после первого открытия саморевью",
        "purpose": "Второе сообщение недели закрепления результатов.",
    },
    {
        "step_key": "pp_review_week_day7",
        "content_code": "tpl_postpurchase_review_week_3",
        "title": "11 · После саморевью — день 7",
        "trigger": "closing_review_opened + 7 days",
        "condition": "Есть действующий ACCESS_MASTERCLASS; событие первого открытия саморевью сохранено",
        "recipient": "Клиент на седьмой день после первого открытия саморевью",
        "purpose": "Завершить postpurchase_masterclass; следующий модуль пока отключён.",
    },
]

TRIGGER_BY_STEP = {item["step_key"]: item for item in TRIGGERS}


def editorial_help(step_key: str) -> dict | None:
    item = TRIGGER_BY_STEP.get(step_key)
    if not item:
        return None
    return {key: item[key] for key in ("trigger", "condition", "recipient", "purpose")}
