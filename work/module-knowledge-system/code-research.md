# Исследование кода: модульная карта и память проекта

Дата исследования: 25.08.2026  
Ветка исследования: `codex/module-knowledge-system`, commit `527ed9a`  
Контекст требований: `work/module-knowledge-system/user-spec.md`, `TASK_LIST.md`, `decisions.md`

## Краткая фактическая картина

В репозитории уже есть все базовые части будущей системы, но они не объединены одним
структурированным контрактом:

- `docs/README.md` вручную перечисляет крупные модули, основные файлы и таблицы;
- `docs/knowledge-base/` хранит канонические бизнес- и продуктовые документы;
- `docs/plans/` хранит планы, черновики и несколько уже реализованных checkpoint;
- `/admin/knowledge-base` читает Markdown непосредственно из Git и показывает дерево;
- `/control` является статическим каталогом административных инструментов;
- Telegram имеет собственный ручной реестр `MODULE_REGISTRY.md`, а
  `telegram-bot/service/app/graph.py` повторно задаёт список модулей в
  `GLOBAL_MODULES`;
- структурированного общего реестра, генератора инвентаря и CI-аудита пока нет.

Фактический production-контур содержит 45 Python-файлов backend-приложения и его
runtime-скриптов, 18 Python-файлов Telegram-сервиса, 61 статический frontend-файл,
24 Alembic migration, 173 FastAPI routes, 68 уникальных SQLAlchemy-таблиц, не менее
617 Python functions/methods и 159 именованных JavaScript function declarations.
Эти числа подтверждают, что ручной список каждой функции станет вторым быстро
устаревающим источником. Полнота достижима через AST-инвентарь и правила владения,
а не через ручное перечисление символов в Markdown.

## 1. Entry Points

### Общий backend

- `backend/app/main.py` — создаёт FastAPI application и подключает 11 routers.
  Ключевые сигнатуры: `health() -> dict[str, str]`,
  `ready(db: Session = Depends(get_db)) -> dict[str, str]`.
- `backend/app/crm_routes.py` — общая admin-сессия, `/control`, `/admin`, `/crm`,
  служебные страницы и CRM API. Ключевые сигнатуры:
  `control_portal(request: Request, credentials: HTTPBasicCredentials | None) -> Response`,
  `admin_index(...) -> FileResponse`, `admin_login(body: AdminLogin, response: Response)`.
  Файл содержит 37 route decorators и одновременно обслуживает несколько предметных
  областей, поэтому одного file-glob для точного владельца routes здесь недостаточно.
- `backend/app/knowledge_routes.py` — каталог и чтение Markdown Wiki.
  `knowledge_catalog(q: str, _: str) -> dict[str, object]` обслуживает
  `GET /admin/api/knowledge-base`; `knowledge_document(path: str, _: str)` обслуживает
  `GET /admin/api/knowledge-base/document`.
- `backend/app/static/admin-portal.html` — текущий `/control`; полностью статический
  список ссылок и пояснений, без API и реестра.
- `backend/app/static/knowledge-base.html`, `knowledge-base.js`,
  `knowledge-base.css` — текущий интерфейс Wiki. JS загружает каталог, строит дерево
  по filesystem path, выполняет поиск и рендерит выбранный HTML.

### Предметные backend routers

| Файл | Routes | Назначение |
|---|---:|---|
| `backend/app/access_routes.py` | 9 | права, account, legal acceptances, персональные ссылки |
| `backend/app/app_auth.py` | 2 | challenge/verify для Tilda-обёрнутых приложений |
| `backend/app/app_routes.py` | 22 | DQS, силовые, метаболизм, публичные assets/legal/intensive |
| `backend/app/content_routes.py` | 4 | административный каталог материалов |
| `backend/app/course_structure_routes.py` | 4 | список курсов, active structure, publish, restore |
| `backend/app/crm_routes.py` | 37 | admin shell, `/control`, CRM, служебные UI и API |
| `backend/app/intensive_routes.py` | 3 | публичный и административный контент четырёх дней |
| `backend/app/knowledge_routes.py` | 2 | Wiki catalog/document |
| `backend/app/main.py` | 2 | health/readiness |
| `backend/app/masterclass_routes.py` | 27 | course runtime, progress, questionnaires, offers, admin |
| `backend/app/pricing_routes.py` | 6 | pricing drafts/publish/public checkout |
| `backend/app/tilda_routes.py` | 1 | Tilda payments webhook |

