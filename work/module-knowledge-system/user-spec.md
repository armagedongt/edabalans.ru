---
created: 2026-08-25
status: approved
type: refactoring
owner_approval: "Владелец явно поручил после полного ТЗ сразу приступить к реализации"
---

# User-spec: модульная карта и единая память проекта

> Перед реализацией прочитать `AGENTS.md`, `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`,
> `docs/README.md`, `decisions.md` и `code-research.md`. Реализовать весь spec. Не создавать
> второй источник бизнес-логики, runtime-редактор реестра, новую БД или монолитную админку.

## 1. Что строим

Создаётся единая система навигации и памяти проекта:

1. канонический структурированный реестр функциональных модулей в Git;
2. автоматически извлекаемый технический инвентарь репозитория;
3. детерминированные JSON- и Markdown-представления;
4. дерево и карточки модулей в существующей Wiki;
5. понятный каталог маленьких административных инструментов в `/control`;
6. короткий маршрутизатор каждого нового чата в `AGENTS.md`;
7. человекочитаемая памятка владельца и нормализованная документация;
8. CI-аудит, который не позволяет production-объектам остаться без владельца;
9. пропорциональные правила tests/deploy/backups и аудит глобальных скиллов.

Система не является новой базой знаний. Канонические Markdown, код и runtime-данные остаются
владельцами своих фактов. Реестр хранит смысл, владение и ссылки, generated inventory —
техническую проекцию исходников.

## 2. Зачем

Сейчас знания распределены между `docs/README.md`, Wiki, планами, кодом, Telegram registry,
runtime DB и памятью владельца. Новый чат может начать существующую функцию с нуля, изменить seed
вместо active runtime source, не увидеть потребителя или принять реализованный план за будущую
работу. Ручная карта уже расходится с кодом.

После изменения владелец или новый сотрудник открывает `/control`, находит область, переходит к
карточке модуля и видит простыми словами: назначение, место в системе, функции, владельца данных
и правил, входы/выходы, зависимости, канонические документы, код, таблицы, routes, админки,
текущее состояние и явно отложенные планы.

## 3. Общий язык

### 3.1 Иерархия

1. **Платформа** — весь `edabalans.ru`.
2. **Область / продукт** — крупная ветка: platform core, продукты, messaging, admin surfaces,
   operations.
3. **Модуль** — самостоятельная функциональная возможность с целью, входами/выходами,
   правилами или собственным жизненным циклом.
4. **Компонент** — техническая часть модуля: экран, API route, таблица, job, скрипт, документ,
   config, migration, frontend/backend file.
5. **Программный символ** — Python class/function/method либо надёжно извлекаемая именованная
   JavaScript function.

Модуль находится внутри области/продукта и может содержать вложенный модуль, если у дочерней
возможности самостоятельный смысл и жизненный цикл. Файл не становится модулем только из-за
существования.

### 3.2 Словарь общения

- «Сделай **модуль**» — создать самостоятельную возможность и включить её в дерево.
- «Добавь **функцию**» — добавить пользовательское поведение в существующий модуль.
- «Сделай **инструмент/страницу**» — создать интерфейс-компонент; это не автоматически модуль.
- «Измени **правило/поле/текст/действие**» — изменить часть функции.
- Python/JavaScript function называется **программным символом**.

Ниже пользовательской функции находятся правила, действия, поля и состояния. Рядом с ней —
компоненты реализации: экран, route, table, event/job и документ.

## 4. Канонический реестр

Создать `docs/modules.toml`. TOML выбран из-за `tomllib` в Python stdlib и отсутствия YAML
dependency. Реестр — единственный владелец stable module id, иерархии, человеческого смысла,
статусов, функций, правил владения и межмодульных отношений. Generated JSON/Markdown, UI и
README не владеют этими фактами.

Каждый module card содержит:

