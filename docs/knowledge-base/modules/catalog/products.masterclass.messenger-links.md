---
title: "Связь участника мастер-класса с мессенджером"
summary: "Создаёт короткоживущую безопасную ссылку для привязки Telegram к участнику курса."
document_status: current
implementation_status: implemented
---

# Связь участника мастер-класса с мессенджером

Создаёт короткоживущую безопасную ссылку для привязки Telegram к участнику курса.

## Функции

- проверять доступ к мастер-классу до создания ссылки;
- одноразово связывать messenger account с внутренним user_id;

## Граница

Не помещает email, user_id или цены в ссылку и не владеет Telegram welcome.

## Источники истины

`messenger_link_tokens`, Masterclass API и Telegram consumer.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

