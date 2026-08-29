# Code research: два связанных курса — «Калорийный» и «С дивана до тренировок»

Дата исследования: 2026-08-28  
Статус: `draft`  
Область: фактическая архитектура репозитория перед проектированием двух курсов. Код и канонические документы в рамках исследования не изменялись.

## 1. Entry Points

### Общая оболочка приложений и ЛК

- `backend/app/static/embed.js` — постоянный Tilda-загрузчик. Ищет узлы `data-edabalans-app`, получает email участника и загружает HTML-фрагмент с `app.edabalans.ru`. Карта `roots` уже содержит `strength`, `metabolism` и `masterclass-course`.
  - `detectTildaMemberEmail()` получает `tma__getProfileObjFromLS().login` для защищённых новых приложений.
  - `load(mount)` загружает `/apps/{app_code}.html`, устанавливает `window.EdabalansAppContext` и исполняет скрипты фрагмента.
  - В `PROTECTED_APPS` входят новый ЛК и Мастер-класс, но не входят legacy-фрагменты `strength` и `metabolism`; для них сохраняется переходная логика определения/запоминания email.
- `backend/app/app_routes.py` — выдаёт публичные фрагменты и содержит legacy API DQS, силовых и метаболизма.
  - `app_fragment(app_code: str) -> FileResponse` обслуживает `/apps/{app_code}.html`.
  - `strength_legacy(request: Request, db: Session) -> JSONResponse` обслуживает `GET/POST /api/apps/strength` и действия `openUser`, `getWorkout`, `saveSession`, `saveExerciseSettings`, `getStats`.
  - `metabolism_get(email: str, db: Session) -> dict` и `metabolism_put(request: Request, db: Session) -> JSONResponse` обслуживают `GET/PUT /api/apps/metabolism`.
  - `admin_metabolism_get(...)` и `admin_metabolism_put(...)` дают управляемый доступ владельцу к состоянию калькулятора.
- `backend/app/access_routes.py` — общий экран ЛК. В `account_payload(...)` сопоставляет каталожные коды `calories` и `training` с account-кодами `calories` и `strength`, затем рассчитывает `owned`, `ready`, `state` и ссылку на приложение.

### Каталог продукта и доступ

- `backend/app/product_catalog_service.py` — публичные названия, дескрипшны и внутренний маркетинговый контекст продуктов.
  - `product_public(db: Session, code: str) -> dict` читает активный `product-catalog/core` и добавляет техническую связь из `PRODUCT_CONNECTIONS`.
  - Для `calories`: ресурс `ACCESS_CALORIES`, `app=None`, `ready=False`.
  - Для `training`: ресурс `ACCESS_STRENGTH`, `app=None`, `ready=False`.
  - `PRODUCT_CATALOG_SEED` и `MARKETING_CONTEXTS` содержат стартовую смысловую рамку; после первой публикации runtime-источником является активная версия `managed_document_versions`, а не seed в коде.
- `backend/app/masterclass_offer_catalog.py` — действующий серверный контракт карточек допродажи. Содержит оффер-коды `calories` и `training`, их ресурс, статус и presentation-блоки; итоговые публичные поля при работе каталога пересобираются из `product_public(...)`.
- `backend/app/access_service.py` — выдача ресурсов и режим отложенного открытия.
  - `grant_resources(..., resource_codes: list[str], unlock_modes: dict[str, str] | None = None) -> list[str]` создаёт `user_accesses` и при необходимости `user_course_policies`.
  - `resources_for_codes(...)` требует существующего активного ресурса.
- `backend/app/app_service.py` — проверка пользователя legacy-приложений.
  - `resolve_user_for_resource(db, email, resource_code, require_legal_acceptance=True) -> User` проверяет активного пользователя, review gate, общие юридические подтверждения и `user_accesses`.

### Существующий редактор и runtime курса