- `id`, `name`, `summary`, `kind`, `parent`;
- `document_status`: `current | draft | planned | archived`;
- `implementation_status`: `implemented | implemented_disabled | in_development | planned | archived`;
- `capabilities` — пользовательские функции простыми словами;
- `canonical_docs`, `plans`, `owner_notes` — ссылки, не копии;
- `runtime_services`, `admin_urls`, `public_urls`;
- `owns_files` и точечные overrides для multi-module files;
- `owns_tables`, `owns_routes` и migration ownership;
- `sources` с ролью `runtime | seed | rule | copy | config | consumer`;
- `reads_from`, `writes_to`, `depends_on`, `events_in`, `events_out`.

Parent и relation targets обязаны существовать. У объекта один module owner, потребителей много.

Первоначальная структура покрывает platform core (identity/CRM, products/pricing,
payments/Tilda, access/legal, app auth, managed documents, content catalog); продукты (DQS,
strength, metabolism/calories, free intensive, Masterclass); Masterclass (course
content/structure, runtime/progress, questionnaires, offers/upsells, messenger links);
messaging/Telegram (attribution/start, intensive, pre-purchase, post-purchase,
post-masterclass, direct support, broadcasts, engine/media/tracking); admin surfaces (control,
project knowledge, technical NocoDB); operations (DB/migrations, deploy/CI, proxy/domains,
backups/restore, imports/tools); planned-only Telegram lottery/quiz.

NocoDB отражается как существующий инструмент, но его развитие и общий вход вне scope.

## 5. Автоматический инвентарь

Создать stdlib CLI `tools/module_inventory.py`:

- читает `docs/modules.toml`;
- получает tracked-file список через Git;
- классифицирует каждый tracked input file; ignored/vendor/cache не tracked, а собственные
  `docs/generated/*` перечисляются отдельно как `derived_outputs`, без рекурсивного разбора;
- Python AST извлекает classes, functions/methods, FastAPI decorators, `__tablename__`,
  `op.create_table`;
- консервативный regex извлекает именованные JS functions;
- HTML/CSS/inline callbacks наследуют владельца файла;
- file/route/table/symbol overrides разрешают `models.py`, `crm_routes.py`,
  `masterclass_routes.py` и Telegram `main.py`;
- генерирует `docs/generated/module-inventory.json` и `docs/generated/module-map.md`;
- сортирует данные детерминированно без времени запуска.

Полный static call graph не строится: semantic relations задаются реестром; imports и symbols —
только evidence.

### 5.1 Граница полноты

Каждый tracked input file относится к модулю. В карту входят production, tests, tools, infra,
content, docs, legacy, prototypes и work. Orphan/overlap любого tracked input file блокирует CI;
для production runtime-кода дополнительно проверяются routes и tables. Symbols извлекаются в
пределах надёжности parser, а не перечисляются вручную. Generated outputs имеют owner
`project-knowledge-viewer`, показываются в manifest как производные, но не сканируют сами себя.

`needs_classification` разрешён только как ошибка/локальный отчёт, но не committed trash module.

### 5.2 Проверка

`python tools/module_inventory.py --check` завершается non-zero при любом tracked-file orphan,
неоднозначном owner без override, route/table без владельца, отсутствующем relation target,
несуществующей canonical path, неизвестном статусе, stale generated artifact или invalid TOML.
Исторические каталоги могут иметь документированное directory rule, но production catch-all,
скрывающий orphan, запрещён.

## 6. Wiki, дерево и `/control`

### 6.1 Wiki

Существующая Wiki остаётся Git-backed reader. Добавить режимы:

- «Карта системы» — дерево по `parent`, поиск, filters и module cards;
- «Документы» — текущий Markdown reader;
- «Как работать» — памятка владельца;
- «Планы» — только явные планы по module id;
- «Техническое» — operations/architecture/reference.

Карточка показывает человеческую часть первой. Files, symbols, routes и tables находятся в
раскрываемом техническом блоке и берутся из generated inventory.

Backend добавляет защищённый существующей admin-сессией `GET /admin/api/project-map`. Runtime
только читает checked-in JSON; repository scan в request path запрещён. Если JSON отсутствует,
повреждён или имеет неизвестную schema version, API возвращает контролируемую ошибку, UI
показывает «Карта временно недоступна» и оставляет рабочим Markdown reader.

