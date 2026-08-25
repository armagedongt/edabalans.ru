---
created: 2026-08-25
status: current
type: code-research
feature: course-structure-editor
---

# Исследование кода: редактор структуры курса

## Последующее решение владельца

После исследования владелец запретил перестановку материалов в редакторе. Кнопки
«выше/ниже», миграция прогресса материалов ради reorder и journey перестановки не
входят в реализацию. Порядок материалов меняется только отдельной задачей в чате.

## Краткий вывод

Сейчас `content/masterclass/course/course.json` является единственным источником
программы, но backend читает его только один раз при импорте Python-модуля. Простая
запись JSON-файла из админки не даст надёжного мгновенного применения: запущенный
процесс продолжит использовать старые глобальные словари, а следующий deploy может
вернуть Git-версию файла.

Главный блокер безопасной вставки материала перед существующим шагом — прогресс хранится по
`day_number + step_index`, хотя в манифесте у материалов уже есть стабильные `id`.
После вставки или перемещения карточки старый индекс начнёт обозначать другой
материал. До добавления шагов runtime и БД нужно перевести на `step_id`.
Чек-лист аналогично хранит галочки по строковому индексу внутри JSON.

Для требуемого поведения «нажал сохранить — сразу работает, без production deploy»
устойчивый путь — перенести именно **структуру курса** в версионированную запись
PostgreSQL и сделать её единственным runtime-источником. `course.json` после
одноразового переноса остаётся seed/export-снимком, но больше не участвует в выборе
активной программы. Паттерны версий и optimistic locking уже есть у цен и страниц
бесплатного интенсива; готовой модели версии структуры курса пока нет.

## 1. Entry Points

### Runtime Мастер-класса

- `backend/app/masterclass_routes.py` — основной FastAPI-router курса, прогресса,
  приложений и предложений.
  - `load_course_manifest() -> dict` читает и минимально валидирует JSON.
  - На уровне модуля выполняются `COURSE_MANIFEST = load_course_manifest()` и
    построение `COURSE_DAYS`, `COURSE_CHECK_COUNTS`, `COURSE_APPS`, `COURSE_OFFERS`,
    `COURSE_CONTENT_FILES`. Они не обновляются во время жизни процесса.
  - `course_manifest(email, request, db, settings) -> dict` возвращает глобальный
    `COURSE_MANIFEST` после проверки `ACCESS_MASTERCLASS`.
  - `course_payload(db, user, settings, now) -> dict` сопоставляет активную
    структуру с серверным прогрессом.
  - `course_complete_step(day, index, ...)` принимает позиционный индекс и пишет
    его в `masterclass_step_progress`.
  - `course_update_check(day, index, ...)` пишет галочку в JSON по ключу индекса.
- `backend/app/static/masterclass-first-days-preview.html` — фактический frontend
  21-дневного курса, несмотря на историческое имя файла. Загружает
  `/api/masterclass/course/manifest`, строит оглавление и страницы дней из
  манифеста. Удалять его вместе со старым прототипом нельзя.
- `backend/app/static/masterclass.js` — загрузчик приложения курса/встраивания.
- `backend/app/main.py` — подключает `masterclass_router`, `crm_router` и остальные
  роутеры к одному FastAPI-приложению.

### Старая служебная страница

- `backend/app/crm_routes.py`:
  - `masterclass_course_preview(...) -> FileResponse` обслуживает
    `/admin/masterclass-course-preview` и отдаёт статический старый файл.
- `backend/app/static/masterclass-course-preview.html` — полностью автономный
  прототип старого дня 5. В нём вручную зашиты программа, теги, темы, таймер
  `20 часов`, три темы дизайна и `localStorage`; `course.json` и runtime API он не
  читает. Это и есть лишняя параллельная сущность, которую нужно удалить/заменить.
- `backend/app/static/masterclass-designs.html` — ссылки трёх старых тем ведут на
  тот же прототип; после удаления файла ссылки станут битым маршрутом.
- `backend/app/static/admin.html` и `backend/app/static/admin-portal.html` содержат
  ссылки «Предпросмотр курса» и «Варианты дизайна».
- `backend/tests/test_crm_auth.py` сейчас проверяет старое содержимое по фразе
  «Не считать идеально, а видеть главное» и три старых дизайна. Эти проверки нужно
  заменить контрактом нового редактора.

### Действующая общая админка

