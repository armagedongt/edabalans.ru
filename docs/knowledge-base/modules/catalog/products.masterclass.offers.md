---
title: "Дополнительные продажи мастер-класса"
summary: "Рассчитывает допустимые предложения, окна, ступени цены, таймеры и последствия покупки."
document_status: current
implementation_status: implemented
---

# Дополнительные продажи мастер-класса

Рассчитывает допустимые предложения, окна, ступени цены, таймеры и последствия покупки.

## Функции

- выбирать предложение по placement и состоянию покупок;
- повторно проверять цену и доступность перед checkout;

## Граница

Позиция блока приходит из active course structure; Telegram не пересчитывает условия.

## Источники истины

`OFFERS_MODULE.md`, `masterclass_offer_rules.py`, `masterclass_offer_catalog.py`, pricing/offer runtime tables.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

