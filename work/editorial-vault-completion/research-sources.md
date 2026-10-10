# Исследование оригиналов: курс тренировок, рецепты и HTML

Проверено: 10.10.2026. База: owned checkout `article-style-unification`, HEAD
`660e812` при старте. Только исследование: материалы, metadata, сервер и публикации
не изменялись. Runtime сначала читался защищёнными GET через `tools.editorial_vault.API`;
уточнение пяти оригиналов ниже использовало отдельно разрешённую READ ONLY
транзакцию DB, ограниченную этими ContentItems.
Локальные курсовые оригиналы прочитаны из постоянной папки; исследовательский файл
не создаёт второго владельца редакционного текста.

## Entry Points

- `tools/editorial_vault.py::Vault.discover/read/refresh/publish` — каталог,
  исходник и конфликтующие версии постоянной папки. `COURSES` сейчас содержит
  только `masterclass-21`, `calories`; kind=course хранит фактический source_format.
- `backend/app/course_material_routes.py::material_service(course_code)` —
  разрешает только Мастер-класс и Калорийный курс; неизвестный training получает
  404. GET `/admin/api/courses/{course_code}/materials/{step_id}` возвращает
  source_content/source_format/provenance; PUT сохраняет редакцию с expected_version.
- Там же `admin_adopt_recipe_source(...)` — POST `.../{step_id}/recipe-source`,
  подключение полного точного MD текущего рецепта, без реконструкции текста.
- `backend/app/course_material_service.py::get_material/publish_material` —
  Мастер-класс, full source в version.blocks. Git day-01 и исторические day-07
  имеют отдельные publication_profile и не должны автоматически превращаться в API.
- `backend/app/calorie_course_material_service.py::get_material/publish_material` —
  самостоятельный источник calories-course-materials, тот же source block договор.

## Data Layer

- `backend/app/models.py::ContentItem/ContentItemVersion` — item связывает source и
  external_id=step_id; latest_version_id выбирает принятую редакцию. text_content
  содержит производный HTML; blocks хранит article_html и editorial_source
  `{format,content}`. Сохранение Markdown не требует новой таблицы.
- `backend/app/course_material_service.py::editorial_source_payload(version, fallback_html)`
  возвращает retained original, иначе обозначает `legacy_html`/`fallback_html`.
  Нельзя переименовать fallback HTML в markdown: renderer экранирует его как текст.
- `backend/app/recipe_originals.py` — namespace `recipe_calculator` в metadata_json:
  version, source_hash, cards. Cards содержат id/title/active; активные — точные
  yield/portion/rows, нутриенты десятичными строками. Данные не извлекаются из PNG.
- `backend/app/recipe_material_authoring.py::authoring_status(db,step_id)` — ready
  только если version синхронизирован и hash полного retained MD совпадает с metadata.
  Состояния adoption_required и original_sync_required различаются.

## Подтверждённый состав папки и 15 исключений

`.publisher/state.json`: 232 items. Источники course: 67 html + 28 markdown;
Git markdown: 7 (интенсив, пять писем, материал day-01). Другие форматы:
5 public MD, 62 blog MD, 1 homepage MD, 56 telegram_html, каталог/цены/названия/2graphs.

| Исключения | Фактический источник / состояние GET |
|---|---|
| `day-07-recipes-part-1` | v5, legacy_html, recipe_authoring отсутствует; это обзор со ссылками, а не рецепт калькулятора |
| `day-15-recipes-part-2` | v13, legacy_html, recipe_authoring отсутствует; общий каталог со ссылками |
| day-07-recipe: author-oatmeal, red-lentils, broccoli, marinara, white-sauce, lazy-khachapuri, caesar, tuna-family | Восемь архивов, source_provenance=git_markdown; publication_profile.type=archive. Читательский оригинал сейчас day-15-recipe с соответствующим slug. Архивы не перепубликовывать как текущие |
| `day-15-recipe-farro-salad` | v4, legacy_html, adoption_required |
| `day-15-recipe-alfredo-sauce` | v4, legacy_html, adoption_required |
| `day-15-recipe-pasta-alfredo` | v4, legacy_html, adoption_required |
| `day-15-recipe-chicken-cabbage-bowl` | v5, legacy_html, adoption_required |
| `day-15-recipe-yogurt-bark` | v3, legacy_html, adoption_required |

