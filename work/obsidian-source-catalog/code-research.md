# Исследование источников каталога Obsidian

Дата: 16.09.2026. Исследование файлов, без публикации и изменения первоисточников.
Корневая рабочая папка находится на грязной `codex/markiting`; ниже состояние `origin/main` явно отделено от файлов рабочей папки. Live-БД не проверялась, статусы документов не являются подтверждением текущей production-конфигурации.

## Entry Points

- `docs/README.md` — действующий вход в документацию. Каталог Obsidian должен ссылаться на этот маршрут, а не заменять его новой базой правил.
- `docs/modules.toml` — существующий реестр `module_id`, родителей, ownership, зависимостей, канонических источников и admin-каталога. `docs/knowledge-base/modules/catalog/*.md` содержат человеческие названия, состояния и функции; `docs/generated/module-map.md` и `module-inventory.json` являются производными.
- `content/masterclass/editorial/README.md` и `program.md` в main — подготовленный редакторский канон курса. Program владеет порядком, названиями и связями; days владеют текстами дней; materials — самостоятельными материалами.
- `.codex-worktrees/masterclass-markdown-canon-20260912/content/masterclass/editorial/` — найденная физическая рабочая копия MD-пака. По данным родительского потока связана с `codex/masterclass-markdown-publish-20260912`; нельзя автоматически принимать её состояние за опубликованное.
- `work/free-intensive-rebuild/README.md` — карта происхождения и редакторских версий интенсива, не команда публикации.
- `work/calorie-course-rebuild/README.md` — карта исходников, решений и редакторских версий калорийного курса.
- `work/training-course-design/00-version-map.md` — карта архитектуры и степени принятия тренировочного курса.

## Data Layer и текстовые пакеты

### Мастер-класс

- `content/masterclass/editorial/days/` содержит 20 файлов дней в main. Идентификатор курса `masterclass-21` не доказывает наличие 21-го учебного дня: документация описывает 20-дневную программу. Каталог должен показывать реально найденный состав и отдельную неопределённость, а не генерировать отсутствующий день.
- `content/masterclass/editorial/materials/` содержит статьи, анкеты, приложения, допродажи и заглушки. Тип и HTML-комментарии `step_id`/`EMBED` задают техническую привязку; анкета/DQS не становятся обычной статьёй при показе в Obsidian.
- `content/masterclass/editorial/OPEN_QUESTIONS.md` перечисляет непринятые названия, заглушки, предложения, права дней 7/15 и новый ID. Наличие канонической папки не означает завершённую приёмку или опубликованность.
- `source-current/` упомянута README как миграционный источник, не второе место редактирования; сохранять ссылки на происхождение.

### Интенсив

- `work/free-intensive-rebuild/SOURCE_BASELINE.md` и `handoff/` — исходная авторская база и прямые решения.
- `history/01-rejected-first-assembly-2026-08-28/` — отвергнутая первая сборка, сохранённая история.
- `rebuild-v2/` — восемь производных материалов, не приняты целиком.
- `rebuild-v3-source-isolated/` — отдельный source-first эксперимент дня 4.
- `versions/03-current-owner-review-2026-08-31/` — составной пакет просмотра: дни 1–3 v2, день 4 v3. README помечает `owner_review_pending`; не объявлять утверждённым.
- `intensive-pages-v2/day-1.md` … `day-4.md`, `bot-messages/`, `bot-message-catalog-v3.md` существуют в рабочей папке. Версию каждого файла сверять по каноническому runtime и карте версий, не выбирать по суффиксу v2/v3 или mtime.
- Живые `/intensive/day-1` … `/intensive/day-4` принадлежат `products.intensive`; редакторский пакет не изменяет их автоматически.

### Калории