- `backend/app/course_structure_routes.py` — API редактора структуры, внешне выглядит мультикурсовым (`/admin/api/courses/{course_code}/...`), но `checked_course()` принимает только `masterclass-21`.
  - `admin_courses(...)`, `admin_course_structure(...)`, `admin_save_course_structure(...)`, `admin_restore_course_structure(...)`.
- `backend/app/course_structure_service.py` — структура текущего Мастер-класса.
  - Константы `DOCUMENT_KEY="masterclass-21"`, `COURSE_CONTENT_ROOT=content/masterclass`, `COURSE_MANIFEST_PATH=.../course.json` жёстко привязывают сервис к одному курсу.
  - `course_context(db: Session) -> CourseContext` собирает активную структуру, дни, задания, специальные приложения, офферы и whitelist fallback-файлов.
  - `publish_course_structure(...)` публикует новую immutable-версию в `managed_document_versions`.
- `backend/app/course_material_routes.py` и `backend/app/course_material_service.py` — независимое версионирование обычных статей курса.
  - `checked_course()` также принимает только `masterclass-21`.
  - `SOURCE_ACCOUNT_KEY="masterclass-course-materials"` и `PARSER_VERSION="masterclass-material-v1"` жёстко задают источник Мастер-класса.
  - `publish_material(...)`, `restore_material(...)`, `published_materials(...)` работают по стабильному `step.id`.
- `backend/app/masterclass_routes.py` — фактический пользовательский runtime одного 21-дневного курса.
  - `course_state`, `course_manifest`, `course_materials`, `course_open_day`, `course_complete_step`, `course_open_task`, `course_update_check` расположены под `/api/masterclass`.
  - Порядок, суточные открытия, прогресс, события и Telegram/outbox-сигналы привязаны к `masterclass_*` таблицам и типам событий.

## 2. Data Layer

### Продукты, ресурсы и отложенное открытие

- `backend/app/models.py: Product` — стабильный технический продукт: `code`, `name`, `status`.
- `backend/app/models.py: Resource` — выдаваемая возможность: `code`, `name`, `status`.
- `backend/app/models.py: ProductAccessRule` — связь продукта с ресурсом и интервал действия.
- `backend/app/models.py: UserAccess` — фактическое право пользователя на ресурс, источник, оплата, даты выдачи/истечения/отзыва.
- `backend/app/models.py: UserCoursePolicy` — политика прохождения конкретного ресурса: `paced` либо `fully_unlocked`; уникальна по `(user_id, resource_id)`.
- `backend/app/importers/sync_app_accesses.py` — legacy-сопоставление уже зафиксировано так:
  - `CALORIES_COURSE -> metabolism`, `ACCESS_CALORIES -> metabolism`;
  - `TRAINING_COURSE -> strength`, `ACCESS_STRENGTH -> strength`.
  Это историческая миграция прав в ресурсы приложений, а не модель содержания курса.

### Калории и метаболизм

- `backend/app/models.py: MetabolismState` — одна строка на пользователя: `variants` JSON, `active_variant`, `formula_version` (`metabolism_v3`), optimistic-lock `version`, `source`.
- `backend/app/static/apps/metabolism.html` — сама формула сейчас находится во frontend-функции `calculate(v)`:
  - BMR по полу, возрасту, росту и весу;
  - корректировка по проценту жира;
  - термический эффект пищи и добавка белка;
  - шаги через длину шага, дистанцию и коэффициент активных шагов;
  - недельные тренировочные калории делятся на семь;
  - баланс, дефицит, целевое потребление, прогноз скорости и потери веса.
- `backend/app/app_routes.py: apply_metabolism_update(...)` валидирует только форму JSON и версию состояния; сервер не пересчитывает и не валидирует результат формулы.

### Силовые тренировки

