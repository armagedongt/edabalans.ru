---
title: "Разовые Telegram-рассылки"
summary: "Создаёт, проверяет, планирует и запускает сегментированные разовые отправки."
document_status: current
implementation_status: implemented
---

# Разовые Telegram-рассылки

Создаёт, проверяет, планирует и запускает сегментированные разовые отправки.

## Функции

- дать preview и owner-test до запуска;
- вести получателей, ошибки, retry и статистику;

## Граница

Рассылка — runtime-операция, а не новый commit или модуль на каждую кампанию.

## Источники истины

`INBOX_AND_BROADCASTS.md`, `tg_broadcasts`, `tg_broadcast_recipients`.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