- `content/calories/course/course.json` — seed/fallback пятиэтапного runtime; активная серверная структура хранится в `managed_document_versions`, ключ `calories`. Документ фиксирует `launchReady=false` и placeholders, без live-проверки нельзя утверждать сегодняшнее состояние.
- `work/calorie-course-rebuild/source-tilda-complete/` — v0: 18 текстовых лекций, 3 видеокарточки, исходный порядок и 58 изображений по README; `source-transcripts/` — три отдельных исходника видео. `source-tilda-complete/verify_archive.py` и `verification.md` проверяют архивную комплектность.
- `rebuild-v5-editorial-2026-08-30/` — 14 черновиков на 5 этапов, не прочитаны/не приняты владельцем. `content/calories/course/README.md` содержит точную таблицу step.id→файл v5, не разрешение публиковать.
- `rebuild-v6-owner-restructure-2026-08-30/` — 14 материалов на 4 этапа, последняя полная текстовая сборка, итоговые тексты не приняты.
- `rebuild-v7-structure-2026-09-01/` — структурный checkpoint; README отдельно фиксирует содержательное отвержение после частичного просмотра.
- `rebuild-v8-owner-compressed-2026-09-01/` — 10 материалов, reviewed_with_corrections, заменена v9.
- README в main описывает v9 как текущую структуру просмотра: 4 этапа, 12 материалов, не принята. Точный путь v9 брать из полной таблицы README при построении каталога, не выводить из шаблона имени.
- `owner-decisions-2026-08-28.md`, `owner-decisions-2026-08-30.md`, `owner-decisions-2026-09-01.md` и последующие раунды — отдельные прямые решения. Не перезаписывать ранние версии.

### Тренировки

- `content/training/reference/README.md` и `reference/transcripts/` — исходники эфира; полный ресурс зарегистрирован как `knowledge://resource/training.stream-full.raw`, короткий — excerpt, не новый эфир.
- `work/training-course-design/sources/author-posts/catalog.md` — 38 дословных публикаций по карте версий; не читать/перекопировать весь корпус для одного каталога.
- `drafts/README.md` — 14 черновиков checkpoint v2.1, не финальные читательские тексты.
- `15-course-program-v3.md` (точное наличие сверять реестром файлов), `17-course-program-v3.1-tree.md` — подробная архитектура и принятая форма прохождения. Принятие дерева не означает принятие текстов, чисел и программ недель.
- `18-course-content-blueprint-v1.md` и `19-course-content-blueprint-audit-v1.md` — сценарный checkpoint v3.2, не тексты на публикацию. Курс обозначен planned и не реализован в ЛК по карте версий.

## Integration Points: мессенджеры

- `docs/knowledge-base/modules/telegram/WELCOME_INTENSIVE.md`, `START_WELCOME_ROUTING.md` — канонические условия Welcome и старта; published runtime graph владеет фактическими сообщениями, задержками и переходами.
- `telegram-bot/service/app/graph.py`, `seed.py` — движок и начальные/согласованные тексты. Seed содержит `WELCOME_CODE = welcome_intensive`, `POSTPURCHASE_CODE = postpurchase_masterclass`, templates и editor metadata. Seed не обязательно равен вручную изменённой опубликованной серверной версии.
- `messaging.telegram.intensive` и `messaging.max` используют один опубликованный Welcome-граф. MAX не проверяет Telegram-подписку и не закрепляет финальный пост; там выбирается полная промежуточная версия. Это два представления с явными отличиями, не два независимых канона.
- `docs/knowledge-base/modules/max/START_AND_ATTRIBUTION.md` — точный контракт MAX. Массовые и послепокупочные сообщения по карточке `messaging.max.md` Telegram-only; не выдумывать пустые MAX-аналоги.
- `PREPURCHASE_NURTURE.md`, `CUSTOMER_LIFECYCLE_TECHNICAL_SPEC.md` — сообщения до покупки и централизованная остановка продаж при оплате.
- `POST_PURCHASE_MASTERCLASS.md` — события после покупки, onboarding, DQS, офферы, саморевью, ограничения test-only. Граф выключен как самостоятельная sequence, отправляет outbox-dispatcher; линейное прочтение всех узлов не равно реальным правилам доставки.
- `messaging.telegram.postmasterclass` — отключённый пустой каркас. Не создавать отсутствующие сообщения через 2/4/7 дней.
- Каталог должен отдельно показывать текст, кнопки/медиа, платформу, события/условия, задержки, статус версии и источник. Персональные подстановки не превращать в реальные данные участника.

