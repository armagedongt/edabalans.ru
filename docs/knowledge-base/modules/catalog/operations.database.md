---
title: "PostgreSQL и migrations"
summary: "Управляет схемой общей базы и последовательным применением версионированных migrations."
document_status: current
implementation_status: implemented
---

# PostgreSQL и migrations

Управляет схемой общей базы и последовательным применением версионированных migrations.

## Функции

- поддерживать закрытый PostgreSQL и readiness;
- создавать и безопасно выпускать migration при изменении схемы;

## Граница

Таблица принадлежит функциональному модулю; этот модуль владеет механизмом migration.

## Источники истины

Alembic migrations, PostgreSQL config и `docs/OPERATIONS.md`.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