- `backend/app/crm_routes.py`:
  - `admin_index()` — `/admin`;
  - `admin_section()` — существующие разделы общей оболочки;
  - `admin_asset()` — allowlist защищённых CSS/JS;
  - `admin_login()` — создаёт общую cookie-сессию.
- `backend/app/static/admin.html`, `admin.js`, `admin.css` — единая оболочка и
  навигация. Для простого редактора допустима отдельная защищённая страница,
  доступная из этой навигации, как уже сделано для базы знаний и Мастер-класса.
- `backend/app/static/masterclass-admin.html/js/css` — другой действующий модуль:
  прогресс клиентов, тестовые профили, офферы и уведомления. Это не редактор
  структуры и удалению не подлежит.
- `backend/app/static/masterclass-preview.html` — стенд реальных анкет/офферов по
  выбранному клиенту. Это не старый course-preview и также остаётся.

## 2. Data Layer

### Текущий источник программы

- `content/masterclass/course/course.json` — schema version 2, 21 день, стабильный
  `courseCode = masterclass-21`, текущая `courseVersion`, атрибуты дней и массивы
  `steps`.
- `content/masterclass/course/README.md` — прямо называет JSON единственным
  источником порядка и предупреждает: изменение порядка/удаление шага требует
  версии и правила миграции прогресса.
- `docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md` —
  канонический контракт атрибутов и производных представлений.

На уровне дня реально присутствуют: `number`, `slug`, `kicker`, `title`,
`shortTitle`, `tocSummary`, `lead`, `media`, `video` (продолжительность вводного
видео), `videoId`, `image`, `intro`, `afterTitle`, `afterText`, `assignmentTitle`,
`assignmentLead`, `checks`, `nextTitle`, `nextTeaser`, `recipeDay`,
`publicationStatus`, `steps`, `implementation`.

Шаги являются union-структурой. Общие поля: `id`, `kind`, полное отображаемое имя
(`title` у статьи, `label` у приложения/оффера), `shortTitle`, `summary`,
`durationMinutes`, `required`. Типовые дополнительные поля: `status`,
`contentKind`, `contentAsset`, `videoId`, `imagePresentation`, `app`, `code`,
`completion`, `placement`, `event`, `accessResource`, `items`.

### Прогресс и риск перестановки

- `backend/app/models.py::MasterclassDayProgress` / migration
  `20260823_0017_masterclass_course_progress.py`:
  - уникальность `(user_id, day_number)`;
  - `checkmarks` — JSON вида `{ "0": true, "1": false }`;
  - день не хранит версию структуры, по которой был открыт.
- `backend/app/models.py::MasterclassStepProgress`:
  - поля `user_id`, `day_number`, `step_index`, `step_kind`, `completed_at`;
  - уникальность `(user_id, day_number, step_index)`;
  - стабильного `step_id` нет.

Следствия текущей схемы:

1. Перемещение шага меняет смысл уже сохранённого `step_index`.
2. Вставка нового шага перед пройденным делает чужой материал визуально пройденным.
3. Удаление шага оставляет прогресс с индексом, который может перейти следующему
   материалу.
4. Изменение порядка пунктов задания меняет смысл сохранённых ключей `checkmarks`.
5. Добавление нового обязательного шага в уже открытый день может задним числом
   заблокировать задание; `MasterclassDayProgress` не фиксирует revision дня.
6. `COURSE_APPS` и `COURSE_OFFERS` индексируются только по номеру дня. Если редактор
   разрешит несколько приложений или офферов одного вида в дне, поздний шаг
   перезапишет ранний в словаре.

Минимальная схема для безопасного добавления материала:

- добавить в `masterclass_step_progress` обязательный `step_id` и unique
  `(user_id, step_id)`; `step_index` оставить временно для обратной совместимости и
  аудита либо удалить отдельной поздней миграцией;
- одноразово backfill `step_id` по точному опубликованному manifest, который
  действовал в момент миграции;
- API завершения может пока принимать индекс для frontend-совместимости, но сервер
  обязан разрешать его в `step.id` активной revision и сохранять ID;
- для редактируемого состава/порядка задания нужны стабильные IDs пунктов и
  checkmarks по ID. Если это не входит в первый этап, UI обязан разрешать правку
  текста существующих пунктов, но не их перестановку/вставку.

### Существующее versioning, которое можно переиспользовать как паттерн

