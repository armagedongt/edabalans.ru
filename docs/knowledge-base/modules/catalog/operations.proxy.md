---
title: "Домены, Caddy и сеть"
summary: "Завершает HTTPS и направляет публичные пути к разрешённым внутренним сервисам."
document_status: current
implementation_status: implemented
---

# Домены, Caddy и сеть

Завершает HTTPS и направляет публичные пути к разрешённым внутренним сервисам.

## Функции

- маршрутизировать app/api/data домены через Caddy;
- не публиковать PostgreSQL и внутренние порты напрямую;

## Граница

Не владеет авторизацией приложений или содержанием страниц.

## Источники истины

Caddyfile, compose/network config и `docs/OPERATIONS.md`.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