### 6.2 `/control`

`/control` остаётся админкой админок — каталогом независимых инструментов. Добавить группы:
инструменты, карта системы, как работать, планы, технические документы. Исправить относительную
Telegram-ссылку `/bot` на корректный domain-aware URL. Runtime-редактора registry нет;
специализированные админки не объединяются и не обязаны иметь один дизайн.

## 7. Документация и источники истины

- `AGENTS.md` — короткие обязательные правила и routing нового чата.
- `docs/README.md` — стартовый навигатор человека и агента.
- `docs/modules.toml` — semantic registry.
- `docs/knowledge-base/` — current человеческий смысл продуктов/модулей.
- `docs/plans/` — только явно отложенное владельцем.
- `docs/OPERATIONS.md` — deploy, backup, restore и production checks.
- `work/` — временные исследования/spec активной работы.
- `docs/generated/` — derived artifacts, не ручной source.

Отдельной редактируемой Wiki-БД нет.

Каждый canonical Markdown получает `current|draft|planned|archived`; состояние реализации
хранится отдельно. Сложные исторические status strings нормализуются, полезная подробность
переносится в отдельное поле/абзац. Старые планы документационной системы после реализации
архивируются со ссылкой на новый канон; реализованное не остаётся ложным future plan.

Идея попадает в plans только после явного «положи в планы» или ясного отложения «на потом».
Незавершённая/незадеплоенная работа планом не становится. Каждый plan содержит `module_id` или
`cross-project`.

Course structure card фиксирует `course.json` как seed, а active
`managed_document_versions` как runtime truth. Telegram верхнеуровневый registry не конкурирует
с `GLOBAL_MODULES` и Markdown registry: он проецируется или проверяется; executable DB graph
остаётся владельцем sequences/edges. Общие ORM mappings не получают второго owner.

## 8. Правила нового чата

`AGENTS.md` направляет новый чат:

1. прочитать `docs/README.md`, `PROJECT_CONTEXT.md`, `ARCHITECTURE.md` в объёме задачи;
2. определить module id;
3. открыть module card, canonical docs, active work и explicit plans;
4. проверить существующую реализацию до создания нового модуля/функции;
5. изменить canonical source, не потребительскую копию;
6. обновить registry/docs/relations/generated artifacts в том же change;
7. выполнить проверки пропорционально риску;
8. не менять один canonical source параллельно с другим чатом.

Маленькая ясная задача выполняется сразу; средняя начинается с исследования и одного пакета
только значимых вопросов; крупная/неоднозначная — с research, согласованного behavior/spec и
свежих review. Preview — только по прямой просьбе. Browser — для изменённого UI или пути,
который нельзя дешевле проверить тестом. Если остановка перед сервером не запрошена и маршрут
согласован, допустим автономный commit/push/deploy.

Памятка объясняет:

- `local` — изменения только в рабочей копии;
- `preview` — специально показанный предварительный результат;
- `tests` — автоматические проверки;
- `commit` — Git-контрольная точка;
- «отправь на сервер» — выполнить нужные commit/push/deploy до production;
- `production` — версия реальных пользователей;
- `migration` — отдельное изменение структуры/обязательных данных БД;
- `rollback` — возврат к предыдущей рабочей версии.

`push` владельцу не нужен как команда: это технический шаг между commit и deploy.

## 9. Скиллы и стоимость процесса

Аудит сохраняется рядом со spec. Комплект Малянова не удаляется: активных дублей нет, полные
тела загружаются только при trigger. Нерабочие ссылки на отсутствующий `~/.claude`/Bash на
Windows исправляются минимально: проектный AGENTS имеет приоритет, user-spec initializer получает
portable fallback, глобальные инструкции не требуют отсутствующий source tree. Изменения
глобальных скиллов проходят skill-review отдельно и не входят в production deploy.

## 10. Tests, CI, backup и deploy