`backend/app/masterclass_routes.py` и `crm_routes.py` являются доказанными
multi-module files: маршруты внутри одного файла принадлежат разным функциональным
модулям. Реестр должен поддерживать route-pattern или symbol override, а не только
владение всем файлом целиком.

### Telegram service

- `telegram-bot/service/app/main.py` — отдельное FastAPI application, webhook,
  scheduler lifecycle, `/bot`, 54 административных/public routes и 80 functions.
  Основные routes: `POST /telegram/webhook`, `GET /bot-api/map`, API цепочек,
  контактов, ссылок, UTM, сообщений и рассылок.
- `telegram-bot/service/app/graph.py` — строит исполняемое представление карты бота.
  Ключевые сигнатуры: `module_overview_graph(session)`,
  `module_graph(session, module_code)`, `sequence_graph(session, sequence_code)`.
  Список верхнеуровневых модулей повторно задан константой `GLOBAL_MODULES`.
- `telegram-bot/service/app/seed.py` — создаёт/обновляет системный контент, routes,
  sequence versions, steps и edges. Это исполняемый seed, а не документационный
  реестр.
- `telegram-bot/service/static/index.html`, `app.js`, `styles.css`,
  `module-map.css` — собственная специализированная админка бота.

### Инфраструктурные entry points

- `compose.yaml` — production services: Caddy, backend, Telegram, NocoDB, PostgreSQL.
- `infra/caddy/Caddyfile` — публичная маршрутизация четырёх доменов.
- `.github/workflows/production.yml` — единственный CI route на push в `main`:
  Docker Compose validation, build/test двух services, затем migration block.
- `infra/deploy/edabalans-deploy-poll` и `edabalans-deploy` — server-side poll и
  deploy после успешного GitHub check.
- `backend/Dockerfile` — production backend image содержит `backend/app`,
  `backend/scripts`, весь `docs/`, два корневых архитектурных документа и выбранный
  Masterclass content. Он **не содержит** `telegram-bot/`, `infra/`, `tools/` и
  полный Git tree, поэтому production API не может на лету сканировать весь репозиторий.

## 2. Data Layer

### Общая модель PostgreSQL

`backend/app/models.py` содержит 46 таблиц нескольких модулей в одном файле. Группы
по фактическому назначению:

- CRM/identity: `users`, `user_emails`, `user_phones`, `messenger_accounts`,
  `tags`, `user_tags`, `client_notes`, `user_merge_events`;
- продукты/цены/оплаты/доступы: `products`, `product_aliases`, `resources`,
  `product_access_rules`, `pricing_versions`, `price_entries`, `payments`,
  `user_accesses`, `personal_access_links`, `user_course_policies`,
  `user_legal_acceptances`, `attribution_events`, `messenger_link_tokens`;
- import/audit: `import_batches`, `legacy_import_records`, `admin_app_edits`;
- приложения: `dqs_states`, `strength_states`, `strength_exercises`,
  `metabolism_states`;
- Masterclass/runtime/offers: `masterclass_events`, `masterclass_day_progress`,
  `masterclass_step_progress`, `questionnaire_runs`, `questionnaire_answers`,
  `offer_stages`, `user_offers`, `offer_checkouts`, `masterclass_notifications`,
  `masterclass_test_profiles`, `managed_document_versions`;
- content catalog: `content_sources`, `content_items`, `content_item_versions`,
  `content_media`, `content_links`, `content_metric_snapshots`, `content_comments`,
  `content_import_runs`.

`telegram-bot/service/app/models.py` объявляет 22 Telegram-специфичных таблицы и
read-only/shared ORM mappings общих таблиц. Уникальные Telegram-owned таблицы:
`tg_bot_instances`, `tg_contacts`, `tg_content_items`, `tg_sequences`,
`tg_sequence_versions`, `tg_sequence_steps`, `tg_sequence_edges`, `tg_bot_routes`,
`tg_sequence_runs`, `tg_step_deliveries`, `tg_update_receipts`,
`tg_tracking_links`, `tg_tracking_link_aliases`, `tg_tracking_link_tags`,
`tg_utm_tag_rules`, `tg_tracking_sessions`, `tg_tracking_events`,
`tg_user_variables`, `tg_manual_messages`, `tg_broadcasts`,
`tg_broadcast_recipients`. Общие mappings `users`, `messenger_accounts`, `tags`,
`user_tags`, `attribution_events`, `masterclass_notifications`,
`messenger_link_tokens` не должны получать второго владельца только потому, что
Telegram их читает.