## Shared Utilities и публикация

- `backend/scripts/bootstrap_masterclass_editorial.py` — первоначальное копирование редакторского пака, не перезаписывает существующие файлы; `parse_program()` — существующий парсер программы.
- `backend/scripts/validate_masterclass_editorial.py: main()` — проверяет файлы, заголовки, типы и stable ID/EMBED без публикации.
- `backend/scripts/publish_masterclass_editorial.py: compile_manifest(current, *, next_version)` — компилирует существующую структуру и сохраняет неуказанные шаги скрытыми; `new_article_step`/`new_placeholder_step` добавляют техшаги. Скрипт существует в main, несмотря на README «нужен синхронизатор»; расхождение зарегистрировать, не редактировать источники в этой задаче.
- `tools/publish_course_material.py` — чтение, версионная публикация и restore обычных текстовых материалов. `backend/app/course_material_routes.py` предоставляет GET list/detail/versions, PUT publish и POST restore под `/admin/api/courses/{course_code}/materials`.
- `backend/app/article_markup.py` — общий renderer/sanitizer; `docs/knowledge-base/ARTICLE_STANDARD.md` — канонические правила оформления. Не менять разметку при каталогизации.
- `tools/install_edabalans_writer_skill.py`, `install_edabalans_librarian_skill.py` — managed установка навыков из источников. Каталог должен различать source package и установленный runtime, не монтировать plugin cache как редактируемый канон.

## Навыки и источники истины

- `content/author-voice/skill/edabalans-writer/SKILL.md` и `assets/skill-manifest.json` — writer source package; соседние `writer-contract-v1.md`, `editing-modes-v1.md`, `article-component-router.md` — связанные каноны platform.content.
- `content/knowledge/skill/edabalans-librarian/SKILL.md` — librarian source package platform.knowledge. Глобальная установка не делает этот отдельный runtime самостоятельным владельцем правил.
- `C:/Users/Segey/.codex/skills/` — пользовательские установленные packages; `.system` и plugin caches — отдельные классы. Для каждого навыка собирать SKILL.md, локальные references/scripts/assets и происхождение, без редактуры или новой классификации универсальности.
- `docs/CONTENT_CATALOG.md` и `docs/KNOWLEDGE_LIBRARY.md` — existing publication families/provenance и карта источников. Библиотека ссылается на `content://`, `knowledge://`, `repo://`, не копирует все тексты в новую DB.

## Existing Tests

- `backend/tests/test_masterclass_editorial_publish.py` — тесты компиляции/публикационного поведения MD-канона; не запускать publish ради каталога.
- `tools/tests/test_publish_course_material.py` — публикационный CLI и версии.
- `telegram-bot/service/tests/test_seed_lifecycle.py` — lifecycle seed; не доказывает live-версию графа.
- `tools/tests/test_catalog_saved_notes_editorially.py` — существующая обработка редакторского каталога заметок.

## Potential Problems / ограничения

1. Старый грязный root, main, отдельная рабочая копия и production — разные состояния. Каждая ссылка каталога требует source location/ref и статуса проверки; нельзя выдать read-only main blob за live editable path.
2. Не менять/удалять/переносить первоисточники, не оптимизировать инструкции, не выбирать победителя semantic conflict без решения владельца. Pass внутренней проверки и факт коммита не равны owner approval.
3. Не получать реальные персональные выгрузки, токены, participant substitutions; `/srv/edabalans-private` исключён. Авторизованный read-only экспорт опубликованных общих текстов допустим только после выбора безопасного инструмента.
4. При дословном MD-представлении серверных текстов сохранять ID, version/hash, дату, original format, buttons/media/conditions отдельно и помечать projection. Нельзя самовольно заменить опубликованный серверный канон локальным экспортом.
5. В каталог включать исторические и непринятые версии рядом с действующим состоянием, не прятать их и не создавать фиктивный единый утверждённый текст.
6. Существующие docs/generated — производные. Новый обзор Obsidian должен ссылаться на факты и владельцев, а не переписывать весь массив в новую альтернативную документацию.
