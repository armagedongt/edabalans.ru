# Исследование кода: единая административная консоль

Дата исследования: 2026-09-19  
Основание: свежий `HEAD` ветки `codex/admin-console-spec-20260919` (`6a891205b0aa63c164b43137a6f35b8f128c3e11`).  
Граница: только фактическая архитектура существующих административных поверхностей; реализация и изменение production не выполнялись.

## Краткий вывод

- В проекте уже есть один логический каталог админок: `/admin`, единая сессия администратора и общий боковой shell. Это не одна монолитная админка: предметные экраны обслуживаются разными route/service/static-модулями.
- Единственный список административных пунктов — `admin_catalog` в `docs/modules.toml`; `/admin/api/project-map` отдаёт его интерфейсу. `docs/generated/*` — производные представления.
- Текущий подтверждённый канон размещает UI на `edabalans.ru`; целевой отдельный хост, уже записанный в документации, — `admin.edabalans.ru`. `api.edabalans.ru` отведён машинным API и webhook, поэтому перенос браузерных экранов туда противоречит текущему канону.
- CRM уже является единственным экраном списка и карточки человека (`/crm`). Старые `/admin/users` перенаправляются туда. Из карточки открываются управляемые DQS, силовые и метаболизм для выбранного `user_id`.
- Редактор материалов МК уже имеет серверный Markdown→HTML pipeline, контроль версии и восстановление, но существующий UI редактирует главным образом структуру курса. Repository Markdown и опубликованная DB-версия материала сейчас являются разными слоями, поэтому будущий Markdown-редактор должен явно выбрать канонический write path, а не создавать третий источник.
- Наблюдаемые дубли в frontend: недостижимый people-flow в `admin.js`, второй content-catalog в `admin.js`, две реализации вкладки тегов в `crm.js`. Это подтверждено маршрутами и вызовами, а не предположением.

## 1. Канонические реестры и документы

| Файл | Фактическая роль |
|---|---|
| `docs/modules.toml` | Единственный машинный реестр модулей, владельцев и `admin_catalog`. Именно из него формируется меню. |
| `docs/ADMIN_ARCHITECTURE.md` | Текущий канон URL, общей сессии, shell, границ экранов и будущего `admin.edabalans.ru`. |
| `docs/CRM_DATA_MODEL.md` | Актуальный паспорт CRM-данных и смысл основных сущностей. |
| `docs/CRM_CORE_DESIGN.md` | Исторический design-документ импорта/миграции. В заголовке всё ещё описан как проектирование до реализации, хотя CRM уже реализована; использовать как историческое объяснение, не как состояние UI. |
| `docs/knowledge-base/modules/catalog/admin.control.md` | Карточка модуля `admin.control`: общий вход, shell, каталог, redirect-контракты. |
| `docs/knowledge-base/modules/catalog/*.md` | Карточки предметных владельцев отдельных экранов. |
| `docs/generated/module-map.md`, `docs/generated/repository-inventory.md` | Сгенерированные витрины; не источники истины. |

Текущие пункты `admin_catalog`:

| Группа | URL | Владелец/назначение |
|---|---|---|
| Клиенты | `/crm` | `platform.crm`: люди, оплаты, доступы, теги, заметки. |
| Приложения | `/admin/dqs` | `products.dqs`: DQS выбранного клиента. |
| Приложения | `/admin/strength` | силовые тренировки; поддержан отдельный `?mobile=1`. |
| Приложения | `/admin/metabolism` | расчёты и состояние метаболизма выбранного клиента. |
| Приложения | `/admin/masterclass-offers-preview` | read-only/preview сценария допродаж МК, не редактор. |
| Маркетинг | `/admin/marketing` | read-only аналитика пути лида. |
| Контент | `/admin/content` | каталог материалов Telegram/Pikabu и авторский каталог. |
| Контент | `/admin/courses` | точка входа в редакторы структуры курсов. |
| Контент | `/admin/courses/calories/structure` | структура калорийного курса. |
| Контент | `https://edabalans.ru/intensive/day-1` | текущий внешний вход в страницы интенсива, а не единый course editor. |
| Коммерция | `/admin/products` | названия, описания и рабочий контекст продуктов/тарифов. |
| Коммерция | `/admin/pricing` | числовые цены, версии и публикация. |
| Коммерция | `/finance` | локальная финансовая модель браузера. |
| Сервис | `https://edabalans.ru/admin/messaging` | Telegram; пункт shell сейчас отключён и помечен как редактируемый через Codex. |
| Знания | `/admin/knowledge-base?view=map|guide|plans|documents` | четыре представления Project Knowledge. |
| Знания | `/admin/library` | библиотекарь: поиск по источникам и очередь решений. |