- `backend/app/models.py::ContentItem` и `ContentItemVersion` — неизменяемые версии
  текстового контента с `version_no`, `content_hash` и указателем
  `latest_version_id`.
- `backend/app/intensive_routes.py::save_intensive_page()` — проверяет переданную
  клиентом версию, возвращает `409` при параллельном изменении, создаёт новую
  версию и атомарно переключает latest pointer.
- `backend/app/models.py::PricingVersion` и `pricing_service.publish_draft()` —
  пример активной и архивных версий с автором и временем активации.

Эти механизмы дают готовый шаблон optimistic locking, immutable revisions и
атомарного переключения, но их таблицы семантически не подходят для структуры
курса: `ContentItemVersion` владеет телом одной статьи, а `PricingVersion` —
каталогом цен. Запись manifest в одну из них смешает владельцев данных.

Для переиспользуемого редактора курсов потребуется собственная общая модель:

- `course_definitions`: `id`, стабильный `code`, название, `active_revision_id`,
  timestamps;
- `course_structure_revisions`: `id`, `course_id`, `version_no`, `schema_version`,
  полный `manifest` JSONB, `content_hash`, `created_by`, `created_at`;
- уникальности `(course_id, version_no)` и `(course_id, content_hash)`.

Revision сама является историей изменений, поэтому отдельная audit-таблица для
первой версии не обязательна. `admin_app_edits` нельзя переиспользовать: она
обязательно связана с `target_user_id` и предназначена для изменений данных
конкретного клиента.

## 3. Similar Features

- `backend/app/intensive_routes.py` +
  `backend/app/static/intensive/intensive.js` — сохранение и немедленная публикация
  визуально редактируемой страницы. Полезны проверка общей admin-cookie, `version`
  в запросе, `409` при конфликте и запись immutable версии.
- `backend/app/pricing_routes.py`, `pricing_service.py` — независимые draft/active
  версии и запрет редактировать опубликованный снимок. Для текущего запроса владелец
  не хочет отдельный черновик, поэтому тот же принцип можно применить в одном
  действии: Save создаёт immutable revision и сразу переключает active pointer.
- `backend/app/knowledge_routes.py` и wiki `/admin/knowledge-base` — пример простой
  отдельной страницы внутри общей admin-сессии без создания второй авторизации.
- `backend/app/static/admin.html` — общий каталог модулей, куда должен войти новый
  пункт «Структура курсов».

## 4. Integration Points

1. **Runtime:** все функции `masterclass_routes.py`, использующие глобальные
   `COURSE_*`, должны получать скомпилированную активную revision через service.
   Простая замена только endpoint `/manifest` недостаточна: backend-проверки
   порядка, событий, контента и количества галочек тоже используют эти словари.
2. **Frontend:** `masterclass-first-days-preview.html` уже строит меню и дни из
   manifest, поэтому после динамического API большинство редакционных изменений
   подхватятся без изменения пользовательского UI.
3. **Контент:** whitelist `COURSE_CONTENT_FILES` сейчас строится при старте. После
   перехода он должен безопасно строиться из активной revision и всё равно
   разрешать только basename внутри `content/masterclass/source-current` плюс явно
   разрешённый imported JSON. Нельзя превращать `contentAsset` в произвольный путь.
4. **Офферы/приложения:** `placement`, `event`, `code`, `accessResource`,
   `completion`, `kind`, `required` участвуют в серверной логике. В первом простом
   UI их нужно показывать, но не делать обычными свободными текстовыми полями.
5. **Заголовки:** frontend использует `day.title` для оглавления и страницы,
   `nextDay.title` для блока следующего дня. Поле `nextTitle` фактически не
   используется этим runtime и дублирует следующий `day.title`. Его следует либо
   удалить из следующей schema revision, либо показывать только как производное
   read-only значение. `shortTitle` — осмысленное необязательное отдельное имя,
   `tocSummary` и `nextTeaser` — отдельные редакционные тексты.
6. **Названия материалов:** runtime-функция `stepTitle(step)` использует
   `shortTitle || title || label`; карточка использует `label || title`. Нужен один
   нормализованный `title` в следующей schema либо атомарная синхронизация старых
   `title/label` до миграции frontend.
7. **Админка:** новый экран использует существующую `require_admin`; определение
   клиентской почты Tilda здесь не участвует.

## 5. Existing Tests

Фреймворк — `pytest`, API проверяется через `fastapi.testclient.TestClient`, БД в
journey-тестах создаётся тестовой factory/dependency override.

