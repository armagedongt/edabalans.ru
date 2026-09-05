---
title: "Старт и атрибуция Telegram"
summary: "Определяет источник входа, tracking link, first-touch и переход пользователя к следующему процессу."
document_status: current
implementation_status: implemented
---

# Старт и атрибуция Telegram

Определяет источник входа, tracking link, first-touch и переход пользователя к следующему процессу.

## Функции

- разбирать start payload и сохранить атрибуцию;
- связать invite, UTM и tracking events с контактом;
- поставлять публичную ссылку и CTA канала внешним поверхностям проекта;
- подставлять в утверждённые сообщения стабильные персональные ссылки на интенсив,
  Мастер-класс и публикацию канала; один непрозрачный код переиспользуется в разных
  маршрутах, а источник Telegram/MAX берётся из серверной записи, не из URL-параметра;
- фиксировать переходы через брендированные маршруты `/m/<код>` и
  `/p/<номер>/<код>` без открытого user id, email или названия мессенджера;

## Граница

Ссылка, UTM и tag являются компонентами этого модуля, а не отдельными глобальными модулями.

## Источники истины

`START_WELCOME_ROUTING.md`, `LEAD_ENTRY_OWNER_REQUIREMENTS.md`,
`LEAD_ENTRY_TECHNICAL_SPEC.md`, runtime tracking data и
`backend/app/telegram_public_cta.py` для публичного CTA и
`backend/app/personal_tracking_routes.py` для персональных исходящих маршрутов.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

