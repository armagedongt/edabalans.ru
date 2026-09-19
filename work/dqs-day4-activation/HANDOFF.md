---
created: 2026-09-19
status: current
module_id: products.dqs
---

# Handoff: DQS day-4 activation и единые пояснения доступов

## Что уже зафиксировано

- Канон DQS: `docs/knowledge-base/modules/dqs/README.md`.
- Общая модель прав и доступности: `docs/knowledge-base/ACCESS_RULES.md`.
- Общая оболочка приложений: `docs/APPLICATION_PLATFORM.md`.
- Полное ТЗ первого migration slice: `work/dqs-day4-activation/user-spec.md`.
- Принятые решения и причины: `work/dqs-day4-activation/decisions.md`.
- Исследование текущего кода: `work/dqs-day4-activation/code-research.md`.

Документы описывают целевое поведение. Сам DQS cutover, общий resolver,
межсервисный endpoint и Telegram-отправка ещё не реализованы и не выпущены.

## Граница первого внедрения

Первый slice реализует общий application-access resolver и подключает к нему
только DQS. Он не меняет правила strength, recipes и metabolism. Для каждого из
них сначала нужна отдельная подтверждённая policy entry:

- какой entitlement означает покупку;
- какое событие или этап делает приложение доступным;
- нужен ли reveal;
- как влияют maintenance и release-state;
- куда ведёт допустимое следующее действие.

Текущий код расходится: ЛК вычисляет часть состояний в `account_applications`, а
Telegram отдельно читает `user_accesses` и `masterclass_events`. Это основание для
миграции, но не доказательство продуктовых правил остальных приложений.

## Готовое поручение следующему техническому чату

> Продолжи модуль `products.dqs` по `work/dqs-day4-activation/user-spec.md`.
> Сначала прочитай `docs/README.md`, `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`,
> `docs/knowledge-base/modules/dqs/README.md`,
> `docs/knowledge-base/ACCESS_RULES.md`, `docs/APPLICATION_PLATFORM.md`,
> `work/dqs-day4-activation/decisions.md` и `code-research.md`.
> Реализуй первый migration slice полностью: единый application-access resolver,
> policy entry DQS, gate прямого `/dqs`, payload ЛК, материал `day-04-dqs`,
> идемпотентный reveal, одну Telegram notification, закрытую service-auth границу
> bot → backend, backfill прежних пользователей и тесты из ТЗ. Не меняй
> production-доступность strength, recipes или metabolism. Их будущие policy
> entries сначала сверь с владельцем и каноническими модулями. Не создавай второй
> реестр прав, отдельную DQS-авторизацию или копии пользовательских текстов во
> frontend. До production-отправки реальным людям покажи Сергею финальную редакцию
> существующего Telegram content slot и запроси подтверждение массового действия.

## Что передать общему чату приложений

Общему чату приложений передаётся не DQS-реализация, а следующий отдельный этап:
составить и согласовать policy matrix для strength, recipes и metabolism, затем
подключать их к уже работающему resolver-у по одному с регрессионными тестами.
Пока matrix не утверждена, текущие правила этих приложений сохраняются.