- `backend/tests/test_app_assets.py::test_masterclass_manifest_is_the_complete_canonical_program()`
  проверяет schema 2, 21 последовательный день, обязательные поля и уникальные IDs.
- `backend/tests/test_masterclass_journey.py::test_course_progress_is_server_side_and_steps_are_strictly_sequential()`
  проверяет manifest API, строгий порядок индексов, оффер и чек-лист.
- `backend/tests/test_crm_auth.py::test_masterclass_course_preview_requires_authentication()`
  проверяет защиту старого маршрута.
- `backend/tests/test_crm_auth.py::test_login_creates_shared_admin_session()`
  проверяет общую `HttpOnly/Secure` cookie.

Пробелы для новой функции:

- нет теста сохранения/активации структуры без рестарта;
- нет optimistic concurrency test двух редакторов;
- нет backfill и продолжения прогресса после reorder;
- нет теста запрета изменения стабильных IDs/system fields;
- нет теста path traversal через `contentAsset`/URL-валидации медиа;
- нет теста добавления required step в уже открытый/завершённый день;
- нет теста отката на предыдущую revision.

## 6. Shared Utilities

- `backend/app/auth.py::require_admin()` — единая защита admin API через общую
  cookie или совместимый HTTP Basic.
- `backend/app/crm_routes.py::protected_file()` — `Cache-Control: no-store` для
  административных HTML/assets.
- `backend/app/intensive_routes.py::safe_href()` и `safe_image_src()` — полезные
  правила URL, но для редактора структуры нужна отдельная валидация URL полей;
  HTML-sanitizer пригодится только позднему редактору статей, не структуре.
- `backend/app/intensive_routes.py::intensive_version_hash()` — паттерн
  детерминированного SHA-256 версии.
- `backend/app/pricing_service.py::publish_draft()` — паттерн атомарного выбора
  активной версии.

## 7. Potential Problems

### Целостность и совместимость

- Модульные глобальные `COURSE_*` делают hot-edit неполным и потенциально
  противоречивым: frontend может получить одну версию, а POST completion проверит
  другую только после рестарта/между несколькими workers.
- Активная revision должна выбираться в транзакции одним pointer, а скомпилированные
  карты должны иметь ключ `(course_id, revision_id)`. Все действия одного запроса
  используют один снимок.
- Новый обязательный шаг в уже открытом дне требует заранее утверждённого правила.
  Без него пользователь может потерять доступ к заданию. Безопасный минимум:
  завершённый день никогда не открывается заново; для незавершённых дней изменение
  required-состава либо запрещается, либо применяется только к новым открытиям с
  сохранённым `revision_id` у day progress.
- Stable ID нельзя менять из UI. Новому материалу ID выдаёт сервер. Удаление
  системного шага (`dqs`, messenger, offer, questionnaire, recipes, closing review)
  должно быть запрещено обычным редактором.
- Один Save должен валидировать весь manifest до переключения pointer. Частичное
  обновление отдельных дней оставит несогласованные `next`/steps/placements.

### Безопасность

- Все GET/PUT редактора должны зависеть от `require_admin`; скрытая кнопка во
  frontend не является защитой.
- Ограничить размер JSON, длины строк, число дней/шагов/галочек и допустимые enum.
- `intro`, `afterText`, `lead` могут содержать HTML. Нужен whitelist sanitizer,
  иначе администраторская ошибка сохранит исполняемый script для клиентов.
- `videoId` должен быть идентификатором допустимого хостинга, `image` — HTTPS URL;
  нельзя принимать произвольный iframe/HTML.
- `contentAsset` должен быть basename из разрешённого каталога; `..`, абсолютные
  пути и неизвестные расширения отклоняются.
- API должен возвращать `409`, если `expected_revision_id` устарел; иначе вкладки
  браузера молча перезапишут изменения друг друга.

### Производные/дублирующиеся поля

- `nextTitle` дублирует заголовок следующего дня и уже обходится frontend через
  `nextDay.title`.
- `title`/`label` шага означают одно отображаемое имя для разных kind.
- `implementation.triggers` дублирует отдельные `step.event`; правила скидок уже
  вынесены в `OFFERS_MODULE.md`. Эти поля нельзя свободно размножать редактором.

## 8. Constraints & Infrastructure

