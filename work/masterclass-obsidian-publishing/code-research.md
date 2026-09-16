# Исследование: Markdown → публикация всего Мастер-класса

Дата: 16.09.2026. Статус документа: `draft`.

## Граница и проверенная ревизия

Исследован код `origin/main` (`99051db9b3e3435861e220d95e2cb7a516481157`), а не работающий сервер. Дополнительно прочитан редакторский пакет `.codex-worktrees/masterclass-markdown-canon-20260912/content/masterclass/editorial/`. Проверок БД, production, ключей и пользовательских данных не было. Исходники не менялись.

Контекст: владелец хочет редактировать программу, названия, тексты дней, задания, самостоятельные материалы и изображения непосредственно в Markdown; публикация только по явной команде, а не при сохранении файла. Требуется связать результат с существующим ЛК и предоставить минимальное действие публикации, в том числе из Obsidian.

Основные module owners: `products.masterclass.course`, `products.masterclass.runtime`, `products.masterclass.questionnaires`, `products.masterclass.offers`, `platform.content`. Карточки находятся в `docs/knowledge-base/modules/catalog/`; module ownership задаётся `docs/modules.toml`.

## 1. Entry Points

### Редакторские исходники

- `content/masterclass/editorial/program.md` — authoring truth названий дней, названий/порядка материалов, примерной длительности, `step_id` и типов. Формат строки материала сейчас строго задан: `1. [Название](materials/имя.md) · ≈ 8 мин` и следующий HTML-комментарий `step_id: ...; type: ...`.
- `content/masterclass/editorial/days/*.md` — текст над вводным медиа, под ним, перед заданиями и пункты заданий. Раздел «Материалы дня» дублирует список для чтения; publisher не использует его как источник порядка.
- `content/masterclass/editorial/materials/*.md` — самостоятельные статьи, вводный текст анкет/приложений/предложений, две заглушки доступа. Заголовок H1 повторяет название из программы и валидатор требует совпадения.
- В проверенной отдельной рабочей папке: **20 файлов дней, 52 файла материалов, 50 `step_id` в программе**. Разница — две заглушки доступа без обычного `step_id`. Код курса `masterclass-21` остаётся историческим идентификатором; parser требует именно дни 1–20.

### Локальные scripts

- `backend/scripts/bootstrap_masterclass_editorial.py`: `parse_program() -> tuple[list[dict], dict[str, dict]]`. Это одновременно существующий parser и первоначальный bootstrap. `main()` создаёт только отсутствующие файлы; повторный запуск не переписывает существующую редактуру. Пути `EDITORIAL`, `SOURCE`, `COURSE` вычислены относительно местоположения script, входной `--editorial-root` отсутствует.
- `backend/scripts/validate_masterclass_editorial.py`: `main() -> None`. Локально проверяет названия, типы, наличие ID, файлов, EMBED-маркеров и двух заглушек. Выводит `OK: 20 дней, 50 материалов и 2 заглушки доступа`. Не проверяет загрузку изображений и не создаёт пакет HTTP-публикации.
- `backend/scripts/publish_masterclass_editorial.py`: `compile_manifest(current: dict, *, next_version: int) -> tuple[dict, list[str]]`, `apply_day_copy(manifest: dict, days: list[dict]) -> None`, `editorial_body(path) -> str`, `special_prelude(path, material_type: str) -> str`, `migrate_step_progress(db, before: dict, after: dict) -> int`. Собирает редакцию на основе active manifest и публикует структуру со статьями в одной DB-транзакции. Без `--publish` выполняет сборку/рендеринг, но всё равно открывает `SessionLocal` и читает DB; это не чистый офлайн dry-run.
- `tools/publish_course_material.py`: `api_request(args, method, path, payload=None) -> dict`, `verify_publish_gate(file_path, pack_path, report_path) -> dict`. HTTP CLI для отдельной обычной статьи: `list`, `get`, `publish`, `versions`, `restore`. Для `publish` обязательны `--pack` и `--validation-report`; wrapper для редакторского пакета должен учитывать этот контракт, а не обходить его.

### HTTP API