## 2. Entry points и административные поверхности

### Общий вход и маршрутизация

- `backend/app/crm_routes.py`
  - `GET /admin`, `/admin/` — каталог/дашборд либо login page.
  - `GET /control` — redirect на `/admin`.
  - `GET /admin/users` — redirect на `/crm` с сохранением релевантного query.
  - `GET /admin/{section}` — общий `admin.html` для `dqs`, `strength`, `metabolism`, `messaging`, `pricing`.
  - отдельные обработчики до wildcard отдают `/admin/content`, `/admin/courses`, course structure, `/admin/products`, `/admin/knowledge-base`, `/admin/library`, offers preview.
  - `GET /crm` и статические `crm.css/js` — единственный person workspace.
  - `POST /admin/api/login`, `POST /admin/api/logout` — общая admin-session.
  - `GET /admin/static/{asset}` — защищённая раздача admin-assets с явным allowlist.
- `backend/app/main.py` подключает предметные routers в один FastAPI backend.
- `backend/app/static/admin-shell.js` каждый раз получает `/admin/api/project-map`, строит меню из реестра и встраивает его в `.admin-sidebar`.
- `backend/app/static/admin-shell.css` задаёт общий desktop/mobile shell. Для `/admin/strength?mobile=1` shell сознательно не внедряется.

### CRM: таблицы, карточки и вкладки

- `backend/app/static/crm.html`, `crm.css`, `crm.js` — отдельный CRM frontend.
- Верхние вкладки в `crm.js`: **Все люди**, **Покупатели**, **Оплаты**, **Доступы**, **Теги**, **Как устроено**.
- `renderUsers(buyersOnly)`:
  1. параллельно загружает `/admin/api/payment-products` и `/admin/api/tags?status=active`;
  2. затем загружает `/admin/api/users` с поиском, buyer/product, `first_seen`, access и tag filters;
  3. рендерит карточки: имя, email/Telegram, источник, первая известная активность, число покупок, LTV, последняя покупка, доступы и теги.
- `renderPayments()` параллельно получает `/admin/api/payments` и `/admin/api/payment-products`; отображает неизменяемые финансовые события.
- вкладка **Доступы** получает `/admin/api/access-reviews` и показывает записи на ручную проверку.
- `renderTagAudit()` получает `/admin/api/tags?status=` и `/admin/api/audit/variables`; именно его вызывает текущий `showView("tags")`.
- вкладка **Как устроено** — статическое описание таблиц/потока прямо в JS; оно дублирует смысл канонической документации и может устареть независимо от неё.

### Карточка клиента и переход к приложениям

- `crm.js::openUser(id)` сначала получает `/admin/api/users/{id}`, затем параллельно:
  - `/admin/api/users/{id}/modules`;
  - `/admin/api/users/{id}/personal-access-links`;
  - отдельно запрашивает справочник `/admin/api/resources`.