- `backend/app/models.py: StrengthState` — одна строка на пользователя: JSON `workout_types`, `hidden_exercises`, `workouts`, optimistic-lock `version`, `source`.
- `backend/app/models.py: StrengthExercise` — общий справочник: `code`, `name`, `active`, `sort_order`, `metadata_json`.
- `backend/app/app_routes.py: strength_payload(...)` разворачивает JSON пользователя в типы тренировок, каталог упражнений, занятия, упражнения и подходы.
- `backend/app/static/apps/strength.html` хранит plan/fact, вес, повторы и RPE и показывает динамику расчётного 8RM.
- Формула 8RM реализована и во frontend `calculate8RM(weight, reps, rpe)`, и на сервере в ветке `getStats` функции `strength_legacy(...)`.

### Структура, тексты и прогресс курса

- `backend/app/models.py: ManagedDocumentVersion` — immutable-версии JSON-документов, один active на `(document_type, document_key)`. Сейчас хранит `product-catalog/core` и `course-structure/masterclass-21`.
- `backend/app/models.py: ContentSource`, `ContentItem`, `ContentItemVersion` — версионный контентный слой. Материал курса связывается по `ContentSource.account_key` и стабильному `ContentItem.external_id == step.id`.
- `backend/app/models.py: ContentMedia`, `ContentLink`, `ContentMetricSnapshot`, `ContentComment` — медиа, ссылки, метрики и редакционные комментарии контентного каталога.
- `masterclass_day_progress`, `masterclass_step_progress`, `masterclass_events`, `masterclass_notifications` — прогресс и исходящие события реализованы только для Мастер-класса; общего `course_progress` по `course_code` пока нет.

## 3. Similar Features

### Мастер-класс как эталон оболочки

- `docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md` объявлен стабильным структурным контрактом всех курсов: курс → дни → материалы → задания, стабильные ID, вычисляемое оглавление и независимые версии статей.
- `docs/knowledge-base/modules/masterclass/COURSE_DESIGN_SYSTEM.md` фиксирует структуру и визуальную систему первого дня как эталон всех курсов.
- `docs/knowledge-base/modules/masterclass/COURSE_RUNTIME.md` задаёт серверный прогресс, события и правила открытия именно Мастер-класса.
- Повторно использовать можно контракт данных, sanitization статей, immutable revisions, стабильные `step.id`, общий renderer и визуальную систему. Текущий runtime нельзя подключить к двум новым курсам только новым manifest: сервисы, routes, таблицы и event names жёстко masterclass-specific.

### Каталог материалов автора

- `backend/app/content_service.py` импортирует и нормализует Pikabu и Telegram в общий контентный каталог.
  - `import_telegram_items(...)`, `import_pikabu_items(...)`, `list_content_items(...)`, `get_content_item(...)`.
- `backend/app/content_routes.py` даёт защищённый просмотр `/admin/content/...`.
- `platform.content` владеет голосом, писателем и полным авторским корпусом; продуктовые курсы должны ссылаться на этот модуль, а не заводить собственные правила языка.
- Рабочая копия Tilda в `work/calorie-course-rebuild/source-tilda/` и транскрипты в `source-transcripts/` являются исследовательским архивом. Они не являются будущим runtime-источником курса.

## 4. Integration Points

### Текущая цепочка калорий

`product catalog: calories` → `ACCESS_CALORIES` в общем ЛК → legacy-миграция к ресурсу `metabolism` → `/apps/metabolism.html` → `/api/apps/metabolism` → `metabolism_states`.

Отдельного звена `курс → manifest → progress` между правом и калькулятором пока нет. Поэтому сейчас `ACCESS_CALORIES` семантически означает и купленный Калорийный продукт, и историческое право на калькулятор метаболизма.

### Текущая цепочка тренировок

`product catalog: training` → `ACCESS_STRENGTH` в общем ЛК → legacy-миграция к ресурсу `strength` → `/apps/strength.html` → `/api/apps/strength` → `strength_states`/`strength_exercises`.