- FastAPI + SQLAlchemy 2 + PostgreSQL; schema changes идут только Alembic migration.
- Production запускается Docker/autodeploy из `main`; ручная запись в checkout
  репозитория на сервере не является устойчивым storage.
- PostgreSQL не публикуется наружу; editor обращается только к FastAPI через Caddy.
- Tilda остаётся пользовательским входом, но административный editor использует
  только общую admin-session.
- В worktree уже есть несвязанные/параллельные изменения, включая migration
  `20260825_0023_masterclass_offer_windows.py`; номер и `down_revision` новой
  migration нужно выбирать после фиксации текущего head, не угадывать заранее.
- В проекте нет отдельной staging-среды, описанной как действующая. Версионная
  запись и rollback важнее, потому что Save будет менять production-runtime сразу.

## 9. External Libraries

Новая внешняя библиотека не требуется. Для первого минимального UI достаточно
нативных `<details>`, form controls, Fetch API и существующего FastAPI/Pydantic/
SQLAlchemy. Drag-and-drop и кнопки изменения порядка в согласованный scope не входят.

## 10. Конкретный состав реализации

### Backend и данные

- новая migration после фактического Alembic head:
  - общая таблица ревизий управляемых документов;
  - `masterclass_step_progress.step_id` + backfill + индекс/unique;
  - при принятом решении — `masterclass_day_progress.structure_revision_id`;
  - при редактируемом составе чек-листа — нормализация check progress по stable ID
    либо миграция JSON-ключей на ID;
- `backend/app/models.py` — новые модели/поля;
- новый `backend/app/course_structure_service.py` — загрузка, полная валидация,
  hash, optimistic publish, compiled revision и seed из `course.json`;
- новый `backend/app/course_structure_routes.py` либо отдельный admin-префикс в
  masterclass router:
  - `GET /admin/api/courses`;
  - `GET /admin/api/courses/{course_code}/structure`;
  - `PUT /admin/api/courses/{course_code}/structure` с
    `expected_revision_id` и полным manifest;
  - опционально `GET .../revisions` и `POST .../revisions/{id}/activate` для
    восстановления;
- `backend/app/masterclass_routes.py` — убрать зависимость runtime от глобальных
  `COURSE_*`, хранить/читать прогресс по stable step ID и использовать один снимок
  revision на запрос;
- `backend/app/main.py` — подключить новый router, если он отдельный.

### UI и маршруты

- новый минимальный `backend/app/static/course-structure-editor.html`;
- новый `course-structure-editor.js`; отдельный CSS не обязателен, но при наличии
  добавить его в защищённый allowlist `admin_asset()`;
- один длинный список из 21 `<details>` без переключения страниц;
- поля дня показываются по контракту, рядом короткая подсказка «где используется»;
- steps выводятся в фактическом порядке без элементов управления порядком;
- «Добавить материал» создаёт только обычный article/placeholder с серверным stable
  ID; системные типы остаются read-only;
- одна кнопка «Сохранить и применить»: сервер валидирует весь manifest, создаёт
  revision, атомарно активирует её и возвращает номер/время сохранения;
- `backend/app/static/admin.html`, `admin.js`/dashboard и при необходимости
  `admin-portal.html` — добавить раздел «Структура курсов».

### Удаление/замена тупикового прототипа

- удалить `backend/app/static/masterclass-course-preview.html`;
- маршрут `/admin/masterclass-course-preview` сохранить как redirect на новый
  `/admin/courses/masterclass-21/structure` для старых закладок;
- удалить старые ссылки «Предпросмотр курса»;
- `masterclass-designs.html` и route `/admin/masterclass-designs` либо удалить как
  завершённый прототип, либо явно архивировать вне production-навигации; оставлять
  ссылки на удалённый preview нельзя;
- не удалять `masterclass-first-days-preview.html`, `masterclass-preview.html` и
  `masterclass-admin.*` — это разные действующие части.

### Проверки

- unit validation полного manifest и enum/system-field invariants;
- API auth, conflict 409, idempotent same-content save, atomic activation;
- миграционный тест `step_index -> step_id` на текущем каноническом manifest;
- journey: добавить материал перед завершающим системным шагом и убедиться, что
  завершённый `step_id` системного шага не меняет смысл;
- journey для незавершённого/завершённого дня при добавлении required шага согласно
  принятой политике;
- asset/route тест нового редактора и redirect старого URL;
- полный `backend/tests` перед production deploy.