- `backend/app/course_material_routes.py`: `PUT /admin/api/courses/{course_code}/materials/{step_id}` принимает `{expected_version, content, format}`. `GET` получает материал/список/историю, `POST .../versions/{version_no}/restore` восстанавливает редакцию новой версией. Все admin routes используют `require_admin`; `format` только `markdown|html`, текст до 500 000 символов и отдельно ограничен 500 000 байт в service.
- `backend/app/course_structure_routes.py`: `GET/PUT /admin/api/courses/{course_code}/structure`, `POST .../structure/versions/{version_no}/restore`. PUT принимает весь `{expected_version, manifest}`, а не Markdown и не отдельный день.
- `backend/app/app_routes.py` — пользовательский маршрут курса отдаёт/подготавливает `backend/app/static/masterclass-first-days-preview.html`. Название файла «preview» не означает, что он не участвует в пользовательском runtime.
- `backend/app/masterclass_routes.py` — runtime курса, прогресс, анкеты, приложения и gate API; данные читаются через `course_context(db)` и published material overrides.

## 2. Data Layer

- `backend/app/models.py`: `ManagedDocumentVersion`, таблица `managed_document_versions`. Структура курса хранится как JSON `payload`, с `document_type='course-structure'`, `document_key='masterclass-21'`, `schema_version`, `version_no`, `content_hash`, `created_by`, `is_active`, временем создания. Есть уникальность `(type,key,version)` и только одной active revision.
- `backend/app/models.py`: `ContentSource`, `ContentItem`, `ContentItemVersion`. Статьи используют source `platform='internal'`, `account_key='masterclass-course-materials'`; `ContentItem.external_id = step_id`, `latest_version_id` указывает на текущий HTML-снимок. Версии содержат `version_no`, `text_content`, blocks, hash, parser version, timestamps; оригинальный Markdown отдельным полем этим publisher не сохраняется.
- `backend/app/models.py`: `MasterclassDayProgress`. Базовые обязательные ID шагов и заданий зафиксированы в `required_step_ids`, `required_check_ids`, `structure_revision_no`; отметки заданий в `checkmarks`. Это пользовательские данные, их нельзя менять через редакторскую публикацию как обычный контент.
- `backend/app/models.py`: `MasterclassStepProgress`. Завершение материала пока адресуется **позиционным** `(user_id, day_number, step_index)`, а не только `step_id`. Поэтому изменение порядка требует специального переноса индексов.
- `backend/app/masterclass_routes.py`: ответы анкет сохраняются по стабильному `question_code` внутри questionnaire run. Текст и подсказка вопроса сейчас берутся из констант, не из опубликованного Markdown.
- `backend/app/course_structure_service.py`: `course_context(db) -> CourseContext`. Runtime truth — active DB revision; `content/masterclass/course/course.json` служит seed, но не перезаписывает active редакцию. Название всего курса подменяется из `product_public(db, 'masterclass')['name']`, а не из общего H1 `program.md`.

## 3. Similar Features и готовые механизмы

- `backend/scripts/publish_masterclass_editorial.py` уже реализует полный authoring parser → manifest → semantic HTML → DB publish, в отличие от гипотезы, что такого синхронизатора ещё нет. `editorial/README.md` и `OPEN_QUESTIONS.md` в проверенном worktree описывают более раннее состояние; факт отсутствия publisher из этих старых описаний не следует.
- `backend/app/course_material_service.py`: `publish_material(db, *, step_id, content, content_format, expected_version, admin, commit=True) -> dict`. Можно использовать для одной статьи или внутри общей транзакции с `commit=False`; идентичный rendered HTML не создаёт новую версию.
- `backend/app/managed_documents.py`: `publish_document(...) -> ManagedDocumentVersion` поддерживает `expected_version`, row lock, hash/no-op, версии, `commit=False`. `restore_document(...)` восстанавливает документ через prepare hook с сохранением появившихся позднее скрытых элементов.
- `backend/app/calorie_course_material_service.py` и `calorie_course_service.py` подключены к тем же HTTP routes через выбор service по `course_code`. МК не нужно создавать второй редактор или параллельную модель versioned articles.
- `backend/app/article_markup.py` — общий semantic renderer/санитайзер статьи; `backend/app/masterclass_article_components.py` добавляет закрытые продуктовые компоненты, не arbitrary JavaScript из Markdown.