Будущий продукт описывает гибкость, силу, мышечную массу, общую и сердечно-сосудистую выносливость и общее здоровье. Существующее приложение реализует только силовой журнал. Поэтому приложение может быть инструментом одной ветки курса, но не владельцем всей методики тренировочного продукта.

### Доступ после Мастер-класса

- `docs/knowledge-base/ACCESS_RULES.md` фиксирует `entitled_locked` и `available`: заранее купленные калории и тренировки должны открываться после завершения Мастер-класса.
- `user_course_policies` уже умеет хранить `paced`/`fully_unlocked`, но account payload новых продуктов сейчас использует только `owned`, каталожные `ready` и `app`; общего расчёта условия «Мастер-класс завершён» для этих двух курсов в найденном runtime нет.
- До готовности тренировочный продукт запрещено включать в checkout.

### Контент и маркетинг

- `platform.content` — единственный владелец авторского голоса, импорта Pikabu/Telegram и writer workflow.
- `products.catalog` — единственный runtime-владелец публичного названия, дескрипшна и внутреннего маркетингового контекста по кодам `calories` и `training`.
- `platform.commerce` — владелец цен, checkout, покупки и ресурса; не владеет содержанием курса.
- `messaging.telegram.*` должен получать утверждённые продуктовые события. Сайт/курс не должен хранить копию графа Telegram-цепочки.

### Устойчивая граница модулей — кандидат для решения владельца

Фактические границы кода поддерживают следующий вариант:

1. Отдельный продуктовый модуль Калорийного курса владеет программой, manifest, статьями, заданиями и прогрессом; он зависит от `products.metabolism`, который остаётся владельцем калькулятора и `metabolism_states`.
2. Отдельный продуктовый модуль тренировочного курса владеет общей матрицей направлений/уровней, программой и прогрессом; он зависит от `products.strength` только в силовой ветке, где нужен журнал подходов и RPE.
3. Общий course engine владеет только переиспользуемой структурой, renderer, versioning и базовым progress API. Конкретные правила прохождения, продуктовые события и задания остаются у каждого курса.
4. `platform.content`, `products.catalog`, `platform.commerce` и messaging остаются внешними владельцами языка, описаний, денег/прав и коммуникаций соответственно.

Это не утверждённые новые `module_id`. Перед изменением `docs/modules.toml` нужно выбрать имена и решить, выделяется ли общий engine сразу либо после первого обобщения hardcoded Мастер-класса.

## 5. Existing Tests

### Курс и редактор

- `backend/tests/test_masterclass_journey.py` — pytest/FastAPI TestClient, реальные тестовые записи SQLAlchemy и server-side проверки.
  - `test_course_structure_editor_publishes_one_version_and_runtime_uses_it()` проверяет публикацию структуры и её использование runtime.
  - `test_course_material_publisher_preserves_article_semantics_and_runtime_override()` проверяет sanitization, независимую публикацию материала и приоритет DB-версии.
  - `test_course_progress_is_server_side_and_steps_are_strictly_sequential()` проверяет порядок прохождения.
  - `test_course_api_uses_tilda_email_but_still_requires_server_access()` проверяет Tilda identity плюс серверное право.
- Покрытие относится к `masterclass-21`; параметризованных сценариев нескольких course codes нет.

### Приложения и доступ

- `backend/tests/test_app_assets.py`
  - `test_application_fragments_use_server_api()` проверяет серверные endpoints во фрагментах.
  - `test_strength_new_user_can_start_and_manage_own_workouts()` проверяет создание и изменение силовых тренировок.
- `backend/tests/test_admin_apps.py`
  - `test_strength_managed_runtime_uses_admin_session_and_writes_audit()` проверяет админский режим и аудит.
- `backend/tests/test_app_auth.py`
  - `test_course_api_rejects_direct_access_before_current_legal_acceptances()` проверяет общий legal gate.
  - `test_masterclass_transition_ignores_obsolete_bearer_token_and_uses_tilda_email()` проверяет канон Tilda-входа.
