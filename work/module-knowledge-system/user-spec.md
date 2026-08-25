---
created: 2026-08-25
status: approved
type: refactoring
owner_approval: "Владелец явно поручил после полного ТЗ сразу приступить к реализации"
---

# User-spec: модульная карта и единая память проекта

> **Executor instruction.** If the project has Project Knowledge, first read its main `SKILL.md`,
> then only the materials it routes to for this task. Read `decisions.md` if it exists. Work from
> the root of the project this spec belongs to. Implement the entire user-spec. Use the execution
> skills appropriate to the work.

Дополнительно прочитать `AGENTS.md`, `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`,
`docs/README.md` и `code-research.md`. Не создавать второй источник бизнес-логики,
runtime-редактор реестра, новую БД или монолитную админку.

## What We Are Building

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

## Why

Сейчас знания распределены между `docs/README.md`, Wiki, планами, кодом, Telegram registry,
runtime DB и памятью владельца. Новый чат может начать существующую функцию с нуля, изменить seed
вместо active runtime source, не увидеть потребителя или принять реализованный план за будущую
работу. Ручная карта уже расходится с кодом.

После изменения владелец или новый сотрудник открывает `/control`, находит область, переходит к
карточке модуля и видит простыми словами: назначение, место в системе, функции, владельца данных
и правил, входы/выходы, зависимости, канонические документы, код, таблицы, routes, админки,
текущее состояние и явно отложенные планы.

## Expected Behavior

### 1. Общий язык

#### 1.1 Иерархия

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

#### 1.2 Словарь общения

- «Сделай **модуль**» — создать самостоятельную возможность и включить её в дерево.
- «Добавь **функцию**» — добавить пользовательское поведение в существующий модуль.
- «Сделай **инструмент/страницу**» — создать интерфейс-компонент; это не автоматически модуль.
- «Измени **правило/поле/текст/действие**» — изменить часть функции.
- Python/JavaScript function называется **программным символом**.

Ниже пользовательской функции находятся правила, действия, поля и состояния. Рядом с ней —
компоненты реализации: экран, route, table, event/job и документ.

### 2. Канонический реестр

Создать `docs/modules.toml`. TOML выбран из-за `tomllib` в Python stdlib и отсутствия YAML
dependency. Реестр владеет только машинной маршрутизацией: stable module id, parent, техническим
ownership и межмодульными отношениями. Человеческий смысл и пользовательские функции живут
только в одной канонической Markdown-карточке модуля, на которую TOML ссылается полем `card`.
Generator извлекает из карточки title, summary, document status и implementation status.
Generated JSON/Markdown, UI и README не владеют этими фактами.

Запись TOML содержит:

- `id`, `parent`, `card`;
- `runtime_services`, `admin_urls`, `public_urls`;
- `owns_files` и точечные overrides для multi-module files;
- `owns_tables`, `owns_routes` и migration ownership;
- `sources` с ролью `runtime | seed | rule | copy | config | consumer`;
- `reads_from`, `writes_to`, `depends_on`, `events_in`, `events_out`.

Markdown-card содержит единственные ручные `title`, `summary`, `capabilities`,
`document_status: current|draft|planned|archived` и
`implementation_status: implemented|in_development|planned|archived`. `implemented` означает,
что функция существует в той Git-ревизии, из которой прочитана карта, а не отдельное ручное
утверждение о deploy. На production экран читает artifact из фактически запущенной ревизии,
поэтому показывает production-состав. В локальной ветке он показывает состав ветки. Временное
runtime enable/disable принадлежит соответствующему runtime source, а не статическому статусу.

Plans не перечисляются обратно в registry/card. Каждый plan сам содержит `module_id`, и
generator строит их группировку в одну сторону.

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

### 3. Автоматический инвентарь

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

#### 3.1 Граница полноты

