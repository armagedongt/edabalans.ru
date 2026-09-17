# Навигатор по документации edabalans.ru

Статус: `current`  
Проверено: 12.09.2026
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
| Как устроены контент, курсы, страницы, дизайн и публикация | `knowledge-base/EDITORIAL_PRODUCT_SYSTEM.md` | канон редакционно-продуктового процесса |
| Что существует и как связано | `modules.toml`, `generated/module-map.md` | registry; Markdown — производная |
| Что делает конкретный модуль | `knowledge-base/modules/catalog/<module_id>.md` | карточка модуля |
| Полные правила бизнеса/продукта | `knowledge-base/README.md` и ссылки из карточки | канонический Markdown |
| Что явно отложено | `plans/README.md` | plan-файл с module id |
| Что сейчас исследуется/реализуется | `../work/` | временные feature artifacts |
| Production, backup, restore, deploy | `OPERATIONS.md` | операционный документ и infra config |
| Доступность, Telegram/MAX, аварии, DNS, уведомления и restart | `runtime-health/README.md` | модуль `operations.health` |
| Перенос публичного домена | `DOMAIN_CUTOVER_RUNBOOK.md` | повторяемый cutover, ручные действия и приёмка |
| Как выбирать глубину разработки и tests | `AI_DEVELOPMENT_WORKFLOW.md` | рабочий процесс |
| Как создавать, менять и удалять модули | `knowledge-base/MODULE_DEVELOPMENT_STANDARD.md` | общий стандарт модулей |
| Как разводить параллельные чаты | `CHAT_WORKSTREAMS.md` | правила потоков |
| Полный технический состав | `generated/module-inventory.json` | автоматически извлечённый artifact |

## Тематические канонические документы

Генерация изображений всех потоков: [единый центр «Художник»](../content/design-workflow/image-generation-protocol.md)
(`platform.web_design`): handoff, шаблоны и маршрут к существующим каталогам.

| Тема | Документ |
|---|---|
| CRM, единый клиент и импорт | `CRM_CORE_DESIGN.md`, `CRM_DATA_MODEL.md` |
| Клиентские приложения DQS/силовые/метаболизм | `APPLICATION_PLATFORM.md` |
| Создание и загрузка приложений курсов | `knowledge-base/COURSE_APPLICATION_STANDARD.md` |
| Платежи и доступы | `TILDA_PAYMENTS.md`, `ROBOKASSA_PAYMENTS.md`, `knowledge-base/ACCESS_RULES.md` |
| Цены | `knowledge-base/PRICING_CATALOG.md` |
| Мастер-класс | `knowledge-base/modules/masterclass/README.md` |
| Telegram — фактическая логика | `TELEGRAM_BOT_CURRENT_LOGIC.md` |
| Telegram — дополнительные правила модулей | `knowledge-base/modules/telegram/MODULE_DEVELOPMENT_STANDARD.md` |
| Каталог материалов | `CONTENT_CATALOG.md` |
| Приём и локальная расшифровка любых голосовых, аудио и видео | [Голосовой диспетчер](knowledge-base/VOICE_TRANSCRIPTION_WORKFLOW.md), модуль `platform.content` |
| Блог: статьи, SEO, аналитика и публикация | `knowledge-base/modules/blog/README.md`, модуль `platform.blog` |
| Писарь: единый вход, правила, источники, прошлые разборы и маршруты публикации | [Писарь](../content/author-voice/README.md); рабочая инструкция — `../content/author-voice/skill/edabalans-writer/SKILL.md` |
| Использование нашего видеоплеера: возможности, настройки и места подключения | [Использование нашего видеоплеера](../backend/app/static/video-player-development/README.md) |
| Единая библиотека, Библиотекарь и MCP | `KNOWLEDGE_LIBRARY.md` |
| Редакционная и продуктовая система | `knowledge-base/EDITORIAL_PRODUCT_SYSTEM.md` |
| Дизайн, адаптив и компоненты главной | `knowledge-base/HOMEPAGE_DESIGN_PASSPORT.md` |
| Бесплатный интенсив | `INTENSIVE_PAGES.md` |
| Административные инструменты | `ADMIN_ARCHITECTURE.md` |
| Теги | `TAG_RULES.md` |
| Legacy Google | `../legacy/google/README.md` |

## Предложение, продажа и приложение — разные владельцы

Оффер не является целиком навыком Писаря: продуктовый/маркетинговый brief задаёт
предложение, Писарь формулирует текст, коммерция поставляет действующие цены и права.
Юридические документы имеют отдельный маршрут через
`knowledge-base/LEGAL_DOCUMENTS.md`, а не обычную продажную редактуру.
DQS, силовые тренировки и метаболизм остаются отдельными модулями со своими
карточками; общий `APPLICATION_PLATFORM.md` не заменяет их правила.

Точная таблица маршрутов и обязательный договор завершения —
[`Общий стандарт модулей`](knowledge-base/MODULE_DEVELOPMENT_STANDARD.md).
Расположение кода в `backend/`, `telegram-bot/` или `tools/` не образует ещё один
реестр: owner и связи берутся из `modules.toml`. Для человека и чата используются
одни и те же карточки и первоисточники.

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