Tests: unit TOML/schema, relation, glob precedence, AST/route/table extraction; fixtures orphan,
overlap и override; deterministic generation/`--check`; integration auth/API, missing-invalid
artifact, Wiki module card/fallback; `/control` link assertions; один browser smoke изменённого UI;
существующие backend/Telegram suites. Мышкой каждый экран не проверяется.

CI запускает inventory `--check` до Docker build/tests. Generated artifacts checked-in, потому
что backend image не содержит весь repository.

Обычный code-only deploy не создаёт backup: остаются ежедневные копии. Свежий pre-deploy backup
обязателен перед migration, импортом персональных данных и изменением Telegram startup seed.
Migration block сохраняется и объясняется простыми словами.

Работа ведётся в отдельном worktree из-за активного чата. Перед выпуском: синхронизация с main,
tests/audit, свежие reviews, push в main, CI, server deploy, smoke `/control`/map/card/Wiki/login`.
Feature не меняет Tilda auth, webhooks, Telegram sequences, DB schema или пользовательские данные.

## 11. Критерии приёмки

- [ ] Список работ покрывает весь исходный диалог.
- [ ] `docs/modules.toml` валиден и содержит первоначальную иерархию current/development/planned модулей.
- [ ] Каждый tracked input file виден с одним owner либо даёт audit-ошибку; orphan/overlap отсутствует во всех tracked-каталогах, а generated outputs отдельно отмечены как derived.
- [ ] Все найденные SQLAlchemy tables и FastAPI routes имеют одного владельца.
- [ ] Python symbols и именованные JS functions извлекаются; inline code наследует file owner.
- [ ] Два запуска генератора дают идентичные artifacts.
- [ ] `--check` находит stale output, invalid relation, orphan и overlap.
- [ ] JSON имеет schema version, modules, relations, files, routes, tables и symbols.
- [ ] Wiki показывает module tree, search/status filter, human card и раскрываемый inventory.
- [ ] Ошибка карты не ломает Markdown reader.
- [ ] `/control` остаётся каталогом маленьких инструментов, имеет map/guide/plans/technical links и правильный Telegram host.
- [ ] Runtime-редактора registry и отдельной Wiki-БД нет.
- [ ] `AGENTS.md` требует module routing, reuse search и обновление canonical source/relations/docs/generated artifacts.
- [ ] Памятка объясняет module/function/component/symbol, plans и рабочие термины простыми словами.
- [ ] Plans создаются только явно и группируются по module id.
- [ ] Document status и implementation status разведены; старые планы не выглядят активными.
- [ ] Course card различает seed и active runtime source.
- [ ] Telegram module list не имеет непроверяемого второго верхнего источника.
- [ ] CI запускает inventory check до production build.
- [ ] Code-only deploy не делает backup; migration/import/Telegram startup seed делают свежий backup.
- [ ] Skill audit фиксирует состав, отсутствие активных дублей и реальные Windows-проблемы.
- [ ] Релевантные suites и CI green; reviewers не находят major/critical defects.
- [ ] Production smoke подтверждает `/control`, map/card, documents и admin session без изменения данных.

## 12. Риски и ограничения

- Широкие globs могут спрятать orphan; production catch-all запрещён без tests.
- Multi-module files требуют route/table/symbol overrides.
- Generated artifacts могут устареть; CI diff check обязателен.
- Реестр не копирует runtime graph, цены, тексты курса и другие изменяемые факты.
- Symbol list информационный и ограничен parser; capabilities остаются semantic частью card.
- Параллельные чаты не меняют один canonical source одновременно.
- Секреты, пароли, PII, дампы и реальные выгрузки запрещены.
- Новый сайт, MAX, отдельный ЛК, развитие NocoDB и единый NocoDB login вне scope.

## 13. Принятые решения

Полный журнал — `decisions.md`: module ≠ file; полнота через generated inventory; Wiki — view;
editor registry отсутствует; tracked files имеют owner; «функция» — пользовательская возможность;
ошибка карты не ломает документы; NocoDB отложен.