### Migration ownership

- `backend/migrations/versions/20260821_0001_baseline.py` — инфраструктурный baseline.
- `0002`–`0008`, `0011`–`0014`, `0019`–`0020`, `0022` — CRM, imports, payments,
  apps, content, access, pricing/legal.
- `0006`, `0009` — Telegram messaging/graph.
- `0010` — intensive restart guard.
- `0015`–`0018`, `0021`, `0023`, `0024` — Masterclass journey, links, progress,
  test profile, timezone, offer windows, course editor.

Файл migration принадлежит функциональному модулю, но сам модуль миграций остаётся
общей инфраструктурной системой исполнения. Audit должен извлекать
`op.create_table(...)` и связывать migration с владельцем таблицы.

### Другие канонические данные

- `content/masterclass/course/course.json` — seed структуры 21-дневного курса.
- `managed_document_versions` — после первого запуска и редакторской публикации
  хранит active version структуры; `course_structure_service.active_course_version()`
  возвращает текущую DB revision и использует `course.json` только как seed.
- `content/masterclass/source-current/` — канонические исходные тексты материалов.
- `backend/app/masterclass_offer_rules.py` — placement → stage и duration rules.
- `backend/app/masterclass_offer_catalog.py` — пользовательские названия,
  описания, состав и status продуктов offer cards.
- `offer_stages`/pricing tables — изменяемые цены и временные ступени.
- Telegram sequence/content/edges — runtime data в PostgreSQL, заполняются seed и
  изменяются специализированной админкой.

Здесь нужен явный тип владения: `seed`, `runtime source`, `business rule`,
`copy/catalog`, `consumer`. Простое поле `files` не объяснит, почему
`course.json` после публикации не является active runtime truth.

## 3. Текущая функциональная иерархия

Ниже — иерархия, подтверждаемая routers, models, docs и UI. Статус реализации
должен храниться отдельно от статуса документа.

```text
platform
├── platform-core
│   ├── crm-identity
│   ├── products-pricing
│   ├── payments-tilda
│   ├── access-legal
│   ├── application-auth
│   ├── managed-documents
│   └── content-catalog
├── products
│   ├── dqs
│   ├── strength
│   ├── metabolism-calories
│   ├── free-intensive
│   └── masterclass
│       ├── course-content-structure
│       ├── course-runtime-progress
│       ├── questionnaires
│       ├── offers-upsells
│       └── messenger-link-and-notifications
├── messaging
│   └── telegram
│       ├── start-attribution
│       ├── welcome-intensive
│       ├── prepurchase-nurture
│       ├── postpurchase-masterclass
│       ├── postmasterclass-nurture
│       ├── inbox-direct-support
│       ├── broadcasts
│       └── shared-engine-media-tracking
├── admin-surfaces
│   ├── control-portal
│   ├── project-knowledge-viewer
│   └── technical-nocodb
└── operations
    ├── database-and-migrations
    ├── deploy-and-ci
    ├── proxy-and-domains
    ├── backups-and-restore
    └── import-and-maintenance-tools
```

`admin-surfaces` — поверхности, а не владельцы бизнес-фактов. Например редактор
структуры принадлежит `course-content-structure`, а `/control` только ссылается на
него. Аналогично Telegram UI не владеет sequence logic отдельно от Telegram modules.

Planned-only Telegram modules `lottery` и `quiz` должны присутствовать с
`implementation_status = planned`, но не смешиваться с production-active модулями.
MAX, новый сайт и собственный ЛК остаются за пределами текущей реализации согласно
`AGENTS.md`, даже если упоминаются в общей архитектуре.

## 4. Existing Registries and Similar Features

### `docs/README.md`

Ручная карта уже задаёт правильный уровень: смысловой модуль → основные файлы →
таблицы → канонические документы. Она не умеет проверять полноту и содержит только
краткий указатель. Её следует генерировать или заменить ссылкой на generated map,
сохранив короткий human entry point.