Каждый tracked input file относится к модулю. В карту входят production, tests, tools, infra,
content, docs, legacy, prototypes и work. Orphan/overlap любого tracked input file блокирует CI;
для production runtime-кода дополнительно проверяются routes и tables. Symbols извлекаются в
пределах надёжности parser, а не перечисляются вручную. Generated outputs имеют owner
`project-knowledge-viewer`, показываются в manifest как производные, но не сканируют сами себя.

`needs_classification` разрешён только как ошибка/локальный отчёт, но не committed trash module.

#### 3.2 Проверка и влияние изменений

`python tools/module_inventory.py --check` завершается non-zero при любом tracked-file orphan,
неоднозначном owner без override, route/table без владельца, отсутствующем relation target,
несуществующей canonical path, неизвестном статусе, stale generated artifact или invalid TOML.
Исторические каталоги могут иметь документированное directory rule, но production catch-all,
скрывающий orphan, запрещён.

Каждый source с ролью `runtime`, `seed`, `rule` или `copy`, который читается другим модулем,
должен иметь явную relation. В режиме проверки Git diff generator выводит impact report:
какой канонический source изменился, какие модули его читают и какие связанные проверки/карточки
нужно просмотреть. Если автоматическое обновление потребителя невозможно, этот отчёт является
обязательным предупреждением владельцу/интегрирующему чату. Пустые relations для доказанно
общего source считаются audit-ошибкой.

Диапазон impact report задаётся явно: `--base <sha/ref> --head <sha/ref>`. В GitHub
integration/main CI используются event `before` и текущий SHA; для локальной незакоммиченной
проверки — `--base HEAD --working-tree`. Пустой неявный `git diff` не считается проверкой.

Обычная feature-ветка обновляет только свой код, module card и TOML, если semantic ownership
действительно изменился. Общие `docs/generated/*` пересобирает интегрирующий чат после rebase
всех готовых веток; stale check обязателен на integration/main, но не превращает независимые
feature-ветки в владельцев одного общего generated diff.

### 4. Wiki, дерево и `/control`

#### 4.1 Wiki

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

#### 4.2 `/control` и единый вход

`/control` остаётся админкой админок — каталогом независимых инструментов. Добавить группы:
инструменты, карта системы, как работать, планы, технические документы. Исправить относительную
Telegram-ссылку `/bot` на корректный domain-aware URL. Runtime-редактора registry нет;
специализированные админки не объединяются и не обязаны иметь один дизайн.

Один вход через backend `/admin/api/login` устанавливает cookie для `.edabalans.ru`. После него
без повторного пароля должны открываться `/control`, backend-admin/Wiki/редакторы на
`app.edabalans.ru` и Telegram admin `/bot` на `api.edabalans.ru`. NocoDB в этот контракт не
входит. Project-map API без валидной admin cookie возвращает `401` и не раскрывает карту.

### 5. Документация и источники истины

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
`cross-project`, `origin: owner-explicit` и дату. CI проверяет наличие декларации происхождения;
AGENTS запрещает агенту ставить её без явной команды. Абсолютно доказать историю разговора по
одному Git-файлу невозможно, поэтому это process rule с машинно проверяемым свидетельством.

Course structure card фиксирует `course.json` как seed, а active
`managed_document_versions` как runtime truth. Telegram верхнеуровневый registry не конкурирует
с `GLOBAL_MODULES` и Markdown registry: он проецируется или проверяется; executable DB graph
остаётся владельцем sequences/edges. Общие ORM mappings не получают второго owner.

### 6. Правила нового чата

`AGENTS.md` направляет новый чат:

1. прочитать `docs/README.md`, `PROJECT_CONTEXT.md`, `ARCHITECTURE.md` в объёме задачи;
2. определить module id;
3. открыть module card, canonical docs, active work и explicit plans;
4. проверить существующую реализацию до создания нового модуля/функции;
5. изменить canonical source, не потребительскую копию;
6. обновить module card/registry/relations в своём change; общие generated artifacts обновляет
   интегрирующий чат после сведения готовых веток;
7. выполнить проверки пропорционально риску;
8. не менять один canonical source параллельно с другим чатом.