- Карточка показывает/меняет контактные данные, credential, покупки, оплаты, доступы, Tilda membership, masterclass questionnaire/events/offers, теги, заметки и персональные ссылки.
- Ссылки приложений ведут на `/admin/dqs?user={id}`, `/admin/strength?user={id}`, `/admin/metabolism?user={id}`. Telegram-контакт ведёт в bot admin context.
- После большинства мутаций (`grant`, `pause`, `resume`, `revoke`, name/email/tags/notes/access review) frontend повторно вызывает `openUser(id)`, то есть полностью перезагружает тяжёлую карточку.

### DQS, силовые и метаболизм

- `backend/app/static/admin.js`:
  - список получает `GET /admin/api/apps/users?app_code={dqs|strength|metabolism}`;
  - выбранный пользователь загружается через `Promise.all` из `/admin/api/users/{id}/modules` и `/admin/api/apps/{app}/users/{id}`;
  - frontend приложения получает `EdabalansAppContext={mode:"admin", targetUserId, ...}` через `/embed.js` и используется повторно вместо отдельной копии интерфейса.
- `backend/app/app_routes.py`:
  - `GET /admin/api/apps/users` — объединяет пользователей с состоянием приложения и активным доступом;
  - `GET /admin/api/users/{user_id}/modules` — доступы/наличие состояния по приложениям;
  - `GET /admin/api/apps/{app_code}/users/{user_id}` — карточка состояния;
  - `POST /admin/api/apps/{app_code}/users/{user_id}/open` — явное создание пустого state при наличии доступа;
  - DQS: admin runtime route `/admin/api/apps/dqs/users/{id}/runtime`;
  - metabolism: admin runtime `GET/PUT /admin/api/apps/metabolism/users/{id}/runtime`;
  - strength использует общий `/api/apps/strength` с `target_user_id`; при managed context endpoint требует admin-session.
- `AdminAppEdit` в `backend/app/models.py` хранит аудит административных изменений: `admin_username`, `target_user_id`, `app_code`, `action`, `details`, `created_at`.
- `backend/app/static/admin.js` поддерживает мобильный список силовых с `with_records=true`; browser test закрепляет этот режим.

### Offers preview

- `GET /admin/masterclass-offers-preview` в `crm_routes.py` вызывает `backend/scripts/generate_masterclass_offer_simulator.py::render_simulator_page(...)`, затем внедряет общий shell.
- Это simulator/preview существующей логики офферов. Исполняемые masterclass offer API находятся под `/api/masterclass/admin/...`; самостоятельного редактора офферов экран не предоставляет.

### Course editors и материалы

- `backend/app/course_structure_routes.py`:
  - `GET /admin/api/courses`;
  - `GET/PUT /admin/api/courses/{course_code}/structure`;
  - restore версии структуры.
- `backend/app/static/course-editors.html/js` — выбор курса; `course-structure-editor.html/js` — редактирование структуры, коротких полей, заданий и скрытия существующего материала. Полный body Markdown в этом UI не редактируется.
- `backend/app/course_material_routes.py` уже содержит API body материалов МК:
  - `GET /admin/api/courses/{course_code}/materials`;
  - `GET/PUT /admin/api/courses/{course_code}/materials/{step_id}`;
  - `GET .../{step_id}/versions`;
  - `POST .../{step_id}/versions/{version_no}/restore`.
- `CourseMaterialUpdate` принимает `expected_version`, `content`, `format: markdown|html`.
- `backend/app/course_material_service.py`:
  - `render_material(content, content_format)` преобразует Markdown через `markdown_to_article_html`, HTML — через sanitizer;
  - `publish_material(...)` проверяет optimistic `expected_version`, создаёт `ContentItemVersion`, обновляет latest version и сохраняет semantic HTML;
  - `restore_material(...)` создаёт новую активную версию из старой;
  - размер одного материала ограничен `MAX_MATERIAL_BYTES = 500_000`;
  - специальные tutorial/components не публикуются как обычная статья;
  - если DB-версии ещё нет, `legacy_material_html()` читает `content/masterclass/source-current/*.md` либо старый imported JSON как fallback.
