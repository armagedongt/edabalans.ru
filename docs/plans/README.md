# Очередь будущих изменений

Статус: `current`  
Назначение: единое место для всего, что владелец решил реализовать позже.

## Как пользоваться

- Небольшое пожелание добавляется в `QUICK_NOTES.md` одной проверяемой записью.
- Крупный модуль или готовое ТЗ получает отдельный файл в этой папке.
- Запись содержит область, желаемый результат, статус и источник решения.
- `planned` не означает, что изменение уже работает.
- При начале реализации задача переносится в рабочий план/issue, а после завершения
  отмечается `implemented` со ссылкой на коммит и канонический документ.
- Существующие специализированные backlog не дублируются: этот индекс ссылается на них.

## Крупные запланированные работы

| Тема | Файл | Статус |
|---|---|---|
| Полноценная база знаний бизнеса | `PROJECT_KNOWLEDGE_BASE_SPEC.md` | `planned` |
| Полная система документации файлов и таблиц | `PROJECT_DOCUMENTATION_SYSTEM.md` | `planned` |
| Каталог авторских материалов: Pikabu, затем Telegram и блог | `CONTENT_CATALOG_SPEC.md` | `draft` |
| Контрольный замер пяти постов Pikabu | `PIKABU_5_POST_BENCHMARK.md` | `draft` |
| Импорт Telegram-канала в каталог материалов | `TELEGRAM_CONTENT_CATALOG_SPEC.md` | `draft` |
| Следующие версии Telegram-бота | `TELEGRAM_NEXT_VERSIONS.md` | `planned` |
| Ссылки, корневой `/start`, welcome и первая версия интенсива | `TELEGRAM_START_LINKS_SPEC.md` | `approved_draft` |
| Атрибуция пути «ссылка → канал → бот» | `TELEGRAM_CHANNEL_ATTRIBUTION_SPEC.md` | `approved_draft` |
| Переходы с канала на сайт и связь с покупкой | `WEBSITE_CLICK_PURCHASE_ATTRIBUTION.md` | `planned` |
| Продукты и офферы | `PRODUCTS_AND_OFFERS.md` | `planned` |
| Серверное приложение мастер-класса в Tilda Members Area | `MASTERCLASS_WEB_APP_SPEC.md` | `approved_requirements / technical draft` |
| Точка возврата по сайту Мастер-класса | `MASTERCLASS_SITE_NEXT_STEPS.md` | `current_status_with_planned_followups` |
| Упрощение доступов после финальной перестройки групп Tilda | `ACCESS_DATA_SIMPLIFICATION.md` | `planned` |
| Одноразовый перенос Tilda Members Area | `TILDA_MEMBERS_SYNC.md` | `archived`; повторной синхронизации не будет |
| Полный аудит дисклеймера и обработки данных | `LEGAL_COMPLIANCE_AUDIT.md` | `planned` |
| Долгосрочное развитие платформы | `PLATFORM_LONG_TERM.md` | `planned` |
| Аудит найденных планов по репозиторию | `PLAN_SOURCES_AUDIT.md` | `current` |

## Существующие очереди в других разделах

- `../APPLICATION_BACKLOG.md` — отложенные изменения DQS, силовых, метаболизма,
  доступов и общего клиентского интерфейса.
- `../../legacy/google/dqs/PENDING_CLIENT_CHANGES.md` — замечания, которые относятся
  именно к текущему переносу legacy DQS и не должны потеряться в общем backlog.
- `../../telegram-bot/docs/FLOW_MAP.md` — фактическая карта и локальное требование к
  безопасной публикации версий; незавершённая часть перенесена в Telegram backlog.
- `../../telegram-bot/docs/CRM_INTEGRATION_CONTRACT.md` — частично реализованный
  целевой контракт Telegram ↔ CRM; оставшиеся пункты перенесены в Telegram backlog.

Полный результат поиска и классификация исторических документов:
`PLAN_SOURCES_AUDIT.md`.

## Правило для следующих ИИ-чатов

Если владелец говорит «потом», «не сейчас», «было бы здорово» или прямо просит
запомнить будущую возможность, сначала определить: это решение или просто идея.
Решение записать как `planned`; непроверенную идею — как `idea`. Не реализовывать её
без отдельного поручения.