Маленькая ясная задача выполняется сразу; средняя — с одного пакета только значимых уточняющих
вопросов без отдельного внешнего research; крупная/неоднозначная — сначала с research, затем с
вопросов и согласованного behavior/spec, после чего со свежих review. Preview — только по прямой
просьбе. Browser — для изменённого UI или пути,
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

### 7. Скиллы и стоимость процесса

Аудит сохраняется рядом со spec. Комплект Малянова не удаляется: активных дублей нет, полные
тела загружаются только при trigger. Нерабочие ссылки на отсутствующий `~/.claude`/Bash на
Windows исправляются минимально: проектный AGENTS имеет приоритет, user-spec initializer получает
portable fallback, глобальные инструкции не требуют отсутствующий source tree. Изменения
глобальных скиллов проходят skill-review отдельно и не входят в production deploy.

### 8. CI, backup и deploy

CI запускает inventory `--check` до Docker build/tests. Generated artifacts checked-in, потому
что backend image не содержит весь repository.

Обычный code-only deploy не создаёт backup: остаются ежедневные копии. Свежий pre-deploy backup
обязателен перед migration, импортом персональных данных и изменением Telegram startup seed.
Migration block сохраняется и объясняется простыми словами.

Работа ведётся в отдельном worktree из-за активного чата. Перед выпуском: синхронизация с main,
tests/audit, свежие reviews, push в main, CI, server deploy, smoke `/control`/map/card/Wiki/login`.
Feature не меняет Tilda auth, webhooks, Telegram sequences, DB schema или пользовательские данные.

## Acceptance Criteria

- [ ] Список работ покрывает весь исходный диалог.
- [ ] `docs/modules.toml` валиден и содержит иерархию модулей, чьи карточки используют только допустимые document/implementation statuses.
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
- [ ] `AGENTS.md` требует module routing, reuse search и обновление canonical source/relations/docs; generated artifacts назначены интегрирующему чату после rebase.
- [ ] Памятка объясняет module/function/component/symbol, plans и рабочие термины простыми словами.
- [ ] Plans группируются по module id; правило явного отложения закреплено в AGENTS как process rule, а не недоказуемое свойство старого файла.
- [ ] Document status и implementation status разведены; старые планы не выглядят активными.
- [ ] Course card различает seed и active runtime source.
- [ ] Telegram module list не имеет непроверяемого второго верхнего источника.
- [ ] Изменение shared canonical source создаёт impact report со всеми зарегистрированными consumers; общий source без требуемой relation блокируется.
- [ ] Plan без `module_id|cross-project`, даты или декларации `origin: owner-explicit` блокируется; AGENTS запрещает создавать декларацию без явной команды (история старых файлов автоматически не доказывается).
- [ ] Project-map API без admin session возвращает `401`.
- [ ] Один login открывает `/control`, backend Wiki/editors и Telegram `/bot` на API-domain без повторного пароля; NocoDB явно исключён.
- [ ] CI запускает inventory check до production build.
- [ ] Code-only deploy не делает backup; migration/import/Telegram startup seed делают свежий backup.
- [ ] Skill audit фиксирует состав и отсутствие дублей; user-spec initialization работает на Windows без Bash, а документационный skill соблюдает project AGENTS/docs вместо создания `.claude`-дубля.
- [ ] Релевантные suites и CI green; reviewers не находят major/critical defects.
- [ ] Production smoke подтверждает `/control`, map/card, documents и admin session без изменения данных.

## Constraints

- Новая БД, SaaS, runtime editor, call graph, MAX, новый сайт и отдельный ЛК не создаются.
- Registry/docs не содержат secrets, PII, dumps или реальные выгрузки.
- Project-map API использует текущую admin session и доступен только через Caddy.
- Global generated outputs пересобираются только интегрирующим потоком после rebase.

## Risks

- Широкие globs могут спрятать orphan; production catch-all запрещён без tests.
- Multi-module files требуют route/table/symbol overrides.
- Generated artifacts могут устареть; CI diff check обязателен.
- Реестр не копирует runtime graph, цены, тексты курса и другие изменяемые факты.
- Symbol list информационный и ограничен parser; capabilities остаются semantic частью card.
- Параллельные чаты не меняют один canonical source одновременно.
- Секреты, пароли, PII, дампы и реальные выгрузки запрещены.
- Новый сайт, MAX, отдельный ЛК, развитие NocoDB и единый NocoDB login вне scope.

## Accepted Decisions

Полный журнал — `decisions.md`: module ≠ file; полнота через generated inventory; Wiki — view;
editor registry отсутствует; tracked files имеют owner; «функция» — пользовательская возможность;
ошибка карты не ломает документы; NocoDB отложен.

## Testing

**Unit tests:** обязательны для TOML/card schema, status/relation/path validation, file-owner
precedence, Python AST и JS named-function extraction, route/table discovery, plan provenance,
orphan/overlap fixtures, impact report и deterministic serialization. Это чистая логика без
network/DB; unit boundary даёт точные и дешёвые ошибки.

**Integration tests:** обязательны для `knowledge_routes` + checked-in artifact + текущей admin
auth: успешный project-map response, `401` без cookie, invalid/missing artifact, Wiki fallback,
module-card data и `/control` links. Здесь нужна собранная FastAPI app/static surface, поэтому
unit-тест недостаточен, но настоящий browser ещё не нужен.

**E2E/browser:** один сценарий: войти через backend login, открыть `/control`, Wiki module card и
Telegram `/bot` на другом поддомене без повторного пароля. Он нужен только для междоменной cookie,
Caddy URL и фактического UI; остальные ветки дешевле и надёжнее проверяются unit/integration.

**Existing suites:** backend и Telegram pytest запускаются после новых focused tests, потому что
меняются общие admin/docs surfaces и production CI. Повторное ручное прокликивание всех админок
не требуется.

## Verification

### Agent Verification

| Step | Expected Result |
|---|---|
| 1. Запустить unit suite генератора на real repo и orphan/overlap/invalid fixtures | Schema, ownership, symbols, tables/routes, plan provenance и impact report проходят; дефектные fixtures завершаются ожидаемой ошибкой. |
| 2. Дважды выполнить generation, затем `--check` и `git diff --exit-code -- docs/generated` | Второй запуск не меняет JSON/Markdown; outputs валидны и не устарели. |
| 3. Проверить полный inventory query/report | Каждый tracked input file имеет одного owner; derived outputs отмечены отдельно; все найденные production routes/tables принадлежат модулю. |
| 4. Запустить backend integration tests | Authorized API отдаёт schema-versioned map; anonymous API получает `401`; missing/invalid artifact не ломает Markdown reader; `/control` содержит правильные ссылки. |
| 5. Запустить Telegram registry consistency tests | Верхний module list соответствует общему registry, а DB graph остаётся источником sequence details. |
| 6. Запустить documentation/status/link audit | Cards, plans, statuses, sources и relations валидны; archived plans не отображаются как active. |
| 7. Запустить portable user-spec initializer test на Windows и skill reviewers | Feature folder создаётся без Bash; документационный routing не требует отсутствующий `.claude`; skill form/logic/simplicity clean. |
| 8. Запустить все backend и Telegram pytest suites и production workflow-equivalent checks | Все suites green; inventory check выполняется до build, migration block не ослаблен. |
| 9. Проверить deploy classifier static fixtures/diffs | Code-only change не создаёт backup; migration, import procedure и изменение seed/его startup call требуют backup. |
| 10. Выполнить один browser smoke после deploy | Один login открывает `/control`, backend Wiki/editors и `https://api.edabalans.ru/bot`; map/card читаемы; повторного пароля нет; NocoDB не проверяется. |
| 11. Сверить deployed revision/CI и выполнить health checks | Production запустил проверенный commit; пользовательские данные, Tilda auth и Telegram sequences не изменились. |

Отдельная User Verification не требуется: владелец прямо разрешил автономную реализацию и
production-выпуск, а все наблюдаемые результаты проверяются агентом и автоматическими tests.