## 4. Integration Points и текущий data flow

### Publisher пакета

1. `parse_program()` читает названия/порядок/IDs.
2. `compile_manifest()` делает deepcopy active manifest; шаги, не включённые в программу, сохраняет скрытыми. Все текущие дни сопоставляются через `zip(..., strict=True)`.
3. `apply_day_copy()` читает Markdown разделы дня. `lead` превращается в plain text, `intro`/`afterText` — в HTML. Метаданные вводного видео/картинки/таймингов здесь не читаются из MD.
4. Статьи собираются `editorial_body()`: снимаются технический H1/строка типа, относительный префикс изображений `assets/` заменяется на серверный URL.
5. Специальные материалы получают `step.editorialHtml` из текста перед EMBED. Для анкеты берётся только текст **до `## Вопросы`**.
6. Только при `--publish`: `publish_document(commit=False)`, перенос positional прогресса, все статьи через `publish_material(commit=False)`, единый `db.commit()`.

### Две существенные API-границы

- Отдельная material PUT меняет только тело статьи; её название и длительность принадлежат structure manifest. `article_step()` отклоняет специальные kind и tutorial (`422`).
- Structure PUT рассчитан на существующий web-editor, а не полный compiler: нельзя менять порядок существующих шагов, добавлять/удалять их или менять неразрешённые поля. `STEP_EDITABLE` включает title/label/summary/hidden/locked/badge, но не новый `editorialHtml` или duration. HTML дня через `sanitize_fragment()` сохраняет лишь strong/em/a/br — сложное форматирование, изображения и списки через этот старый editor API не проходят полностью.

Следовательно, последовательность «PUT structure + N PUT articles» не эквивалентна готовой транзакционной пакетной публикации: другие ограничения, отдельные коммиты, возможен частичный результат.

### Отображение специальных материалов

- `backend/app/static/masterclass-first-days-preview.html` — обёртки `renderQuestionnaire`, `openEmbeddedApp`, `openDqsMaterial` используют `editorialHtml`. Анкетные поля рендерятся из `data.questions`, а не из секции вопросов MD.
- `<!-- EMBED: ... -->` не должен появляться в пользовательском HTML. Права доступа, приложения, товары, цены и действия формы принадлежат существующему runtime.
- Две MD-заглушки `07-00-*`, `15-00-*` создаются bootstrap и проверяются валидатором, но `publish_masterclass_editorial.main()` перебирает только `materials`, возвращённые parser программы. Поэтому **их авторский текст сейчас не опубликован этим маршрутом**.

## 5. Existing Tests

Framework: pytest; backend tests используют FastAPI TestClient и SQLite in-memory, SQLAlchemy Session. Реальный сервер/production для этих tests не нужен.

- `backend/tests/test_masterclass_editorial_publish.py` — сборка 20 дней/названий/видимости, reordering, day copy, special prelude, медиа-prefix rewrite, перенос прогресса. Примеры: `test_day_markdown_supplies_runtime_day_copy_and_checks()`, `test_step_progress_follows_stable_id_when_program_reorders_steps()`.
- `backend/tests/test_masterclass_journey.py` — structure publication/runtime override, conflicts, history restore, articles with Markdown and special-kind rejection, product semantics, safe media path. Примеры: `test_course_material_publisher_supports_markdown_history_restore_and_blocks_special_steps()`, `test_masterclass_article_media_route_serves_only_registered_image_tree()`.
- `backend/tests/test_article_markup.py` — semantic renderer/sanitization и таблицы/плашки/изображения.
- `backend/tests/test_course_structure_multiline.py` — сохранение переносов строк через editor normalizer.
- `tools/tests/test_publish_course_material.py` — CLI-публикация и validation gate, timeout/unknown-result поведение.

Не найден существующий тест upload API изображений, Obsidian plugin/button, атомарного HTTP publisher всего пакета, публикации MD-вопросов анкет и текстов двух access gates; самих этих механизмов в проверенных границах нет. Tests в этой исследовательской задаче не запускались.

## 6. Shared Utilities / форматирование