- `backend/app/article_markup.py` — общий Markdown/HTML renderer и sanitizer; `backend/app/masterclass_article_components.py` — renderer специальных компонентных вставок.
- Следствие для будущего редактора: API и versioning можно переиспользовать, но PUT сохраняет опубликованный semantic HTML в `content_items/content_item_versions`; он **не перезаписывает repository Markdown**. Нужно отдельно зафиксировать, является ли редактируемым первоисточником Git-файл или DB publication. Иначе появятся две расходящиеся редактируемые версии.

### Контент, библиотека и Project Knowledge

- `backend/app/static/content-catalog.html/js` + `backend/app/content_routes.py` (`/admin/api/content/*`) — каталог Telegram/Pikabu, группы авторских версий, media/provenance, комментарии и очередь решений.
- `backend/app/static/knowledge-library.html/js` + knowledge library routes (`/admin/api/library/*`) — единый поиск по зарегистрированным источникам и продуктам; не копия Project Knowledge.
- `backend/app/static/knowledge-base.html/js` + knowledge routes — читает зарегистрированные repository-документы и generated map для `map`, `guide`, `plans`, `documents`; не создаёт вторую БД документации.

### Продукты, цены и финансовая модель

- `backend/app/static/product-catalog-editor.html/js` + product catalog service/API — версионный редактор названий, коротких описаний и продуктового контекста.
- `/admin/pricing` работает через `admin.html/admin.js` и pricing API/service; цены имеют draft/published версии и restore/publish lifecycle.
- `/finance` обслуживается `backend/app/app_routes.py::finance_model()` и `eda-finance.html`; требует ту же admin-session, но значения сохраняются только в браузерном `localStorage` (`edabalans-finance-model-v2`), серверной финансовой модели/общих данных нет.
- «Продукты и тарифы» и «Цены и тарифы» выглядят как близкие пункты, но владеют разными фактами: первый — copy/catalog, второй — числовые цены и публикация. Это UX-пересечение названий, не доказанный дубль данных.

## 3. Общая авторизация, cookie и домены

- Реализация общей сессии находится в `backend/app/admin_auth.py` и используется всеми перечисленными FastAPI routes, включая `/finance` и управляемые приложения.
- Логин — `ADMIN_USERNAME`/`ADMIN_PASSWORD`; в Git секреты не хранятся.
- Cookie: `edabalans_admin`, `HttpOnly`, `Secure`, `SameSite=Strict`, срок 30 дней. Для доверенных edabalans-поддоменов задаётся domain `.edabalans.ru`; logout удаляет cookie в согласованной области.
- Тесты закрепляют: ротация пароля инвалидирует старую сессию; cookie работает между доверенными edabalans-поддоменами; внешний host не расширяет область доверия.
- `infra/caddy/Caddyfile`: текущий публичный домен маршрутизирует `/admin/messaging` и bot paths отдельно, остальные admin/API пути идут в backend. Блок `api.edabalans.ru` предназначен для API proxy, а не для UI shell.
- Канонический документ требует отдельной задачи для `admin.edabalans.ru`: DNS, Caddy host block, cookie-domain/redirects и проверка абсолютных ссылок. Простое изменение menu URL недостаточно.

## 4. Data layer и источники данных

### CRM

- `backend/app/models.py` разделяет человека (`users`) и его email, messenger accounts, phones, payments, accesses, attribution, tags, notes, Tilda snapshots, questionnaire/event/offer data.
- `backend/app/crm_service.py::list_users(...)` строит строку человека с шестью correlated scalar subqueries: primary email, Telegram, число покупок, фактический LTV, оценочный LTV, последняя покупка. Затем отдельным запросом загружает активные access codes для страницы.
- Лимит списка людей по умолчанию 100, максимум 250; платежей 200/500; access review до 1000.
- `crm_service.summary(db)` выполняет семь самостоятельных aggregate scalar queries: users, buyers, paid payments, actual revenue, estimated revenue, Tilda members, access reviews.
- `crm_service.user_detail(db, user_id)` последовательно загружает множество коллекций: идентификаторы/контакты, payments, accesses, attribution, tags, notes, Tilda snapshot, questionnaires/answers, masterclass events/offers и credential. Это сборная карточка, а не одна таблица.

