# Навигатор по документации edabalans.ru

Статус: `current`  
Проверено: 27.08.2026
Назначение: единая точка входа для владельца, сотрудника и нового ИИ-чата.

## Базовый минимум

1. `../AGENTS.md` — обязательный маршрут и ограничения работы.
2. `../PROJECT_CONTEXT.md` — цель платформы и достигнутое состояние.
3. `../ARCHITECTURE.md` — устойчивые технические решения.
4. `generated/module-map.md` — автоматически собранное дерево модулей.
5. Карточка затронутого модуля из `knowledge-base/modules/catalog/`.

Новый чат не должен читать подряд всю документацию. После базового минимума он
определяет `module_id` и открывает только карточку, её канонические источники,
связанные модули, активную работу и явные планы.

## Главные разделы

| Нужно понять | Где смотреть | Владелец факта |
|---|---|---|
| Как Сергею ставить задачи и что значат термины | `knowledge-base/OWNER_PROJECT_GUIDE.md` | человекочитаемая памятка |
| Что существует и как связано | `modules.toml`, `generated/module-map.md` | registry; Markdown — производная |
| Что делает конкретный модуль | `knowledge-base/modules/catalog/<module_id>.md` | карточка модуля |
| Полные правила бизнеса/продукта | `knowledge-base/README.md` и ссылки из карточки | канонический Markdown |
| Что явно отложено | `plans/README.md` | plan-файл с module id |
| Что сейчас исследуется/реализуется | `../work/` | временные feature artifacts |
| Production, backup, restore, deploy | `OPERATIONS.md` | операционный документ и infra config |
| Как выбирать глубину разработки и tests | `AI_DEVELOPMENT_WORKFLOW.md` | рабочий процесс |
| Как создавать, менять и удалять модули | `knowledge-base/MODULE_DEVELOPMENT_STANDARD.md` | общий стандарт модулей |
| Как разводить параллельные чаты | `CHAT_WORKSTREAMS.md` | правила потоков |
| Полный технический состав | `generated/module-inventory.json` | автоматически извлечённый artifact |

## Тематические канонические документы

| Тема | Документ |
|---|---|
| CRM, единый клиент и импорт | `CRM_CORE_DESIGN.md`, `CRM_DATA_MODEL.md` |
| Клиентские приложения DQS/силовые/метаболизм | `APPLICATION_PLATFORM.md` |
| Платежи и доступы | `TILDA_PAYMENTS.md`, `knowledge-base/ACCESS_RULES.md` |
| Цены | `knowledge-base/PRICING_CATALOG.md` |
| Мастер-класс | `knowledge-base/modules/masterclass/README.md` |
| Telegram — фактическая логика | `TELEGRAM_BOT_CURRENT_LOGIC.md` |
| Telegram — дополнительные правила модулей | `knowledge-base/modules/telegram/MODULE_DEVELOPMENT_STANDARD.md` |
| Каталог материалов | `CONTENT_CATALOG.md` |
| Бесплатный интенсив | `INTENSIVE_PAGES.md` |
| Административные инструменты | `ADMIN_ARCHITECTURE.md` |
| Теги | `TAG_RULES.md` |
| Legacy Google | `../legacy/google/README.md` |

Не поддерживать здесь ручную таблицу всех файлов, routes, symbols и таблиц: её
заменяет generator. При расхождении сначала установить фактический источник истины
и исправить registry/card/канонический документ в одном изменении.

## Два независимых статуса

`document_status` отвечает только на вопрос «можно ли доверять этому тексту»:

- `current` — актуальный утверждённый документ;
- `draft` — содержание ещё уточняется;
- `planned` — документ описывает будущее;
- `archived` — исторический контекст.

`implementation_status` отвечает на вопрос «есть ли функция в этой Git-ревизии»:

- `implemented`;
- `in_development`;
- `planned`;
- `archived`.

Это не ручной production-флаг. Production показывает карту из реально запущенной
ревизии; факт выпуска проверяется по CI и server revision.
