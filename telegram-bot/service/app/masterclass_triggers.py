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
        "step_key": "pp_current_diet_questionnaire",
        "content_code": "tpl_postpurchase_current_diet",
        "title": "03 · День 2 — ответы по продуктовым категориям",
        "trigger": "current_diet_questionnaire_completed",
        "condition": "Опросник дня 2 отправлен; Telegram связан с клиентом",
        "recipient": "Клиент, который заполнил опросник дня 2",
        "purpose": "Прислать в Telegram структурированный список ответов по 16 продуктовым категориям.",
    },
    {
        "step_key": "pp_dqs_app_link",
        "content_code": "tpl_postpurchase_dqs_app_link",
        "title": "DQS — ссылка на приложение",
        "trigger": "dqs_app_link_requested",
        "condition": "Участник сам нажал кнопку в материале DQS; Telegram привязан и доступ к мастер-классу действует",
        "recipient": "Тот же участник",
        "purpose": "Отправить ссылку и кнопку открытия существующего DQS как Telegram Web App; MAX и автоматическая рассылка не используются.",
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
        "condition": "За 24 часа до конца текущего окна early/second: ACCESS_RECIPES отсутствует, покупок в окне не было, предложение ещё действует",
        "recipient": "Клиент без рецептов",
        "purpose": "Показать только актуальное персональное предложение рецептов.",
    },
    {
        "step_key": "pp_sales_early_owned",
        "content_code": "tpl_postpurchase_recipes_owned",
        "title": "05 · Рецепты уже куплены",
        "trigger": "sales_last_chance_due",
        "condition": "За 24 часа до конца текущего окна early/second: рецепты уже были куплены раньше, остаются другие разрешённые продукты и покупок в этом окне не было",
        "recipient": "Клиент с рецептами",
        "purpose": "Не продавать рецепты повторно; при необходимости показать остальные продукты.",
    },
    {
        "step_key": "pp_closing_review_copy",
        "content_code": "tpl_postpurchase_closing_review_copy",
        "title": "06 · Копия итогового саморевью",
        "trigger": "closing_review_submitted",
        "condition": "Анкета отправлена; telegram_linked=true",
        "recipient": "Участник, который заполнил итоговое саморевью",
        "purpose": "Вернуть участнику полную копию анкеты и объяснить, как при желании переслать её Сергею.",
    },
    {
        "step_key": "pp_final_offer",
        "content_code": "tpl_postpurchase_final_offer",
        "title": "08 · Финальное предложение",
        "trigger": "sales_last_chance_due",
        "condition": "За 24 часа до конца last_week: есть недостающие продукты, покупок в окне не было и предложение ещё действует",
        "recipient": "Клиент с недостающими продуктами",
        "purpose": "Один раз показать итоговый комплект; после срока больше не отправлять.",
    },
]

TRIGGER_BY_STEP = {item["step_key"]: item for item in TRIGGERS}


def editorial_help(step_key: str) -> dict | None:
    item = TRIGGER_BY_STEP.get(step_key)
    if not item:
        return None
    return {key: item[key] for key in ("trigger", "condition", "recipient", "purpose")}