### Что означает `first_seen_at`

- `User.first_seen_at` — **самый ранний известный момент появления/активности человека из доступных источников**, а не обязательно регистрация, покупка или первый вход в ЛК.
- `backend/app/importers/legacy.py::import_clients(...)` читает legacy-поля `Первая активность`, fallback `Дата создания`; заменяет `user.first_seen_at` только если импортированное время раньше уже известного. То же правило применяется к messenger account.
- Импорт оплаты также может впервые создать человека с временем исходного события. Native onboarding/Tilda создают собственные timestamps. Происхождение фиксируется attribution/import batch, но само поле `first_seen_at` не кодирует вид события.

### Прежняя Google CRM

- `docs/CRM_CORE_DESIGN.md` описывает два historical Google sources: таблицу оплат (строка = финансовое событие) и таблицу клиентов после бота (Telegram-centric, email может отсутствовать). Они были входом миграции, а не текущим runtime CRM.
- Импорт помечается batch/source `google_legacy_crm`; текущим источником UI является PostgreSQL через `crm_service.py`.
- `legacy/google/dqs/CONTEXT.md` сохраняет историческое обсуждение общей Google-таблицы CRM.
- `legacy/google/dqs/SUPERSEDED_INTEGRATIONS_PLAN.md` — явно superseded план; AGENTS.md прямо запрещает его реализовывать. Его нельзя использовать как действующую архитектуру.

## 5. Существующие API и переиспользуемые части

| Задача | Уже есть и может быть переиспользовано |
|---|---|
| Единое меню/оболочка | `admin-shell.js/css`, `/admin/api/project-map`, `docs/modules.toml::admin_catalog`. |
| Общая авторизация | `admin_auth.py`, login/logout API, общая cookie. |
| CRM люди/платежи/доступы/теги | `/admin/api/users*`, `/payments`, `/payment-products`, `/access-reviews`, `/resources`, `/tags*`, `/audit/variables`. |
| Управляемые клиентские приложения | app list/state/modules API, `target_user_id`, общий user frontend, `AdminAppEdit`. |
| Course structure | course list, versioned structure GET/PUT/restore, существующий editor shell. |
| Markdown body материала | course material GET/PUT/versions/restore, `article_markup.py`, sanitizer, masterclass component renderer, optimistic versioning. |
| Каталог контента | `/admin/api/content/*`, существующие content source/item/version/media модели. |
| Project Knowledge | `/admin/api/project-map` и knowledge-base routes, без копирования repository docs. |
| Product/pricing versions | существующие version/publish/restore сервисы; их источники фактов остаются раздельными. |

Для будущего Markdown course editor минимально нужны существующие: admin shell/session; `/admin/api/courses`; structure manifest; material API; `expected_version`; renderer/sanitizer; version history/restore; текущие Markdown sources и `ARTICLE_STANDARD`/`MARKDOWN_MATERIAL_TRANSFER`. Не требуется новый универсальный content store.

## 6. Наблюдаемые дубли и недостижимые участки

