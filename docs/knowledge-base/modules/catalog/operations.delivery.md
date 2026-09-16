---
title: "CI и доставка версии"
summary: "Проверяет commit и доставляет успешную main-ревизию на production-сервер."
document_status: current
implementation_status: implemented
---

# CI и доставка версии

Проверяет commit и доставляет успешную main-ревизию на production-сервер.

## Функции

- классифицировать влияние commit на данные, backend, Telegram, Caddy и Compose;
- строить, тестировать и перезапускать только затронутые сервисы;
- блокировать автоматический deploy при migration или провале checks;
- проверять readiness подключённых ботов после server deploy;
- забирать публичный `main` через зафиксированный HTTP/1.1, не завися от
  нестабильного HTTP/2 Git-транспорта текущей VM;

Production smoke-check проверяет единый `/favicon.ico` на всех управляемых
доменах. Пока временные сравнительные страницы ещё существуют, он также проверяет
`/favicon-tests/{black|blue|face}` и три их статических ресурса через настоящую
публичную границу блог-домена.

## Граница

Push, CI и deploy — разные технические этапы одного маршрута.
Наблюдение, incident и аварийное восстановление принадлежат `operations.health`:
[единый README](../../../runtime-health/README.md).

## Источники истины

GitHub workflow, deploy poll/script и `docs/OPERATIONS.md`.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

