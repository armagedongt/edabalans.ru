# Исследование кода: каталог рецептов и конструктор приёма пищи

Дата: 2026-08-27
Статус: initial research
Контекст: `work/recipe-catalog/user-spec.md` пока является шаблоном без принятых требований; `decisions.md` пуст. Ниже зафиксирована только существующая реализация и её границы.

## 1. Entry Points

### Текущий пользовательский вход и гейт

- `backend/app/app_routes.py` — отдаёт статические T123-фрагменты. `app_fragment(app_code: str) -> FileResponse` разрешает коды `recipes-part-1` и `recipes-part-2`, но не отдельный `recipes`/`recipe-catalog`.
- `backend/app/static/apps/recipes-part-1.html` — однострочный mount-point `#recipes-part-1-app`, подключает общие `masterclass.css` и `masterclass.js`; данных рецептов в файле нет.
- `backend/app/static/apps/recipes-part-2.html` — такой же mount-point `#recipes-part-2-app`; самостоятельного UI второй части нет.
- `backend/app/static/embed.js` — постоянный загрузчик для страниц Tilda. `PROTECTED_APPS` включает обе части рецептов; `detectTildaMemberEmail()` берёт `profile.login` из `tma__getProfileObjFromLS()`, затем загрузчик передаёт email и placement-token в приложение. Для защищённого приложения нет альтернативного email-ввода.
- `backend/app/static/masterclass.js` — общий UI офферов и системных шагов Мастер-класса. `gate(part)` вызывает `GET /api/masterclass/gate/{part}`. При доступе он сейчас выводит текст «Здесь появятся карточки рецептов», а не каталог; при отсутствии доступа показывает существующие карточки допродажи.
- `backend/app/masterclass_routes.py` — router с префиксом `/api/masterclass`. `recipe_gate(part: int, email: str, placement_token: str, request: Request, db: Session, settings: Settings) -> dict` принимает только части `1` и `2`, требует подписанный placement-token и проверяет `ACCESS_RECIPES`. Он пишет одноразовое событие `recipes_part_{part}_opened` и возвращает либо `state: content`, либо `state: offer`.

### Точки перехода из Мастер-класса

- `content/masterclass/course/course.json` — seed/fallback структуры дня курса. День 6 создаёт placement `recipes-part-1-gate`; день 7 содержит системный шаг `kind: recipes-part-1`, `accessResource: ACCESS_RECIPES` и перечень будущих материалов; дальнейшая часть курса содержит второй gate. Это маршрут из курса к текущим фрагментам, а не хранилище карточек рецептов.
- `backend/app/course_structure_service.py` — считает `recipes-part-1` и `recipes-part-2` системными шагами (`SYSTEM_KINDS`); в `course_context()` экспортирует их как приложения. Редактор обычных текстовых материалов намеренно их не принимает.
- `backend/app/masterclass_routes.py` — при сборке course runtime добавляет `placement` и `placement_token` для обоих recipe-gate. `COURSE_APP_EVENTS` связывает открытие с событиями `recipes_part_1_opened` / `recipes_part_2_opened`.

### Возможная отдельная поверхность

В текущем registry отдельного module/route для каталога рецептов нет. `backend/app/product_catalog_service.py` уже объявляет продукт `recipes`, но в `PRODUCT_CONNECTIONS` для него стоит `{"resource": "ACCESS_RECIPES", "app": None, "ready": False}`. Поэтому личный кабинет показывает продукт, но не может открыть отдельный каталог.

## 2. Data Layer

### Существующие коммерческие и доступные данные

- `backend/app/models.py` — SQLAlchemy 2 ORM-модели PostgreSQL. `Product(code, name, status)` представляет продаваемый продукт; `Resource(code, name, status)` — техническое право; `ProductAccessRule(product_id, resource_id, effective_from, effective_to)` связывает подтверждённую покупку с правами.
- `backend/app/models.py` — `Payment` хранит идемпотентную историю оплаты с уникальными `(source, external_order_id)` и `(source, external_payment_id)`; `UserAccess(user_id, resource_id, source_payment_id, granted_at, expires_at, revoked_at)` — отдельный текущий entitlement. Это действующая граница между оплатой и доступом.
- `backend/app/models.py` — `User`, `UserEmail`, `UserCoursePolicy` и `MasterclassEvent` нужны текущему гейту: user находится по нормализованному Tilda email, access-review status способен блокировать доступ, а открытие recipe-gate записывается в `masterclass_events`.
- `backend/migrations/versions/20260822_0015_masterclass_journey.py` — seed-миграция создаёт активный ресурс `ACCESS_RECIPES` с именем «Система рецептов» вместе с ресурсами Мастер-класса и офферным runtime.
- `backend/migrations/versions/20260823_0020_pricing_catalog.py` — создаёт каталог цен и строку `product.recipes`/`RECIPES` с `resource_codes: ["ACCESS_RECIPES"]`. Цена и доступ существуют отдельно от будущих рецептов.