1. **People UI:** `admin.js` содержит самостоятельные `users()`/person-list ветви для `/admin/users`, но backend всегда redirect-ит `/admin/users` в `/crm`. Логика общего person renderer в app context используется, но старый общий список через этот URL недостижим.
2. **Content catalog:** `admin.js` содержит `contentCatalog()`, однако явный route `/admin/content` раньше wildcard отдаёт отдельные `content-catalog.html/js`. Встроенная версия `admin.js` на каноническом URL недостижима.
3. **Tags:** в `crm.js` существуют `renderTags()` с edit/merge handlers и `renderTagAudit()`; `showView("tags")` вызывает только `renderTagAudit()`. Первая реализация не является активной вкладкой.
4. **Architecture explanation:** вкладка CRM «Как устроено» вручную перечисляет таблицы и поток, хотя те же факты принадлежат `CRM_DATA_MODEL.md`/модульным карточкам.
5. **Старый design status:** `CRM_CORE_DESIGN.md` всё ещё выглядит как pre-implementation draft, несмотря на действующую реализацию; это документальная неоднозначность.
6. **Content sources:** repository Markdown используется как fallback до первой DB-публикации, после чего runtime отдаёт latest `ContentItemVersion`. Это не кодовый дубль, но два слоя контента с риском расхождения при ручной редактуре обоих.

## 7. Потенциальные причины долгих загрузок — только подтверждённые кодом

- Начальная загрузка CRM: сначала `await /admin/api/summary`, затем активная вкладка запускает свои запросы. Это последовательный waterfall. Параллельно общий shell делает отдельный `/admin/api/project-map`.
- `summary()` — семь последовательных aggregate SQL запросов вместо одного агрегата/параллельного слоя.
- `list_users()` содержит шесть correlated scalar subqueries на каждую строку и сортировку по вычисляемому last purchase, затем второй запрос доступов. Поиск с `%query%` применён к имени и scalar email/Telegram. Это потенциально дорогой SQL shape; реальная длительность без query plan/метрик не измерена.
- `user_detail()` собирает карточку множеством последовательных SQL запросов; frontend после него делает ещё modules/personal-links/resources.
- После почти каждой мутации карточки `openUser(id)` повторно загружает весь набор данных, а не обновляет изменённый блок.
- `GET /admin/api/apps/users` объединяет access/state sets и формирует строки пользователей; код следует проверить query-plan/число обращений `primary_email` при профилировании. Без runtime trace утверждать N+1 как факт нельзя.
- `admin-shell.js` получает project map на каждом открытии предметного экрана; cache layer в frontend не наблюдается.
- Никаких измерений production latency, EXPLAIN или browser network trace в рамках read-only исследования не выполнялось; причины выше — кандидаты, непосредственно видимые из control flow.

## 8. Existing tests

- `backend/tests/test_crm_auth.py`
  - `test_legacy_control_and_people_redirect_to_single_admin_surfaces()` — закрепляет `/control` и `/admin/users` redirects.
  - `test_login_creates_shared_admin_session()` и `test_admin_session_last_30_days_and_password_rotation_revokes_it(...)` — общая сессия/ротация.
  - `test_admin_cookie_cross_subdomain_and_logout()` и `test_independent_host_login_does_not_expand_cookie_trust()` — доменная область cookie.
  - также проверяются auth, assets, common shell, offers preview и course APIs.
- `backend/tests/browser/admin-shell.e2e.mjs` — группы registry menu, mobile drawer, collapse/hide и `/finance`.
- `backend/tests/test_admin_apps.py`
  - `test_admin_app_list_includes_access_without_state_and_state_without_access()`;
  - `test_strength_admin_mobile_list_requires_admin_and_returns_only_profiles_with_records()`;
  - `test_strength_managed_runtime_uses_admin_session_and_writes_audit()`.
- `backend/tests/browser/strength-admin-mobile.e2e.mjs` — мобильная управляемая силовая.
- `backend/tests/test_eda_finance.py::test_finance_model_uses_admin_session_and_contains_browser_persistence()` — общая сессия + localStorage-only.
- `backend/tests/test_content_catalog.py`, `test_content_authoring_catalog.py` — модели/авторизация/контролы content catalog.
- `backend/tests/test_knowledge_base.py` — auth, чтение/search документов и checked-in project map.
- `backend/tests/test_knowledge_library.py` — библиотека.
- `backend/tests/test_pricing_catalog.py`, `test_product_copy_migration.py` — pricing/product boundaries.
- `backend/tests/test_course_structure_multiline.py` — сохранение структуры/многострочных полей. Материальные API также защищены auth-тестами, но полного browser-теста будущего Markdown editor нет, поскольку UI ещё не реализован.
- `telegram-bot/service/tests/test_admin_session_contract.py` — совместимость общей admin-session на Telegram surface.

