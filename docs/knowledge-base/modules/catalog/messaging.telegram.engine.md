---
title: "Движок, медиа и tracking Telegram"
summary: "Исполняет версии графов, планирует шаги, доставляет Telegram media и журналирует события."
document_status: current
implementation_status: implemented
---

# Движок, медиа и tracking Telegram

Исполняет версии графов, планирует шаги, доставляет Telegram media и журналирует события.

## Функции

- идемпотентно принимать updates и исполнять due steps;
- переиспользовать media file_id и фиксировать delivery/tracking;

## Граница

Системный engine не владеет продуктовым смыслом отдельных цепочек.

## Источники истины

Telegram service code, runtime sequences/steps/edges, deliveries and update receipts.

Требования к цели, ТЗ писателю, редакционному статусу, Telegram HTML-редактированию и
безопасной публикации каждого контентного слота описаны в
`../telegram/MESSAGE_CONTENT_AUTHORING.md`. Подтверждённые владельцем сообщения
массовый модуль-писатель пропускает.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