`Vault.read` сейчас применяет проверку `"recipe" in item["id"]`: она ошибочно
блокирует два обзорных recipes-part материала без recipe_authoring. Реальная
граница backend — `STEP_PREFIX="day-15-recipe-"`; поддержка обычных обзоров
не требует изменения калькулятора или снятия архивной блокировки.

## Полные оригиналы пяти текущих рецептов

`content/masterclass/recipes/README.md` владеет форматом и адресами пакетов.
Для всех пяти существует MD в
`D:/Codex/work/private-authoring/recipe-feedback-sequential-20261005/materials/day-15-recipe-<slug>.md`.
Проверка точного `publication_markdown(step,source)` → `render_material(...,"markdown")`
показала **побайтовое равенство нынешнему HTML** всех пяти. Использован UTF-8 с LF,
как устанавливает существующий договор. Однако эти пять файлов не содержат
скрытого recipe-card-data, и metadata.source_hash не проверялся через DB:
равенство HTML само по себе ещё не доказывает полный принятый оригинал.

| Slug | SHA256 файла с LF, HTML совпадает |
|---|---|
| farro-salad | `0d99b9b356f87ac629bc352790f46ffb7dedac91271b67c92d29c3d5a26a98c6` |
| alfredo-sauce | `99e0b66926be1429eb7078d2034c6a6e1e14bc04c547f84af8c2dbf22bb82e08` |
| pasta-alfredo | `9c64fbf2cb55e37d2d7338b8741a914a8c6e1b36b23672632b5743b9a9cfc4eb` |
| chicken-cabbage-bowl | `ba485b45e39d1bf00e03ac8739258b2e4bdbc540401b9a11cefb48df1bc66d94` |
| yogurt-bark | `27a7318ad16fa4b8872a10264559941c8ba043d9280599674d07f466c47b0a92` |

Исходная сборка находится по документированному
`D:/Codex/work/private-authoring/recipe-publication-20261001/`; её
`execution/inventory.json` указывает review-20261001/materials и исторические
файлы/таблицы, но прямо не является реестром последних версий. До adoption нужны
два доказательства одновременно: MD hash = existing calculator source_hash,
rendered HTML = current.text_content. Не менять source_hash ради удобного файла.
Утверждённые карточки и точные числа должны оставаться в исходном договоре.

## Курс тренировок: фактическая граница

- `docs/knowledge-base/modules/catalog/products.training.md` — implementation_status
  planned. `modules/training/README.md`, COURSE_PROGRAM.md,
  MATERIALS_AND_SOURCES.md, DECISIONS_AND_OPEN_QUESTIONS.md — текущие владельцы
  программы/готовности. Не путать с работающим приложением `products.strength`.
- Актуальный GET product-catalog: training имеет status=planned; backend
  product_catalog_service.py задаёт ready=False/app=None. Название берётся из active
  catalogue, описание продажи не доказывает готовность курса.
- В постоянной папке **один** рабочий файл: `Курс по тренировкам/Силовой тренинг/Каталог упражнений по мышцам.md`.
  Карта материалов 09.10 прямо сообщает: локальный справочный материал, runtime
  публикации нет; источник 50 названий/12 групп — strength_exercise_guides.json.
- 14 ранних читательских черновиков в work/training-course-design/drafts не приняты
  как пакет новой программы. Кандидат 1.1 находится в отдельной приватной authoring
  папке по карте материалов; не переносить автоматически как опубликованный урок.
- Ни material_service, ни Vault.COURSES не обслуживают training; существующего
  маршрута опубликованного тренировочного курса исследование не обнаружило.
  API-редакция существующего справочника/хранение черновиков и создание runtime
  учебного курса — разные результаты. Новая оболочка/доступ/публикуемая структура
  требует соблюдения COURSE_APPLICATION_STANDARD и ограничения AGENTS, а не
  добавления строки training в клиентский список.

## Similar Features / Shared Utilities

- `recipe_material_authoring.py::publish_recipe_source(...,adopt=False)` — готовая
  транзакция source+HTML+calculator metadata. Adopt проверяет exact hash+HTML;
  обычный PUT сохраняет cards и protected_parts; restore требует retained MD.
- `backend/scripts/publish_recipe_originals.py::publish(db,bundle,apply=False)` —
  синхронизация точных карточек с текущими material versions под locks; dry-run
  default, не копирует тела материалов. Не превращать adoption в пересчёт PNG.
