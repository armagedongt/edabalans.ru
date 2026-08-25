---
title: "Карта системы и Wiki"
summary: "Показывает дерево модулей, карточки, планы и канонические Markdown из Git."
document_status: current
implementation_status: implemented
---

# Карта системы и Wiki

Показывает дерево модулей, карточки, планы и канонические Markdown из Git.

## Функции

- искать модуль или документ и показывать человеческое описание;
- раскрывать автоматически собранные файлы, routes, таблицы и symbols;

## Граница

Нет отдельной Wiki-БД и ручного редактора карты; ошибка map не ломает documents view.

## Источники истины

`docs/modules.toml`, canonical Markdown, checked-in `docs/generated/*` и project-map API.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