### Данных каталога пока нет

В `backend/app/models.py` отсутствуют `recipes`, ингредиенты, категории, блюда, варианты, медиа, избранное, план приёма пищи или пользовательские конструкторские сохранения. `DqsState` — отдельная JSONB-строка дневника DQS на пользователя; он не содержит рецептуры. В репозитории также нет migration с данными рецептов.

`ManagedDocumentVersion` используется для версионирования структуры курса, материалов и каталога публичных продуктов, но не как рецептурная модель. В нём есть JSON payload и optimistic versioning на уровне документа; это не существующая модель карточек, фильтров или вычислений конструктора.

## 3. Similar Features

- `backend/app/static/apps/dqs.html` + `backend/app/app_routes.py` — пример отдельного client app, загружаемого через `embed.js`, который общается с FastAPI и хранит пользовательское состояние в `DqsState`. Применим только для оболочки Tilda/API, поскольку данные и правила DQS не совпадают с рецептами.
- `backend/app/static/apps/masterclass-course.html` + `backend/app/masterclass_routes.py` — пример защищённого server-driven приложения Мастер-класса, где Tilda даёт email, а backend повторно проверяет доступ. Recipe catalog должен использовать ту же границу идентичности/права, а не login или email form.
- `backend/app/product_catalog_service.py` + `backend/app/product_catalog_routes.py` — пример versioned editable catalog: `active_product_catalog()`, `product_public(db, code)` и `/admin/api/product-catalog*`. Он владеет только маркетинговыми названиями и описанием продукта, не рецептами; `validate_catalog()` прямо запрещает менять технические коды и состав из редактора.
- `backend/app/models.py` (`StrengthExercise`) — единственный отдельный предметный справочник, но он очень мал: `code`, `name`, `active`, `sort_order`, `metadata_json`. Паттерн пригоден как пример immutable code + управляемая активность, но не покрывает рецептурную нормализацию.
- `backend/app/masterclass_offer_catalog.py` — уже содержит публичные описания продукта «Система рецептов», включая «Рецепты и конструктор блюд». Это copy для продаж; не использовать как второй source of truth содержимого каталога.

## 4. Integration Points

### Доступ и identity

- `backend/app/app_service.py` — `resolve_user_for_resource(db, email, resource_code)` находит активного пользователя по `UserEmail`, проверяет review-block и активный `UserAccess`; это стандартная серверная проверка приложений.
- `backend/app/masterclass_routes.py` — `resolve_masterclass_user(...)` является текущей специализацией того же пути для Мастер-класса; `access_codes(db, user.id)` возвращает набор действующих ресурсов, из которого гейт читает `ACCESS_RECIPES`.
- `backend/app/access_service.py` — `user_for_email`, `review_blocks_access`, `grant_resources` — общие функции поиска и выдачи прав. `grant_resources()` не дублирует неотозванный доступ, проверяет существующие resources и создаёт/обновляет `UserCoursePolicy`.
- `docs/APPLICATION_PLATFORM.md`, `docs/knowledge-base/ACCESS_RULES.md` и `AGENTS.md` фиксируют ограничение: Tilda Members Area — единственный пользовательский вход; email только из авторизованного Tilda profile; backend обязан проверить PostgreSQL access. Отдельная passwordless/app session для каталога не разрешена.

### Коммерция и офферы

- `backend/app/tilda_service.py` — `OFFER_RESOURCES = {"recipes": "ACCESS_RECIPES", ...}` и `process_tilda_payment(...)` сопоставляют checkout с продуктом/правом после подтверждённой оплаты. Входящий webhook — `POST /integrations/tilda/payments` в `backend/app/tilda_routes.py`.
- `backend/app/masterclass_routes.py` — текущая офферная ветка создаёт `OfferCheckout`, проверяет re-use/срок и возвращает Tilda cart command. Каталог рецептов не должен заново реализовывать продажу или сам выдавать `ACCESS_RECIPES`.
- `backend/app/access_routes.py` — `/api/account` строит карточки продуктов из `product_public(...)` и действующих `UserAccess`; для recipes link сейчас отсутствует из-за `ready: False`.