## 9. Точные зоны будущих изменений и проверки

### Минимальный вариант архитектуры

Сохранить текущие URL и предметные экраны, завершить консолидацию только на уровне shell/navigation:

- удалить недостижимые frontend-ветви после покрытия тестами;
- устранить две реализации tags/content/people;
- оставить `/crm` единственным person workspace;
- добавить body Markdown editor поверх уже существующего course material API;
- не менять домен и cookie contract.

Затрагиваемые файлы: `backend/app/static/admin.js`, `crm.js`, `content-catalog.*`, `course-structure-editor.*` либо новый один editor asset, `course_material_routes.py/service.py`, `docs/modules.toml`, `docs/ADMIN_ARCHITECTURE.md`, карточки владельцев. Риск: низкий/средний; основной риск — случайно удалить ветвь `person()` используемую app context вместе с недостижимым старым people list.

### Рекомендуемый вариант архитектуры

Сначала выполнить минимальную консолидацию, затем отдельным выпуском перенести browser UI на уже выбранный `admin.edabalans.ru`, оставив `api.edabalans.ru` машинным API. Предметные backend routes можно сохранить; host routing отделит UI, а не потребует переписать их в новый монолит.

Дополнительные файлы/границы: `infra/caddy/Caddyfile`, admin auth trusted-host/cookie helpers, absolute URL generation, Telegram admin rewrite, offers simulator links, blog/admin redirects, environment/domain settings и ops docs. Риск: средний/высокий из-за cross-subdomain cookie, redirects, CSP/CORS/absolute links и rollback, поэтому это отдельная миграция с сохранением старых redirects.

### Обязательные проверки будущей реализации

1. Unit/API: все admin routes требуют одну сессию; login/logout/rotation/cookie-domain.
2. Redirects: `/control`, `/admin/users`, старые deep links и query `user` не теряются.
3. Browser: shell на каждой поверхности; desktop/mobile; strength `mobile=1` исключение.
4. CRM: все вкладки и карточка; переход CRM → выбранный user → DQS/strength/metabolism; изменения пишут `AdminAppEdit`.
5. Markdown: render/sanitize, custom components, конфликт `expected_version=409`, versions/restore, media links, special tutorial rejection.
6. Source-of-truth contract: тест должен доказать выбранное направление Git Markdown ↔ DB publication; молчаливое расхождение недопустимо.
7. Domain migration: оба hosts, Secure/Strict cookie, logout, old URL redirects, Caddy Telegram paths, offers preview, finance, content/library/knowledge links.
8. Performance: до оптимизации снять browser waterfall и SQL `EXPLAIN ANALYZE` для `summary`, `list_users`, `user_detail`; затем закреплять только измеримый эффект.

## 10. Ограничения и инфраструктура

- Backend — FastAPI/SQLAlchemy/PostgreSQL; наружу PostgreSQL не публикуется, доступ только через Caddy.
- NocoDB не является публичной админкой: loopback/SSH-only.
- Tilda остаётся единственным пользовательским входом в текущий ЛК; admin auth — отдельный внутренний контур.
- Blog editor отсутствует; публичный блог не следует автоматически считать частью существующей админки.
- Telegram admin имеет особую маршрутизацию через Caddy и собственный session-contract test; перенос host требует сохранить этот контракт.
- `/finance` не является общей серверной моделью: данные одного браузера не видны другому администратору.
- Для изменения DNS, Caddy, production secrets/password, миграций и пользовательских данных требуется отдельная реализационная задача и предусмотренные AGENTS.md подтверждения. В этом исследовании такие изменения не выполнялись.