- `backend/tests/test_personal_access_links.py`
  - `test_universal_account_blocks_review_and_uses_server_resources_for_catalog()` проверяет карточки общего ЛК по ресурсам.
- Отдельных unit/integration-тестов расчёта `calculate(v)` метаболизма не найдено. Формула находится в HTML/JS и не исполняется серверными тестами.
- Отдельного теста эквивалентности frontend/backend формулы 8RM не найдено.

## 6. Shared Utilities

- `backend/app/managed_documents.py` — `ensure_seed_document`, `publish_document`, `restore_document`, `version_history`; готовая основа для versioned manifest каждого курса.
- `backend/app/article_markup.py` — Markdown → semantic HTML, sanitization, plain text; уже применяется публикацией материалов.
- `backend/app/course_structure_service.py: sanitize_fragment(...)` — ограниченная очистка редакторских фрагментов.
- `backend/app/app_service.py: normalize_email(...)`, `resolve_user_for_resource(...)` — общая проверка пользователя legacy-приложений.
- `backend/app/access_service.py: grant_resources(...)` — общая выдача ресурса и политика открытия.
- `backend/app/product_catalog_service.py: product_public(...)` — единственная точка получения пользовательского названия/описания продукта.
- `backend/app/static/embed.js` — общая Tilda-оболочка, identity context и монтирование приложения.

## 7. Potential Problems

1. **Нет владельца содержания двух новых курсов в module registry.** `products.metabolism` и `products.strength` описаны как приложения, а не как course runtime. Вся текущая пересборка живёт в `work/`, который по правилам проекта не является базой фактов.
2. **Один ресурс одновременно означает продукт и инструмент.** `ACCESS_CALORIES` связан с калькулятором, `ACCESS_STRENGTH` — с силовым журналом. Если состав тарифа курса и доступ к инструменту когда-либо разойдутся, текущая модель не сможет выразить это без отдельного ресурса/правила.
3. **Тренировочный курс шире `products.strength`.** Гибкость, кардио, интервалы, зоны мощности и общая выносливость не принадлежат силовому журналу; размещение всей методики внутри `products.strength` создаст неверного владельца факта.
4. **Course API только внешне обобщён.** `{course_code}` есть в URL редактора, но все сервисы принимают только `masterclass-21`, используют `content/masterclass`, один content source и `masterclass_*` progress/event tables.
5. **Отложенное открытие описано, но не закончено как runtime двух курсов.** Account payload знает `owned/ready`, а документ — завершение Мастер-класса; единой вычисляемой функции состояния новых курсов не найдено.
6. **Метаболическая формула живёт только во frontend.** Сервер хранит произвольный `variants` JSON и строку `formula_version`, но не рассчитывает и не проверяет значения. Изменение HTML способно поменять результат без отдельной серверной версии и теста.
7. **Формула 8RM продублирована.** Одни и те же вычисления находятся в `strength.html` и `app_routes.py`; рассинхронизация изменит график клиента и серверный `getStats` по-разному.
8. **Legacy identity для `strength` и `metabolism`.** Они не входят в `PROTECTED_APPS`, а `detectTildaEmail()` может искать email в DOM и использовать remembered identity. `APPLICATION_PLATFORM.md` прямо называет это переходной известной границей, не целевой безопасностью.
9. **Слабая валидация JSON-состояний.** `apply_metabolism_update` проверяет только dict/active variant; силовой endpoint принимает глубоко вложенные workout JSON без отдельной схемы Pydantic. Для учебных заданий нельзя считать эти JSON уже надёжным доменным контрактом.
10. **Несколько представлений продукта.** Seed и marketing context находятся в `product_catalog_service.py`, презентационные пункты — в `masterclass_offer_catalog.py`, фактический каталог — в `managed_document_versions`. Новые course screens обязаны читать `product_public`, иначе появится ещё одна копия названия/обещания.
11. **Tilda-архив не сохраняет полный визуальный/медиа-контракт.** `source-tilda` содержит полные тексты, но README отдельно требует сверки картинок, ссылок, файлов и видео. Его нельзя автоматически объявить новой публикационной БД.
12. **Видео-ссылки чувствительны.** В Git безопасно хранить Boomstream ID/карточку и метаданные; прямой открытый MP4 URL фактически даёт доступ к материалу и не должен становиться публичным course manifest без модели защиты.
13. **Нет тестов формул и границы двух курсов.** Перед выпуском нужны тесты course-code isolation, независимого прогресса, resource gate, delayed unlock, calculator formula version и согласованности 8RM.

