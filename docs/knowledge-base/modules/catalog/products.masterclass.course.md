---
title: "Структура и материалы мастер-класса"
summary: "Определяет содержание, дни, шаги и редакторские версии структуры 21-дневного курса."
document_status: current
implementation_status: implemented
---

# Структура и материалы мастер-класса

Определяет содержание, дни, шаги и редакторские версии структуры 21-дневного курса.

## Функции

- публиковать и восстанавливать версию структуры курса;
- показывать единый порядок дней и материалов во всех представлениях;

## Граница

`course.json` не является active runtime после появления DB revision.

## Источники истины

Active `managed_document_versions` — runtime truth; `content/masterclass/course/course.json` — seed; контракт — `COURSE_STRUCTURE_CONTRACT.md`.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