### Telegram registry and graph

- `docs/knowledge-base/modules/telegram/MODULE_REGISTRY.md` — ручной реестр 10
  глобальных модулей с входами/выходами/status.
- `telegram-bot/service/app/graph.py:GLOBAL_MODULES` — второй список 9 модулей и
  status strings; `direct_support` отсутствует как отдельная строка, а описан через
  inbox/API. Тексты статусов отличаются от Markdown registry.
- `module_overview_graph()` вручную строит edges между несколькими модулями.
- `sequence_graph()` уже доказывает полезный принцип: подробные nodes/edges
  формируются из исполняемых DB sequence versions, а не копируются в Wiki.

Это ближайший аналог общего module registry. Общий реестр должен стать источником
верхнего уровня, а Telegram graph продолжит владеть подробным исполняемым графом.

### Masterclass ownership map

`docs/knowledge-base/modules/masterclass/README.md` уже распределяет факты между
`course.json`, `OFFERS_MODULE.md`, pricing DB, offer catalog, visual contract и
Telegram document. Это хороший шаблон module card: он ссылается на несколько
канонических источников с разными ролями вместо копирования правил.

### Current Wiki

`backend/app/knowledge_routes.grouped_paths()` формирует четыре фиксированные
группы: start, knowledge, working, plans. `document_meta()` извлекает title/status
regex-ами. `catalog()` при поиске читает полный текст каждого документа.
`allowed_documents()` создаёт allowlist только из известных directories, поэтому
path traversal закрыт. Markdown рендерится библиотекой `Markdown` с raw HTML,
осознанно доверяя private Git repository.

Wiki уже является view, а не второй БД. Её не требуется заменять отдельной системой
редактирования; требуется добавить module-tree/card view и перестать показывать
planned/current documents как одну неразличимую свалку.

### Plans already describing this feature

- `docs/plans/PROJECT_DOCUMENTATION_SYSTEM.md` — двухуровневая карта, module
  registry, automatic table/router/file audit, broken links и CI.
- `docs/plans/PROJECT_KNOWLEDGE_BASE_SPEC.md` — human knowledge, statuses,
  canonical sources и onboarding нового сотрудника.
- `docs/plans/ADMIN_UX_UNIFICATION_SPEC.md` — единая admin shell; большая часть уже
  реализована и отражена в `docs/ADMIN_ARCHITECTURE.md`, но plan всё ещё имеет
  статус `planned`.

Текущая user-spec объединяет первые два плана и превращает Wiki в представление
общего реестра. Старые plans после реализации должны получить `implemented`,
`superseded` или `archived`, а не оставаться конкурентными ТЗ.

## 5. Integration Points for Registry, Generator, Audit and UI

### Registry

Минимальный новый canonical artifact: `docs/modules.toml` (или эквивалентный JSON).
TOML читается стандартным `tomllib` Python 3.13 и не требует новой зависимости,
в отличие от YAML. Для каждого module нужны как минимум:

- stable `id`, `name`, `kind`, `parent`, human `summary`;
- `document_status` из закрытого набора `current|draft|planned|archived`;
- отдельный `implementation_status`;
- `canonical_docs`, `owner_notes`, `plans` как ссылки, не копии;
- ownership rules для file globs, routes, tables и exceptional symbols;
- `reads_from`, `writes_to`, `events_in`, `events_out`, `depends_on`;
- `admin_urls`, `public_urls`, `runtime_service`;
- canonical source roles (`seed`, `runtime`, `rules`, `copy`, `consumer`).

Владение должно быть одно. Потребителей можно перечислять многократно через связи.
Shared ORM mappings Telegram не становятся вторым table owner.

### Generator

Минимальная реализация без новых parsing libraries:

- новый `tools/module_inventory.py` использует `ast`, `pathlib`, `tomllib`, `json`,
  `fnmatch` из stdlib;
- Python AST извлекает files, module-level classes/functions/methods, FastAPI route
  decorators, `__tablename__` и `op.create_table`;
- JS/CSS/HTML/static сначала покрываются file ownership globs; именованные JS
  functions можно извлекать консервативным regex как информационные symbols без
  CI-block на анонимных callbacks;
- infrastructure/config/content/docs inventory строится по file categories, а не
  Python symbols;