### DQS и курс

- `legacy/google/README.md`, `legacy/google/dqs/CONTEXT.md`, `legacy/google/dqs/apps-script/Code.gs`, `legacy/google/dqs/tilda/client-t123.html` — legacy DQS является только справочным снимком прежнего дневника и его Google-интеграции. Фактический DQS уже перенесён в FastAPI/PostgreSQL; legacy не содержит текущего каталога рецептов/конструктора.
- `content/masterclass/course/course.json` связывает формирование «опорных точек», овсянку и пять вкусов с product entry. Это содержательная точка интеграции, не API-контракт каталога.

## 5. Existing Tests

Тесты живут в `backend/tests/`, запускаются pytest; API сценарии используют FastAPI `TestClient`, SQLite/PostgreSQL-compatible SQLAlchemy factory и seed data.

- `backend/tests/test_app_assets.py` — проверяет публичную отдачу app fragments и общих ассетов. Представительная сигнатура: `def test_masterclass_fragments_and_shared_assets_are_public() -> None:`; она требует, чтобы обе recipe части имели верный mount id и подключали `masterclass.js`.
- `backend/tests/test_masterclass_journey.py` — покрывает доступ, офферы, placement tokens и course journey. Представительная сигнатура: `def test_recipe_gate_uses_access_and_records_open_once():`; тестирует отказ без `ACCESS_RECIPES`, success после `UserAccess`, одноразовую запись `MasterclassEvent` и отсутствие recipe follow-up notification.
- `backend/tests/test_tilda_payments.py` — проверяет подтверждённый webhook, идемпотентность payment и выдачу `ACCESS_RECIPES` через product rules.
- `backend/tests/test_app_assets.py` — DQS тесты закрепляют отсутствие legacy Google/App Script URL в production fragment; это релевантно, если конструктор будет использовать сведения DQS: он не должен возвращать browser на Google.

Не покрыты, потому что их нет: API карточек и фильтрации рецептов, CRUD/admin редактирование рецептуры, нутриентные расчёты, сохранение собственной сборки, интеграция выбора блюда с DQS, доступ к медиа и разграничение публичной/закрытой информации о рецепте.

## 6. Shared Utilities

- `backend/app/app_service.py` — `normalize_email`, `resolve_user_for_resource`, `primary_email`, `clean_json`; общий путь доступа и безопасная сериализация JSON-полей.
- `backend/app/access_service.py` — `normalized_email`, `user_for_email`, `review_blocks_access`, `resources_for_codes`, `grant_resources`; общий доступ и его проверка.
- `backend/app/app_auth.py` — `create_placement_token(placement, settings)` и `require_placement(request, placement, token, settings)` подписывают источник оффера/шага Мастер-класса. Они нужны существующим переходам из course, но не должны быть единственной авторизацией отдельного каталога.
- `backend/app/product_catalog_service.py` — `product_public(db, code)` берёт утверждённое public name/descriptor и его техническую связь по стабильному коду. Использовать для заголовка/карточки продукта, а не держать новое локальное название.
- `backend/app/managed_documents.py` — `ensure_seed_document(...)` и `publish_document(...)` обеспечивают versioned editable documents с защитой stale update. Это готовая инфраструктура, если редакционные правила решат хранить одну версию структуры или методики конструктора.
- `backend/app/static/embed.js` — один загрузчик Tilda, умеющий монтировать новый app code после его явного добавления в `PROTECTED_APPS`, `roots` и whitelist маршрута.

## 7. Potential Problems

- **Гейт не является каталогом.** `recipe_gate()` утверждает `state: content` сразу после entitlement, хотя frontend показывает только заглушку. Добавление frontend без новой API/data layer даст статический контент без управляемых данных.
- **`ACCESS_RECIPES` — единственное право на обе части.** Разделение «часть 1/2» сейчас служит событиям курса и офферным окнам; разные права/персональное открытие частей не реализованы.
- **Email передаётся query parameter.** Это уже известная переходная граница текущего Tilda-контра, а не модель, которую следует расширять. Любой новый endpoint должен повторять server access check и не делать email идентификатором данных рецепта.
- **Tilda placement token.** Токен подтверждает placement, а не user identity; route сначала разрешает пользователя по Tilda email, затем вызывает `require_placement`. Не раскрывать рецепт только по token или ссылке.
- **JSONB не заменяет модель каталога без контракта.** DQS допускает один document-like JSON на пользователя, но фильтруемый каталог с вариантами, ингредиентами и медиа потребует определить source of truth, индексы и версионирование до внедрения.
- **Изменения schema требуют ручного выпуска.** `docs/OPERATIONS.md` устанавливает backup + test restore до migration, а автоматический deploy блокирует миграции; миграции не должны смешиваться с обычным code-only deploy.
- **Параллельная работа.** Worktree уже содержит незакоммиченные изменения в `masterclass_routes.py`, `models.py`, `masterclass.js`, `course.json`, payment/CRM files и docs; их нельзя перезаписывать при реализации, и будущая точка пересечения особенно высока для текущего recipe-gate.
- **Контент и код имеют разных владельцев.** Авторский текст регулируется `platform.content` и `edabalans-writer`; модуль каталога рецептов не должен создавать второй канон названий продукта, курса или редакторского голоса.