## 8. Constraints & Infrastructure

- Tilda Members Area остаётся единственным пользовательским входом. Новый email/password/code/app session для курсов запрещён без отдельной задачи.
- Backend обязан повторно проверять ресурс в PostgreSQL; сама страница/группа Tilda не даёт продуктового права.
- Общие юридические подтверждения (`user_legal_acceptances`) действуют для всех программ; прямое приложение до подтверждения блокируется.
- Калорийный и тренировочный курсы, купленные заранее, должны показываться как купленные, но закрытые до завершения Мастер-класса.
- Тренировочный продукт имеет статус `planned`, `ready=False` и не должен попадать в checkout до выпуска.
- Каноническая визуальная система курсов уже утверждена; два курса не должны создавать собственный дублирующий дизайн-контракт.
- Публичные приложения обслуживаются через `app.edabalans.ru`/`api.edabalans.ru` и Caddy; новый отдельный сайт или собственный ЛК вне текущей Tilda-оболочки не входит в задачу.
- PostgreSQL, backend и NocoDB не публикуются в обход Caddy; наружу остаются только 22/80/443.
- Изменение Tilda-групп, checkout, production hooks, новый внешний сервис/расход и миграция реальных данных требуют отдельного подтверждения владельца.
- Основные зависимости: FastAPI, SQLAlchemy, Pydantic, PostgreSQL; frontend-приложения — самостоятельные HTML/CSS/vanilla JS fragments без отдельного framework build.

## 9. External Libraries

Новых внешних библиотек для исследованной границы не требуется. Текущие механизмы курсов, версий, доступа и приложений реализованы собственным кодом поверх FastAPI, SQLAlchemy, Pydantic и vanilla JavaScript. Внешняя документация не исследовалась, так как этот этап устанавливает фактическую структуру репозитория, а не выбирает новый API или dependency.

## Файлы вероятного будущего изменения

Это dependency trace, не утверждённый план реализации:

- module ownership: `docs/modules.toml` и новые/обновлённые карточки после решения владельца;
- общий course registry/context: `backend/app/course_structure_service.py`, `backend/app/course_structure_routes.py`;
- изоляция источников материалов по course code: `backend/app/course_material_service.py`, `backend/app/course_material_routes.py`;
- пользовательский runtime и progress tables: текущие patterns в `backend/app/masterclass_routes.py`, `backend/app/models.py` и новая migration;
- общий ЛК и ready/delayed state: `backend/app/access_routes.py`, `backend/app/product_catalog_service.py`;
- Tilda mount: `backend/app/static/embed.js`, `backend/app/app_routes.py` и course frontend;
- калькулятор: `backend/app/static/apps/metabolism.html`, при переносе формулы на сервер — отдельный service и tests;
- силовой инструмент: `backend/app/static/apps/strength.html`, `backend/app/app_routes.py` и тест согласованности 8RM;
- content/runtime source: отдельные course manifests и content source keys, без изменения авторского канона `platform.content`;
- tests: расширение `backend/tests/test_masterclass_journey.py` либо отдельные тесты общего course engine и двух product runtimes.