- default owner назначается glob-правилом; route/table/symbol overrides решают
  multi-module files `crm_routes.py`, `masterclass_routes.py`, `models.py`,
  `telegram main.py`;
- generator формирует детерминированные
  `docs/generated/module-inventory.json` и `docs/generated/module-map.md`.

Полный static call graph не нужен для первого выпуска: он будет неточным из-за
FastAPI dependencies, SQLAlchemy и динамических DB graphs. Модульные зависимости
фиксируются явно, а imports/routes/table usage могут выводиться как диагностические
evidence, не как канонический смысл.

### Audit

Один CLI mode `--check` должен завершаться ошибкой при:

- production file без владельца;
- двух owner rules одного уровня без явного override;
- table без единственного владельца;
- route без владельца;
- отсутствующем module parent или dependency;
- несуществующем canonical doc/path/admin URL declaration;
- документе с неизвестным document status;
- несовпадении regenerated artifacts с Git.

Каждая функция выводится в inventory и наследует владельца файла. CI-block для
каждой функции не требует её ручной записи. Явный symbol override нужен только когда
один production file сознательно смешивает модули.

### Backend/API

Фактическая точка интеграции — `backend/app/knowledge_routes.py`:

- сохранить существующие document endpoints для совместимости;
- добавить `GET /admin/api/project-map` из checked-in generated JSON;
- добавить `GET /admin/api/project-map/modules/{module_id}` либо фильтрацию одного
  manifest response;
- использовать существующий `require_admin`;
- не запускать repository scan в request path.

Backend image уже копирует весь `docs/`, поэтому checked-in/generated artifacts
будут доступны runtime. Скрипт должен запускаться до Docker build и в CI, потому что
сам backend image не содержит Telegram/infra/tools source.

### UI

Минимально затрагиваются:

- `backend/app/static/admin-portal.html` — оставить launcher небольших инструментов,
  добавить понятные входы «Карта системы», «Как работать», «Планы»,
  «Технические документы»;
- `knowledge-base.html/js/css` — добавить top-level view modes и module tree/cards;
- `knowledge_routes.py` — API registry/inventory;
- `crm_routes.admin_asset()` — allowlist новых JS/CSS assets, если они выделены в
  отдельные файлы;
- `backend/tests/test_knowledge_base.py` и `test_crm_auth.py` — auth, catalog,
  module card, control links.

Tree строится по `parent`, а не по directory path. Межмодульные связи показываются
в card как списки/links; чистое дерево не может выразить cross-cutting dependencies.

### AGENTS and navigation

Точки интеграции постоянных правил:

- `AGENTS.md` — короткий обязательный router: прочитать `docs/README.md`, определить
  затронутый module id, открыть card/canonical docs, проверить registry/plans/drafts,
  обновить docs/inventory в том же изменении;
- `docs/README.md` — короткий human/AI entry point со ссылкой на module map и owner
  guide, без ручной таблицы каждой production entity;
- новый owner guide может жить в `docs/knowledge-base/OWNER_PROJECT_GUIDE.md` и
  отображаться Wiki; он не должен дублировать технические правила AGENTS;
- `docs/plans/README.md` — plans только по явному отложению владельца, с optional
  `module_id`.

## 6. Existing Tests

### Framework and runner

- Backend: `pytest 9.1.1`, FastAPI `TestClient`, SQLite in-memory для data tests и
  environment-configured PostgreSQL URL для import/runtime tests.
- Telegram: отдельный pytest suite, SQLite temp DB, fake Telegram clients и
  monkeypatch settings.
- CI собирает оба Docker images и запускает оба suites. На исследуемом commit:
  20 backend test files + 11 Telegram test files, 184 `test_*` functions.

Representative signatures:

- `backend/tests/test_knowledge_base.py::test_knowledge_base_lists_and_renders_documents()`
  проверяет четыре группы Wiki, известные paths и Markdown HTML.
- `backend/tests/test_knowledge_base.py::test_knowledge_base_searches_content_and_rejects_unknown_paths()`
  проверяет search и path traversal rejection.
- `telegram-bot/service/tests/test_api.py::test_webhook_start_is_idempotent_and_admin_can_inspect()`
  среди прочего проверяет `/bot-api/map`, module/sequence graph и transitions.
- `backend/tests/test_crm_auth.py::test_login_creates_shared_admin_session()`
  проверяет domain cookie и доступ к admin shell.