## 8. Constraints & Infrastructure

- `backend/requirements.txt` и `backend/Dockerfile` — Python 3.13, FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.1, PostgreSQL driver `psycopg[binary] 3.3.4`, Pydantic Settings 2.15.0. Backend запускается Docker image from `python:3.13-slim`.
- `docs/OPERATIONS.md` — push в `main` запускает tests/compose checks and deployment polling. Новая Alembic migration блокирует automatic publish and requires backup, actual test restore, separate migration verification and manual release with `ALLOW_DATABASE_MIGRATIONS=1`.
- `docs/modules.toml` — текущий owner экранов recipes-part-1/2 — верхнеуровневый `products`; product/access facts принадлежат `platform.commerce`; auth boundary — `platform.auth`; course structure — `products.masterclass.course`.
- `docs/knowledge-base/PRODUCT_CATALOG.md` — product catalog owns public naming/descriptor only; prices belong to pricing catalog and technical access/resource/app links are deliberately not editable there.
- `docs/knowledge-base/ACCESS_RULES.md` — payment, entitlement, unlock policy and actual access are intentionally separate facts; a Tilda group, tag, browser state or personal link cannot substitute active PostgreSQL entitlement.

## 9. External Libraries

Новая внешняя библиотека в текущей функции не обнаружена. Уже используемые FastAPI, SQLAlchemy, Alembic and Pydantic покрывают HTTP, persistence, migrations and validation; Context7 research is therefore not applicable at this stage.

## Module boundary and factual implementation surface

### Устойчивая граница

Новый дочерний module `products.recipes` должен владеть рецептурной сущностью и пользовательской функцией «Каталог рецептов и конструктор приёма пищи»: модели/миграции, read API, client app, админский контур рецептурных данных и их тесты. Он зависит от `platform.auth` и `platform.commerce`, но не владеет ими.

`products.masterclass.course` остаётся владельцем только шагов и переходов курса к рецептам. `products.catalog` остаётся владельцем маркетингового названия/дескрипшна «Система рецептов». `platform.commerce` продолжает владеть `RECIPES` / `ACCESS_RECIPES`, pricing, payment and entitlement. `products.dqs` остаётся владельцем дневника DQS; явный API-контракт потребуется только если конструктор станет записывать/читать данные DQS.

### Минимальная фактическая поверхность первой реализации

1. Зарегистрировать `products.recipes` в `docs/modules.toml` и дать ему card; перенести ownership новых файлов туда, не забирая текущие course/commerce источники.
2. Создать migration и ORM/API для recipe catalog; текущая схема не содержит ни одной рецептурной таблицы.
3. Добавить защищённый app code/fragment в `app_routes.py` и `embed.js`, либо заменить только содержимое существующих recipe part fragments, если продуктово подтверждено, что части — единственная навигация каталога.
4. Проверять `ACCESS_RECIPES` через shared access service на каждом read/write endpoint; в ЛК поменять `PRODUCT_CONNECTIONS["recipes"]` с `ready: False` только когда есть реальная точка запуска.
5. Сохранить `recipe_gate()` как путь из курса/офферов или заменить его ответ на ссылку в новый каталог без изменения коммерческой логики; добавить тесты гейта и нового API.

## Dependency trace

`Tilda Members Area profile.login` → `embed.js` → app fragment → client API request with email + (для course placement) token → `resolve_masterclass_user` / shared access lookup → `users` + `user_emails` + active `user_accesses(ACCESS_RECIPES)` → recipe-gate/catalog response.

`Tilda payment webhook` → `tilda_service.process_tilda_payment(...)` → `payments` → `product_access_rules` → `user_accesses(ACCESS_RECIPES)` → account/card and recipe-gate/catalog become available.