- `tools/extract_tilda_article_markdown.py::TildaArticle` — extraction-only из
  div.tlk-lecture__text сохранённой Tilda-страницы. Не универсальный конвертер
  уже очищенных нынешних articles: иначе тело без этого wrapper будет пропущено.
- `backend/app/article_markup.py::markdown_to_article_html(...)` — детерминированный
  renderer; HTML inline экранируется. Есть notes, lists, tables, images, links.
- `backend/app/masterclass_article_components.py::render_masterclass_component` —
  закрытые recipe_card/audio/video/slider/dqs_score_table/spoiler; не разрешать raw
  executable HTML ради миграции.

## HTML → Markdown: измеренный состав и Integration Points

67 фактических HTML источников содержат 2658 p, 443 h2, 96 h3, 210 ul, 73 ol,
493 ссылок, 143 figure, 149 img. У 84 блоков class=article-note-accent.
Особые части: day-04-article-01 — 6 DQS tables, 2 galleries/21slides; day-05-article-01
— 2 обычных tables и spoiler; day-11-article-01 — media iframe; day-20-article-02
— audio iframe. У пяти неподключённых рецептов 6 recipe_card (bowl имеет две).
`day-17-article-04` — пустой fallback: не придумывать текст и не пытаться отправить
пустой MD, sanitizer обоснованно откажет.

Конверсия нынешнего HTML может создать новую **производную authoring редакцию**,
а не восстановить утраченный авторский MD. История прежнего HTML остаётся
ContentItemVersion; новая editor_source должна стать единственным текущим
редактируемым источником с явной provenance преобразования. Если найден реальный
полный актуальный MD и точное равенство runtime — подключать его вместо конверсии.
Старый source-current после DB override не доказательство нынешнего текста.

Конвертеру требуется распознавать существующие semantic DOM primitives и
закрытые компоненты; сохранять слова, ссылочные адреса, list start, картинки/alt,
плашки, таблицы, media source и подписи. Пример: DQS table сопоставляется с
существующим renderer и разрешённым аргументом; иначе unsupported с адресом
узла. Не вырезать незнакомую часть, не превращать gallery в один img. Парсер MD
имеет узкую escape grammar: отдельно проверить literal `*`, `~`, `[]`, `|`,
перенос br и круглые скобки URL, иначе roundtrip может поменять видимый текст.
Обычный PUT позволяет format=markdown и сохраняет source; для initial adoption
нужны expected_version и доказанная проверка текущего HTML под lock, чтобы
между read/convert/apply не принять чужую редакцию. Source и local state менять
в существующем файле только с compare/base guard, сохраняя пользовательский draft.

## Existing Tests / Проверки равенства

- `backend/tests/test_recipe_material_authoring.py` (pytest, existing SQLite
  setup): `test_adoption_requires_existing_source_hash_and_exact_render`,
  `test_failed_original_sync_rolls_back_material_and_metadata`; покрывают
  exact adoption, защищённые части, rollback, restore и CRLF/LF.
- `backend/tests/test_article_markup.py` (unittest): notes, safe links/images,
  tables, list starts, escaped marks; готовые фикстуры primitives.
- `tools/tests/test_editorial_vault.py` и `test_publish_course_material.py` —
  base/version/hash, no-op, external source guard, dirty local draft/conflict.
- Не обнаружен готовый тестовый пакет HTML→MD→HTML. Для нового конвертера нужны
  representative actual structures, полное invariants сравнение, отказ неизвестным
  блокам, stale apply без writes, repeat no-op; recipe source отдельно exact HTML/hash.

## Potential Problems / Constraints & Infrastructure

Архивные day-07 IDs должны отображаться как архив/ссылка на текущий оригинал,
а не как требующий срочной публикации новый рецепт. Recipes-part guard — клиентский
ложноположительный результат. Media recipe protected_parts ныне запрещает менять
картинки/ссылки через обычный prose PUT: новый общий uploader обязан учитывать эту
границу, сохраняя calculator rows/cards и atomic metadata sync.
Структура/доступ/прогресс являются отдельным владельцем и не меняются от перехода
format HTML→MD. Не выполнять массовый импорт персональных данных, DDL или новую
публичную оболочку как побочный результат. API/auth существуют; secrets не входят
в каталог/MD. Новых внешних библиотек не требуется для проведённого исследования;
Context7 не применялся, production settings/пароли не выводились.

