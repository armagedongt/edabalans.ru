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
- локально перезапускать зависший Telegram-контейнер;
- независимо проверять production с Cloudflare и запускать согласованное аварийное восстановление;
- забирать публичный `main` через зафиксированный HTTP/1.1, не завися от
  нестабильного HTTP/2 Git-транспорта текущей VM;

Пока идёт выбор favicon, production smoke-check также проверяет три временные
`/favicon-tests/{black|blue|face}` страницы и три их статических ресурса через
настоящую публичную границу блог-домена.

## Граница

Push, CI и deploy — разные технические этапы одного маршрута.

## Источники истины

GitHub workflow, deploy poll/script, `infra/monitoring/` и `docs/OPERATIONS.md`.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