- `markdown_to_article_html(source, *, strip_source_metadata=False, component_renderer=None)` из `backend/app/article_markup.py`. Поддерживает h2/h3, inline emphasis/links, paragraph, ordered/unordered lists, цитаты, Markdown tables, `:::note [Заголовок]`, безопасные картинки/подписи; вывод санитизируется.
- Изображение renderer распознаёт отдельной строкой `![alt](https://... "подпись")` или URL от `/`. Произвольный `assets/...` renderer непосредственно не принимает: текущий publisher предварительно переписывает префикс. Obsidian `![[...]]` сейчас не конвертируется.
- `render_material(content, content_format) -> str` из `course_material_service.py` — общий renderer с ограничением байтов, безопасным Markdown и разрешёнными masterclass components.
- `material_hash(step_id, version_no, html)` и `document_hash(payload)` фиксируют versioned HTML/structure. Это не журнал соответствия локального Markdown и baseline серверной версии.
- `effective_required_step_ids(...)`, `effective_required_check_ids(...)` из `course_structure_service.py` используют сохранённую baseline курса, скрытость/lock и reactivation marker. Новые и возвращённые пункты нельзя оценивать только визуальным списком редактора.

## 7. Потенциальные проблемы и недостающие границы

### Изображения и persistence

- `backend/app/course_material_routes.py`: `GET /course-assets/masterclass/media/{asset_path:path}` выдаёт только файл из `content/masterclass/source-current/assets/`, с resolve/is_relative_to, allowlist `.gif/.jpeg/.jpg/.png/.webp`, cache max-age 86400. **Это GET, не загрузчик.**
- `backend/Dockerfile` COPY помещает content/masterclass/source-current и editorial в image; приложение запускается пользователем `app`.
- `compose.yaml` не монтирует постоянный каталог изображений backend. Новые runtime uploads нельзя просто писать в layer контейнера: они пропадут при пересоздании. Действующий редакторский publisher только переписывает ссылки, ничего не копирует/загружает.
- В проверенном editorial worktree нет ни `editorial/assets`, ни `editorial/materials/assets`; существующий локальный `assets/...` не доказательство, что Obsidian уже может открыть этот файл рядом с материалом.

### Прогресс и checklist IDs

- `migrate_step_progress()` использует стабильные ID для пересчёта индексов; PostgreSQL блокирует таблицу, сначала переносит affected indices на +10000, затем на target. Нельзя заменить этот этап одним structure PUT.
- `apply_day_copy()` сопоставляет старые checklist IDs по **точному тексту**. При редактировании двух слов создаётся новый hash-based ID, старый пункт скрывается. Это не гарантия сохранения галочки на отредактированном пункте; для неё нужен отдельно определённый стабильный ID задания.
- Если MD-раздел задания пуст, `if checks:` оставляет прежние задания, то есть «удалить всё» не работает как ожидается и не сигнализирует явно.
- `compile_manifest()` умеет создавать только два специально предусмотренных новых step (`day-07-store-food`, `day-17-article-04`). Произвольное создание нового материала сейчас вызывает `ValueError`.
- При переносе существующего шага между днями глобальный map и список hidden старого дня требуют проверки на дубли и корректность positional прогресса. Тесты покрывают перестановку внутри дня, не перенос между днями.

### Конфликты и запись

- `expected_version` и row locking уже защищают серверную конкуренцию. Но CLI по умолчанию получает свежую версию непосредственно перед PUT: это не обнаруживает ситуацию, когда локальный MD создан на старом тексте и правки в админке появились раньше. Нужен явный authoring baseline/version manifest, если обещается обнаружение такой ситуации.
- Пакетный publisher также получает current перед сборкой, не знает последней авторской baseline. Не содержит HTTP validation gate `--pack/--validation-report`, который обязателен для отдельного CLI.
- Admin HTTP маршруты защищены `require_admin`; `tools/publish_course_material.py` использует Basic auth из environment. Нельзя складывать credentials в заметки Markdown, Git или plugin settings в tracked `.obsidian`.
- `verify_publish_gate()` проверяет schema `author-validation-v1`, pass, hash pack/draft, при необходимости review hash и срок fact review (24 часа). Пакетная публикация и небольшая механическая правка должны иметь согласованный маршрут с существующим authoring contract, а не фиктивный pass report.