## Updated: 2026-10-10 — точные оригиналы пяти рецептов подтверждены

Дополнительное разрешение исследования ограничено metadata.source_hash/cards/version
пяти текущих recipes. Через существующий SSH/docker выполнены две транзакции
`SET TRANSACTION READ ONLY`, завершённые rollback; ни один SELECT не затрагивал
пользовательские данные, соседние источники или `/srv/edabalans-private`.

**Все пять LF SHA из таблицы выше совпадают с действующим calculator source_hash.**
Во второй транзакции одновременная сверка также доказала точное равенство rendered
HTML принятому current.text_content, metadata_version=current version,
`validated_cards(cards)` проходит, retained editorial_source/Markdown отсутствует.
Отсутствие recipe-card-data комментария в этих принятых MD не повод дописывать
его и менять hash: калькуляторные оригиналы уже зарегистрированы в действующей
metadata. Они сохраняются готовой транзакцией adoption.

| Step slug | Version / metadata_version | Cards | SHA256 нынешнего HTML |
|---|---|---|---|
| farro-salad | 4 / 4 | farro-salad active, 9 rows | `d00ad828da80b5a64905d702532c3b4b02a7c9f5719a42c99b0b6273bb129a81` |
| alfredo-sauce | 4 / 4 | alfredo-sauce active, 4 rows | `9182c31e73a1de263a3966e49da5a7e3cbb03c1103946e304184d3d01919dc97` |
| pasta-alfredo | 4 / 4 | pasta-alfredo active, 5 rows | `b800a7e3932b6b0b64c01c1bf0f43e4c397b16be246c722409d089b31b592a0b` |
| chicken-cabbage-bowl | 5 / 5 | chicken-cabbage-bowl + beef-cabbage-bowl active, 9 rows each | `a0fb4b24958b1b8a459642971b428195fc79d505673d5bb58940bcd46db32abd` |
| yogurt-bark | 3 / 3 | yogurt-bark active, 3 rows | `2ce71ab28b271dbd2e040d414ab56ca044ec225819bf4e71eef3ed05246c76a2` |

### Процедура существующего adoption для root

Новый production helper или изменения backend для этих пяти не нужны.

1. Выбрать только эти пять стабильных IDs в существующем state. Проверить hashes
   фактических локальных Obsidian файлов против base_hash. Не заменять пользовательский
   dirty HTML/MD черновик источником из приватного пакета.
2. Читать exact MD по пути таблицы выше через `Path.read_text(encoding="utf-8")`:
   universal-newline даст доказанное LF представление. SHA обязан равняться таблице;
   не strip, не добавлять комментарии, шапки, нормализацию пунктуации или расчёты.
3. Перед операцией получить защищённый GET текущего material; потребовать ожидаемую
   версию из таблицы и `recipe_authoring.status=adoption_required`. Локально сравнить
   rendered HTML с свежим GET html, а не с историческим vault-файлом. При drift
   остановить выбранный материал с конфликтом, не заменять expected_version новым
   значением автоматически. Если уже ready, сверить exact source и считать no-op.
4. Вызвать существующий POST
   `/admin/api/courses/masterclass-21/materials/day-15-recipe-<slug>/recipe-source`
   с `{expected_version: проверенная_версия, format:"markdown", content: полный_MD}`.
   Сервер внутри lock повторно проверит source hash, HTML, cards и version, создаст
   retained source и синхронизирует metadata без изменения точных rows.
   Нормальное продвижение версий — 5,5,5,6,4; тело читательского HTML неизменно.
5. При timeout сначала GET: ready+exact source+same HTML доказывает завершённую
   операцию; не повторять POST со старой версией и не инициировать пересборку карточек.
6. Обновить именно эти five entries существующим Vault.refresh с ограниченным
   discovery (сохраняет state остальных items), используя normal locks и
   update_if_unchanged; не копировать текст вручную поверх state/base. Проверить
   format=markdown, unsupported=False, source hash и выбранный clean/no-op status.
7. Записать санитарное evidence: IDs, before/after versions, source/HTML hashes,
   cards unchanged proof. Не сохранять служебные пароли, ключи или полный DB dump.

Пункт training исключён владельцем из текущей реализации; исходная проверка
planned/no runtime выше остаётся фактологическим контекстом, не заданием создавать курс.