### Coverage gaps relevant to feature

- нет теста `/control` и его ссылок;
- нет machine-readable общего module registry;
- нет теста единственного владельца table/route/file;
- нет deterministic generation test;
- нет Markdown broken-link/status schema audit;
- нет проверки, что `MODULE_REGISTRY.md`, `GLOBAL_MODULES` и runtime sequences не
  расходятся;
- CI не запускает документационный audit.

Новая тестовая граница должна включать unit tests parser/ownership resolution,
integration tests project-map API/UI, fixture с orphan/overlap и CI regeneration
check. Browser test нужен только один smoke критического admin flow после UI change;
основная полнота проверяется дешевле API/DOM assertions.

## 7. Shared Utilities

- `backend/app/auth.py` — общая admin cookie/Basic auth для backend routes:
  `admin_session_token`, `admin_identity`, `require_admin`.
- `backend/app/managed_documents.py` — generic versioned document storage:
  seed, publish, active version, optimistic version check. Используется редактором
  курса, но не подходит для module registry: registry должен изменяться через Git,
  без runtime editor.
- `backend/app/knowledge_routes.py` — безопасный allowlist Markdown paths,
  metadata/search/render.
- `telegram-bot/service/app/graph.py` — готовый contract nodes/edges/issues для
  подробной Telegram visualisation.
- `backend/app/course_structure_service.py` — хороший пример разделения seed,
  active runtime version, normalization и validation.
- `backend/app/product_identity.py`, `pricing_service.py`,
  `masterclass_offer_catalog.py`, `masterclass_offer_rules.py` — доказанные
  canonical ownership seams внутри одной пользовательской функции offers.

## 8. Доказанный дрейф, дубли и бесхозные объекты

### Статусы документов

В `docs/` найден 71 Markdown document и 31 различная status string:

- только 20 документов имеют ровно `current`, 10 — `planned`, 6 — `draft`, 1 —
  `archived`;
- 5 документов не имеют `Статус:` вообще:
  `CRM_DATA_MODEL.md`, `OPERATIONS.md`, `TAG_RULES.md`, `TILDA_PAYMENTS.md`,
  `plans/COURSE_EDITOR_DEFERRED.md`;
- остальные смешивают document status и implementation/deployment state:
  `current_deployed_owner_test`, `runtime_deployed_launch_integration`,
  `approved_requirements / technical draft` и ещё десятки вариантов.

Текущий `knowledge_routes.STATUS_RE` принимает любую строку и UI показывает её без
валидации. Это непосредственная причина, по которой пользователь не может быстро
отличить актуальный смысл от состояния внедрения.

### Таблицы и код

- из 68 SQLAlchemy table names только `tg_bot_instances` нигде не назван в docs;
- `docs/README.md` владеет ручной таблицей modules/files/tables, но её полнота не
  проверяется;
- приблизительная проверка basename обнаружила 19 production Python-файлов, не
  названных ни в одном документе, включая `auth.py`, `app_auth.py`,
  `knowledge_routes.py`, `managed_documents.py`, несколько importers, Telegram
  `maintenance.py` и `schemas.py`. Это не доказывает, что каждый файл требует
  отдельного текста, но доказывает отсутствие полного ownership inventory;
- `models.py`, `crm_routes.py`, `masterclass_routes.py`, Telegram `main.py` смешивают
  несколько модулей, поэтому только directory ownership даст ложную карту.

### Telegram duplicate registry

`MODULE_REGISTRY.md`, `graph.py:GLOBAL_MODULES` и фактические DB sequences являются
тремя списками с разными деталями/status. `direct_support` есть в Markdown registry,
но не в `GLOBAL_MODULES`; status strings не совпадают. Это конкретный второй
источник перечня модулей.

### Course structure source drift

`docs/AI_DEVELOPMENT_WORKFLOW.md` говорит, что `course.json` «должен стать машинным
владельцем порядка», тогда как текущий `course_structure_service.py` после seed
использует active `managed_document_versions.payload` как runtime truth. Module card
должна явно отразить `course.json = seed`, PostgreSQL active revision = runtime
source, иначе новый чат может изменить не тот источник.

### Plans versus facts