## 8. Constraints & Infrastructure

- `backend/requirements.txt`: Python image 3.13, FastAPI 0.141.1, SQLAlchemy 2.0.52, Pydantic Settings 2.15.0, psycopg 3.3.4, Markdown 3.8.2. Renderer статей в этой границе — собственный ограниченный parser; факт установленного Markdown не делает Obsidian plugins автоматически совместимыми.
- Канонические контракты: `docs/knowledge-base/ARTICLE_STANDARD.md`, `docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md`, `COURSE_VISUAL_SYSTEM.md`, `COURSE_DESIGN_SYSTEM.md`. Новый publication contract должен связаться с ними, не повторять их как конкурирующий стандарт.
- Изменение текста — versioned data publish без code deploy, когда соответствующий механизм уже выпущен. Добавление нового publisher API/upload/persistence/Obsidian button требует первоначального выпуска кода и инфраструктуры.
- Чтение live DB не выполнено; нельзя утверждать, что именно этот `origin/main` сейчас deployed или все текущие MD уже приняты владельцем/опубликованы.
- Старый `OPEN_QUESTIONS.md` содержит gate/doprodazha вопросы и утверждение, что runtime не видел новый ID; main уже включает publisher и runtime шаблон. Это исторический незавершённый контекст, не подтверждение сегодняшнего блокера. Авторское решение проверяется отдельно без самостоятельной замены текста.

## 9. External Libraries

В рамках чтения существующего механизма новый external package не выбран. Context7 не вызывался: задача не использует новую внешнюю библиотеку. Obsidian-кнопка требует отдельного выбора native plugin/approved community command runner и проверки актуальных официальных API. На текущем этапе button/plugin в проекте не найден и не устанавливался.

## 10. Проверенная матрица готовности

| Объект редактуры | MD есть | Publisher готов | Существенная граница |
|---|---|---|---|
| Оглавление, названия, порядок, длительность | Да, program.md | Да, direct DB package | Нет эквивалентного package HTTP API; ID менять нельзя |
| Тексты дней и checklist | Да, days | Да, direct DB package | Checklist identity зависит от текста; media metadata не в MD |
| Статьи | Да | Да, direct DB и material API | Перед material CLI нужен действительный validation report |
| Вступления анкет/приложений/offer | Да | Частично, editorialHtml package | Не обычный material PUT; особые тексты после EMBED не публикуются |
| Вопросы и подсказки анкет | Да, bootstrap snapshot | Нет из MD | Runtime константы; stable question_code/ответы сохранять |
| Заглушки закрытых дней | Да, 2 файла | Нет в package | Не входят в parser material map |
| Локальные изображения | В старом assets | Только prefix rewrite и GET | Нет upload/persistent runtime storage/hash dedup |
| Вводное видео/картинка дня, тайминги | Runtime metadata | Не из day MD | Сейчас остаются из active manifest |
| Цена/права/кнопки покупки/логика приложений | Другие runtime owners | Не должны быть обычным authoring MD | Не смешивать публикуемый текст с кодом/доступами |
| Кнопка публикации Obsidian | Нет | Нет | CLI wrapper + explicit action + безопасные credentials |

## 11. Минимально необходимое продолжение

Для покрытия согласованного «всего МК» существующие compiler/render/version services пригодны как основа; отсутствуют их безопасный HTTP batch facade, uploader/persistent asset area, authoring baseline/journal, special gate и questionnaire copy bindings. Повторный курс/второй ЛК/второй renderer для этого не нужны.

Существенные решения до публикации: какой физический editorial пакет содержит последнее утверждённое редактирование; входят ли в текущий выпуск только тексты уже существующих вопросов или изменение состава анкеты; должна ли текстовая правка задания сохранять старую галочку; входят ли introductory media/timings в управляемые MD-метаданные. Эти решения не требуют спрашивать владельца о внутренних API/таблицах/скриптах.

Локальная подготовка стандарта и compiler может быть проверена без DB; первая настоящая пакетная запись в production требует раскрытого состава изменений и подтверждённой редакции источников. Нажатие будущей кнопки не должно публиковать весь пакет без выбора/показа затронутого набора.