`docs/plans/ADMIN_UX_UNIFICATION_SPEC.md` всё ещё `planned`, хотя
`docs/ADMIN_ARCHITECTURE.md` и код фиксируют реализованную общую shell/session.
В plans также находятся implemented/test-only checkpoint. Без отдельного
implementation field текущая Wiki показывает их как просто планы.

### `/control` route drift

`admin-portal.html` вручную содержит ссылку `href="/bot"`. На `APP_DOMAIN`
`Caddyfile` проксирует все paths в backend, а Telegram `/bot*` проксируется только
на `API_DOMAIN`. Следовательно относительная ссылка с
`https://app.edabalans.ru/control` по текущей конфигурации ведёт в backend route,
где `/bot` не зарегистрирован. Это нужно подтвердить production smoke, но код и
Caddy config уже показывают несогласованность. Автоматический registry URL audit
должен хотя бы проверять объявленные routes/domain targets, а `/control` не должен
поддерживать links вручную.

### Wiki information architecture

- hierarchy строится по директориям, а не по modules/parents;
- план, current business doc и operations doc визуально равноправны;
- search перечитывает все Markdown целиком на каждый запрос;
- raw HTML доверяется private repository; это соответствует текущему trust model,
  но любой будущий web editor/upload Markdown изменит security boundary;
- нет date/schema/canonical-owner validation и broken link check.

## 9. Constraints and Infrastructure

- Python versions: backend 3.13, Telegram 3.12. Общий generator, если запускается
  отдельным CI host Python, не должен зависеть от runtime import FastAPI/DB.
- FastAPI 0.141.1, SQLAlchemy 2.0.52, Markdown 3.8.2, pytest 9.1.1.
- YAML parser отсутствует. TOML/JSON дают минимальную реализацию без dependency.
- Backend production image не содержит весь repo; scan только в CI/local.
- PostgreSQL и backend не публикуются в обход Caddy; project-map API только под
  существующей admin session.
- В Git нельзя помещать secrets/PII/dumps. Registry хранит только safe locations и
  module relations.
- Push в `main` запускает tests; server poll deploys только успешный commit.
  Migration files блокируют автоматический production deploy.
- Generated artifacts должны быть deterministic и проверяться до Docker build,
  иначе production Wiki покажет старую карту.
- Новая feature не должна менять Tilda customer auth, Telegram runtime graph,
  production webhooks, NocoDB или пользовательские данные.
- `AGENTS.md` требует одновременного обновления canonical docs при изменении
  фактического поведения и запрещает второй источник логики.

## 10. External Libraries

Новая внешняя библиотека для минимального выпуска не требуется. Python stdlib
покрывает TOML/AST/glob/JSON/Markdown-link checks; существующие FastAPI и Markdown
покрывают API и render. Поэтому Context7 research не применялся.

Если позже потребуется точный JavaScript AST/call graph, это будет отдельное
расширение с новым dependency и собственным maintenance cost; текущий vanilla JS
можно покрыть file ownership и информационным списком named functions.

## 11. Минимальный безопасный implementation slice

Минимальный выпуск, который уже выполняет основное требование и не создаёт монстра:

1. `docs/modules.toml` с hierarchy, canonical links, ownership rules и связями.
2. `tools/module_inventory.py` со stdlib AST и детерминированными JSON/Markdown outputs.
3. Полная первоначальная классификация production directories, tables и routes;
   функции наследуют owner автоматически, исключения у multi-module files заданы
   точечно.
4. CI `--check`, блокирующий новые orphan/overlap/table/route и stale generated files.
5. Project-map API в `knowledge_routes.py` под `require_admin`.
6. Module tree/cards как основной режим существующей Wiki; current Markdown reader
   остаётся режимом «Документы».
7. `/control` получает generated tool sections и ссылки на карту, owner guide,
   plans и технические документы, но специализированные админки не объединяются.
8. `AGENTS.md`, `docs/README.md`, status schema и owner guide перенаправляют каждый
   новый чат по module id и canonical sources.
9. Telegram `GLOBAL_MODULES` заменяется projection общего registry либо проверяется
   против него; подробный DB graph остаётся источником исполняемой последовательности.
10. Старые documentation/knowledge plans получают финальный status и ссылку на
    реализованный module system.

Этот slice не требует ручного редактора, новой БД, NocoDB, полного static call graph,
перемещения production-кода или ручного перечисления 700+ symbols.
