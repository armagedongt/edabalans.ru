# Code Research

База: 660e812, 10.10.2026.

# Исследование локальных изображений редакционной папки

Проверено: 10.10.2026. Checkout: `article-style-unification`, исходная ревизия `660e812`.
Граница: чтение кода; публикация и изменения production не выполнялись. Файл относится
к дополнению редакционной папки, не является новым каноном медиа.

## Что работает сейчас

- `tools/editorial_vault.py`: `Vault.read(item)`, `Vault.publish(ids, owner_edited=False)`
  передают только текст существующим адаптерам. Файл изображения в папке Obsidian
  не читается, не загружается, не учитывается в `base_hash`. Изменение байтов картинки
  без изменения MD сейчас не отражается в статусе публикации.
- `backend/app/article_markup.py`: `markdown_to_article_html(...)` распознаёт отдельную
  строку `![alt](https://... "подпись")` или корневой URL `/...`. Относительный путь
  `assets/photo.jpg` и Obsidian `![[photo.jpg]]` не являются поддержанными вставками.
  Подпись необязательна. `safe_image_src(value, allow_relative=False)` запрещает
  protocol-relative URL, обратные слеши, управляющие символы; разрешает HTTPS, а
  корневые относительные URL — только в подходящем профиле sanitizer.
- `tools/editorial_git_adapter.py`: Git-интенсив и Git-материал курса публикуются
  текстом через `/draft` и `/publish`, с SHA основного и чернового источника. Адаптер
  не передаёт бинарные Git-файлы. `backend/app/github_content_editor.py` кодирует
  UTF-8 текст; существующие операции нельзя использовать как бинарный upload.

## Блог: имеющийся upload не равен публичной публикации картинки

- `backend/app/blog_draft_routes.py`: существующий admin `PUT
  /admin/api/blog/articles/{slug}` принимает `DraftPackage` с `DraftMedia`;
  `PATCH .../text` принимает только Markdown и обложку. Авторизация через
  `require_blog_mutation`, существующая защита same-origin для браузера; desktop
  API сохраняет свой действующий машинный маршрут.
- `backend/app/blog_draft_service.py`: `prepare_package(slug, source)` и
  `_decode_media(item)` проверяют и сохраняют base64 в payload
  `ManagedDocumentVersion`; `media_bytes(version, name)` возвращает проверенные байты.
  Это готовые примеры проверки данных и versioned-storage, не файловый upload-сервис.
- Лимиты: 8 изображений в пакете; 1 MiB декодированных байтов на файл; 4 MiB
  суммарно; 1 500 000 символов base64 на поле; общий HTTP body 8 MiB. PNG/JPEG/WebP,
  расширения png/jpg/webp, имя `[a-z0-9][a-z0-9_-]{0,91}` с расширением.
  Pillow проверяет формат, verify + load, ≤6000 px по стороне, ≤25 млн пикселей.
  Provenance обязателен, ≤2000 символов; alt ≤500. SVG/GIF этим пакетом не принимаются.
- `_validate_markdown(markdown, media)` разрешает только изображения того же пакета;
  Git-изображения — `/blog/media/{name}`, DB-изображения — `/media/{name}`. Raw HTML
  и H1 в теле запрещены; служебные metadata и конечная CTA имеют своих владельцев.
- `publish_article(db, slug, expected_version, admin)` восстанавливает публичные
  media из Git manifest, проверяет `_matches_manifest_contract`, затем разрешает
  поменять только Markdown и выбор существующей обложки. Новый media-пакет сейчас
  отклоняется. `public_payload(db, slug)` также восстанавливает media из текущего
  manifest. Простое подключение PUT к клиенту не решает пользовательский запрос.
- `backend/app/blog_draft_routes.py`: `/blog/drafts/{slug}/media/{name:path}` отдаёт
  байты через `_owner_article`, private/no-store/noindex/nosniff. В
  `backend/app/blog_routes.py` публичный `/blog/media/{name:path}` ограничен manifest
  и производными Git-файлами. Renderer умеет формировать `/articles/{slug}/media/...`
  для DB media, но отдельного публичного маршрута выдачи DB media в этих файлах нет.

## Курсы и публичные страницы

- `backend/app/course_material_routes.py`: GET
  `/course-assets/masterclass/media/{asset_path:path}` читает Git-папки
  `content/masterclass/editorial/assets` и `source-current/assets`, проверяет
  resolved containment и raster suffix. Доступ публичный, cache public. Upload отсутствует.
  Это не подходящий канал для новых закрытых курсовых вложений без access-проверки.
- `backend/app/masterclass_routes.py`: `course_materials(...)` сначала
  `resolve_masterclass_user`, затем рассчитывает доступные дни/step IDs и nested
  recipe exceptions через реальное состояние пользователя. Проверка одного права
  на продукт не заменяет доступ к конкретному ещё закрытому дню.
- `backend/app/calorie_course_routes.py`: `resolve_course_user(...)` использует
  native user и права calories/legacy, а выдача `course_materials` — доступный этап.
- `backend/app/recipe_course_routes.py`: `resolve_course_user(request, db)` проверяет
  native user, ресурс курса и `course_start_is_open`; `material(...)` обращается к
  действующему manifest. Новая выдача изображения должна наследовать этот контекст.
- `backend/app/public_site_content_service.py`: подробные описания продуктов
  используют общий Markdown renderer. После подстановки безопасного HTTPS URL
  они могут отображать изображения без создания другого редактора.
- `backend/app/intensive_onepage.py`: основной текст проходит общий renderer +
  course sanitizer, собственная оболочка/спецэлементы остаются. Подстановка ссылок
  должна учитывать абсолютный origin: блог и основной сервер имеют разные hosts.
- `backend/app/homepage_content_service.py`: `compile_homepage(markdown)` обрабатывает
  только фиксированные textSlots из `content/public-site/homepage/block-map.json`.
  `InlineValidator` не разрешает img. Главная сейчас редактирует текст, её изображения
  принадлежат шаблону. Нельзя автоматически вставлять картинки в любой текстовый slot
  без изменения layout-контракта. Для замены существующих фото нужны отдельные
  стабильные asset slots, не произвольная перестройка главной.

## Существующие общие владельцы и инфраструктура

- `backend/app/models.py`: `ManagedDocumentVersion` — существующая таблица versioned
  JSON payload, document_type/key, hash, creator, active/version. `docs/modules.toml`
  относит таблицу и `backend/app/managed_documents.py` общему владельцу.
- `backend/app/managed_documents.py`: `active_document`, `ensure_seed_document`,
  `publish_document(..., expected_version, admin, commit=True)` дают JSON snapshot,
  дедупликацию одинакового payload, optimistic conflict и retention 20 редакций.
  `ensure_seed_document` выполняет commit; его нельзя использовать внутри новой
  обещанной общей транзакции без проверки границ. Исторические asset records нельзя
  удалять по retention, если они остаются ссылками в сохранённых материалах.
- `compose.yaml`: backend не имеет постоянного upload volume. Файлы внутри
  контейнера без нового volume потеряются при recreate. Telegram `/app/media`
  принадлежит другому runtime; попутно его использовать нельзя.
- `backend/app/content_service.py`: `ContentMedia` хранит ссылочные метаданные
  авторского каталога; существующие функции не являются бинарным upload storage.

## Реальные отсутствующие части минимального решения

Это вывод по зависимостям существующего кода, а не описание уже внедрённого API:

1. Клиентский resolver только изображений выбранного материала: обычный относительный
   MD и `![[...]]`, путь от MD/корня хранилища, percent-encoding/пробелы, alias/размер
   Obsidian; fenced/inline code не трогать. Неоднозначный basename — адресная ошибка,
   не произвольный первый файл. Resolved path и symlink должны остаться внутри vault;
   нельзя читать C:/, UNC, `../` наружу или remote URL как локальные файлы.
2. Authenticated image ingestion к существующему backend, проверенные байты,
   provenance `owner-upload` + источник/исходное имя без ложного утверждения лицензии,
   server-computed digest. Можно использовать существующую JSON document table как
   content-addressed asset record без DDL и новых host/volume, если принято хранение
   ограниченных raster bytes в БД. Более крупное filesystem storage потребует отдельного
   volume/backup-контракта. Отдельный публичный SaaS не требуется.
3. Scope ключа asset: product/material ID + digest. Одинаковые байты не создают
   новый объект при retry; одинаковый digest другого материала не должен обходить
   права. Upload не открывает картинку миру до публикации ссылающегося материала.
4. Public delivery для опубликованных public/blog/popup/intensive ссылок и private
   course delivery с существующими native cookies/access + конкретным step/day.
   Закрытое вложение не должно попадать в публичный `/course-assets/masterclass/media`.
   Git-интенсив требует привязки фактического runtime-оригинала после deploy; сохранённый
   Git draft сам по себе ещё не делает файл публичным.
5. Нормализация серверной MD-ссылки и локального Obsidian оригинала должна быть
   обратимой. Нельзя заменять локальную картинку URL навсегда так, чтобы дальнейшая
   замена её байтов в Obsidian перестала публиковаться. Локальная state-карта assets
   + accepted source/asset hashes сохраняет один MD-оригинал и его ссылки.
6. Статус материала учитывает asset digests. Сохранение снимка MD+байтов, preflight
   conflict до uploads, повторная проверка файла перед публикацией; unrelated материалы
   не отправлять. Lost response: повторно читать canonical record/version/digest,
   восстанавливать pending состояние, не дублить assets/редакции и не затирать drafts.
7. Blog публикация и `public_payload` должны принять дополнительный immutable
   опубликованный asset набор при сохранении manifest-владения CTA/category/visibility/
   существующим hero. Иначе новые URL не проходят `_validate_markdown`. Draft/public
   images остаются разными доступами. Изменения media не должны открыть новый slug
   или internal article; metadata/media исключение сужать до проверенных owner assets.
8. Homepage фото требует отдельного asset-slot договора в том же оригинале MD.
   Достаточно замены существующего src фиксированного изображения без смены текста,
   размеров, CSS и блока. Возможность произвольных новых картинок — другая задача.

## Проверки и существующие примеры

- `backend/tests/test_blog_draft_authoring.py` — pytest fixture authoring + реальные
  package bytes, `test_real_markdown_package_round_trip_and_owner_preview(...)`,
  `test_text_update_preserves_package_and_conflict_preserves_active_version(...)`,
  `test_existing_article_seed_publish_and_later_draft_do_not_leak(...)`.
  Это основа проверки uploaded draft/public isolation и сохранения metadata.
- `backend/tests/test_article_markup.py`, `test_homepage_content.py`,
  `test_recipe_material_authoring.py` проверяют ближайшие renderer/структурные границы.
- `tools/tests/test_editorial_vault.py` проверяет selective publish, base conflicts,
  lost responses, preservation локальных правок. Расширить fixtures реальными PNG:
  changed bytes same filename; повтор одинаковых bytes; MD и Obsidian ссылки;
  basename ambiguity/path escape/symlink/fenced code; конфликт до HTTP mutation;
  изменение файла во время upload; unrelated материал не загружен.
- Backend security tests: unauthorized writes/reads; private image без course access,
  закрытый день при наличии продукта, scoped digest другого материала; invalid MIME,
  svg/HTML под png, decompression bomb/size/body limits, slug traversal; draft не
  публичен и rollback/version mismatch не раскрывает вложения; valid publication
  переживает повторные запросы и новый backend process.
- Граница ревью: code, затем security обязательно из-за untrusted binary/path/auth
  и нового public/private delivery; test reviewer для assertions этих границ.
  Полный UI-прогон не нужен для byte API, но одно реальное Obsidian-style изображение
  должно отображаться в публикации и сохранять исходный layout/подпись.

## Решения владельца, которых нет в коде

- Из запроса уже разрешены реальные local image uploads, API publication выбранных
  материалов, сохранение визуала и отсутствие новой админки. Дополнительное разрешение
  на каждую картинку не требуется.
- Пользователь не выбирал новый media host/SaaS/расход; это не нужен путь реализации.
- Для главной выбранное намерение «редактировать всё» не определяет произвольную
  смену композиции. Без дополнительных вопросов можно сохранить текущий layout и
  сделать заменяемыми уже существующие фото через фиксированные slots.
- Автоматическое заявление «у меня есть права на фото» из имени файла недостоверно.
  Техническое происхождение owner-upload можно хранить автоматически; если нужен
  действительный правовой provenance конкретного стороннего файла, его факт нельзя
  выдумывать. Эта граница не должна превращать обычную вставку владельца в AI review.


# Исследование оригиналов: курс тренировок, рецепты и HTML

Проверено: 10.10.2026. База: owned checkout `article-style-unification`, HEAD
`660e812` при старте. Только исследование: материалы, metadata, сервер и публикации
не изменялись. Runtime читался защищёнными GET через `tools.editorial_vault.API`.
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


# Адресные операции структуры: исследование

Дата: 2026-10-10. База исследования: owned worktree `article-style-unification`, HEAD `660e812`. Только чтение исходников; production, прогресс участников и код не изменялись. Это исследование для внедрения, не свидетельство готового structural API.

## Entry Points

- `backend/app/course_structure_routes.py`: защищённые `GET/PUT /admin/api/courses/{course_code}/structure`, version restore; `course_service(course_code)` поддерживает `masterclass-21` и `calories`. `CourseStructureUpdate(expected_version, manifest)` и `editor_payload(db, course_code)` уже дают активную версию, исходный manifest и историю.
- `backend/app/course_structure_service.py`: `publish_course_structure(db, *, manifest, expected_version, admin)` сохраняет MK; `normalize_editor_payload(manifest, current, next_version)` намеренно запрещает новые ID, удаление и перестановку. `normalize_seed` лишь нормализует договор формата, не заменяет строгую валидацию.
- `backend/app/calorie_course_service.py`: тот же договор calories, но канон `stages`, а `days` — alias. Structural apply должен согласованно обновлять оба представления; не создавать независимые списки.
- `backend/app/masterclass_routes.py`: `course_complete_step(day,index,body,...)`, `reveal_course_application(app_code,body,...)` выбирают шаг по позиции. `complete_questionnaire_course_step(...,context)` находит специальный шаг через runtime, а не из тела запроса.
- `backend/app/calorie_course_routes.py`: `course_complete_step(stage,index,body,...)` сохраняет позиционный прогресс и может вызвать `reveal_metabolism`. `course_update_check` завершает этап; `course_state` тоже пишет события и открывает этап.
- `backend/app/static/masterclass-first-days-preview.html`: `markStep`, `revealCourseApplication`, `applyCourse`, questionnaire completion используют общий клиент. `markStep` сейчас отправляет только email; reveal отправляет day/step_index. В ответе курса уже есть `structure_version`, но при действиях он не передаётся.
- `backend/app/app_routes.py:616–684`: calories и recipes используют тот же HTML посредством строковых замен. Менять контракт запросов следует с проверкой обоих реально получившихся HTML, иначе замены могут перестать совпадать.

## Data Layer

- `backend/app/models.py::MasterclassStepProgress`: user + устойчивый `step_id` уникальны, также хранятся day/index/kind/completed_at. `step_id` nullable только для изолированных legacy fixtures; комментарий указывает существующий production backfill и NOT NULL. `completed_step_indexes` всё равно фильтрует строки по дню: междневной перенос требует обновить day_number.
- `CourseStepProgress`: уникальность user/course/stage/index; стабильного ID нет. Это общая таблица calories и recipes. Новая таблица для операции не нужна: можно построить точное отображение old position → old stable ID → new position до изменения manifest.
- `MasterclassDayProgress`/`CourseStageProgress`: first_opened_at, task_opened_at, completed_at, timezone, structure_revision_no, required_step_ids, required_check_ids, checkmarks. Перестановка не требует переписывать эти строки; перенос материала не должен переносить вместе с ним весь день/этап или сбрасывать выполненное задание.
- `CourseEvent`: уникальность user/course/event_key, details JSON. Calories completion key — `stage:{stage}:step:{index}:completed`; details содержат step_id. MK completion key уже `course:step:{step_id}:completed`, поэтому его не нужно переписывать ради позиции.
- `ContentItem`/`ContentItemVersion`: опубликованный текст адресуется external_id=step_id, независимо от структуры. Reorder не публикует тела повторно. Междневной перенос требует согласовать текущие canonical_url/source_tags day/stage у ContentItem; историю HTML/source не переписывать.
- `backend/app/recipe_course_service.py`: GROUPS — фиксированные ID, отдельный `progressNumber`; nested рецепты строятся из порядка MK source_steps. `recipe_course_routes.complete_step` не записывает nested отметки. Проверять производный recipes manifest при structural diff; существующие фиксированные GROUPS не менять автоматически.

## Existing Implementations / Shared Utilities

- `backend/app/managed_documents.py::publish_document(...,commit=False)`: SELECT active FOR UPDATE, expected_version 409, hash no-op, история, один flush без commit. Готовое ядро транзакции; revision check необходим повторно на apply, а preview ничего не резервирует.
- `backend/scripts/publish_masterclass_editorial.py::migrate_step_progress(db,before,after)`: уже выполняет двухфазный перенос индексов с промежуточным +10000 и PostgreSQL table lock. Работает только внутри одного дня через zip и сканирует все MK rows; для узкого сервиса переиспользовать алгоритм, не запускать широкий publisher и не вызывать этот helper для cross-day.
- `new_article_step(item,next_version)` сейчас жёстко подставляет чужой `55-store-food-without-cooking.md` и обязательность после revision. Этот шаблон нельзя без изменений применять как универсальную новую статью. `new_placeholder_step` задаёт draft/placeholder/required:false, но также устанавливает revision marker.
- `course_structure_service.publish_course_seed_additions(db,admin)`: добавляет весь отсутствующий seed-набор, не отдельную requested operation. Не заменяет адресный add API.
- `course_material_service.publish_material(...,commit=False)` уже позволяет MK material + manifest в одном commit. `calorie_course_material_service.publish_material` сейчас коммитит сам; для атомарного add+body потребуется такой же параметр commit=False.
- `effective_required_step_ids` в обоих course services: учитывает сохранённый baseline и requiredForAllAfterRevision только для видимого required шага. Обычный reorder сохраняет оба значения точно, не обновляет revision marker у всех шагов.

## Минимальная граница нового API/CLI

Ниже проектируемый договор, отсутствующий в текущем коде.

Рядом с существующим structure route: preview/apply одной операции либо малого пакета, `course_code`, `expected_version`, stable IDs, explicit operation fields. Нужны `reorder` внутри unit; `add_article`; `move` обычного материала между существующими units. Нет создания дней, GUI, замены всей программы или произвольного manifest из CLI. Сервер сам строит manifest из активного оригинала.

Reorder задаёт точный полный список IDs одного unit, включая hidden/nested: permutation без потерь. Add задаёт новый ID, title, target unit/anchor, required:boolean и явное `required_for_existing:boolean`; для article тело публикуется из единственного vault файла в той же транзакции. Не ссылаться на чужой fallback asset; если тело ещё не готово, отдельный явный placeholder hidden/locked без выдуманного содержимого.

Move сохраняет ID и все поля шага. Для nested нужен целый parent+children block; нельзя оставлять parentStepId в другом дне. Existing runtime applications/offers/questionnaire/messenger/feedback checkpoints не являются обычными статьями: первый сервис должен конкретно отказать в их cross-unit move, сохранив существующий специальный workflow. При reorder внутри unit сохранять код/placement/event/accessResource, но предупреждать preview о смене последовательности prerequisites.

Move required материала требует явного решения: требуется ли он ранее открывшим target unit. Поле операции обязательное, без молчаливого выбора. Для сохранения прежних обязанностей можно перенести именно ID из source required_step_ids в target snapshot только существующего target progress; не создавать новый открытый target day, не менять даты. Для обязательности всем ранее открывшим target — requiredForAllAfterRevision=next_revision. Уже completed_at target остаётся completed: требовать повторного прохождения — другое явное бизнес-решение, не технический эффект move. Preview должен показывать это различие.

CLI читает operation JSON и файл тела из permanent vault; по умолчанию preview, apply с ожидаемой версией и явным флагом. Итог: новая revision, точный diff, remapped row counts, warnings; затем selective vault refresh без overwrite локальных черновиков. Existing Names.md профиль остаётся только заголовками.

## Транзакции, гонки и отсутствие DDL

Административный FOR UPDATE сам по себе не защищает completion: учащиеся блокируют User, затем читают manifest, а structural writer может заменить позиции между чтением и записью progress. Table lock из старого publisher блокирует INSERT поздно, но запрос уже выбрал старый шаг. Нужен общий порядок синхронизации, а не только блокировка progress tables.

Практичный вариант без DDL — стабильный PostgreSQL advisory transaction key на course: progress mutations берут shared lock ДО User lock и чтения context; structural apply берёт exclusive lock ДО active revision/progress locks. Key постоянен независимо от revision, не Python hash. Reorder/move, обычный PUT/restore и seed/special publishers должны участвовать в том же договоре; если старый publisher оставлен вне него, гарантия неполна. SQLite unit tests не доказывают этот PostgreSQL контракт.

Охват mutations включает GET course_state, open day/task, checks, feedback/finalize, completion, reveal, questionnaire-driven completion, admin reset и другие функции, которые меняют координаты progression; надо пройти caller chain `complete_questionnaire_course_step`, `reconcile_completed_days`, `finalize_course_day` и `finalize_stage`, а не ограничиться одним POST complete. Shared lock размещать до уже имеющегося User FOR UPDATE, иначе структурный writer и learner могут создать обратный lock order.

Все затронутые existing progress rows проверяются по старому manifest. Нет ID/позиции — fail закрыто 409/422 без угадывания. MK обновляет day/index по step_id. Calories/recipes используют двухфазное назначение временных координат вне старого/new max диапазона, flush, then exact new coordinates; фиксированный +10000 без верхней проверки не универсальная гарантия. Completion time/kind/row ID/user неизменны.

Calories completion events можно двухфазно remap к new coordinate keys, проверив details.step_id против старого отображения; временные уникальные keys перед окончательными keys исключают swap collisions. Только известные completion keys текущего calories курса: не переписывать исторические stage-opened/completed и события других курсов. Альтернатива — переход completion dedup на stable step_id, но тогда существующие старые события нельзя молча оставлять без compatible lookup, иначе повторные завершения создадут вторые события. Полный remap без DDL проще доказать в ограниченной операции.

Транзакция: acquire course lock → lock/read active/check expected → validate proposed diff/dependencies/progress → publish_document(commit=False) → coordinate/event remap → material add/body commit=False → один commit. Ошибка любого шага rollback всего набора. Existing restore запрещает reorder по normalizer; после нового structural API для возврата использовать обратную stable-ID operation с тем же remap, а не голое восстановление payload поверх нового positional progress.

## Старые открытые вкладки

После первой structural operation старый запрос без revision должен получить 409 `structure_changed` без изменения progress/reveal, даже если индекс существует. Добавить в существующий manifest небольшой persisted structural marker, например minimum_required_structure_revision; schema DDL для JSON не нужна. До появления marker можно сохранить совместимость старых клиентов; после него body должен иметь structure_version и stable step_id, совпадающие с current day/index. Новая вкладка передаёт оба поля, клиент на 409 перечитывает manifest+state и просит повторить действие. Автоматический blind retry старого index запрещён.

Общий shell обновляет completion/reveal и day/check/task actions по соответствующему устойчивому ID/revision договору. Отдельный recipes shell имеет свой derived manifest version и index completion, поэтому проверить adapter responses и его body; не предполагать, что он автоматически получил MK `structure_version` только от общей HTML замены.

## Existing Tests / Minimal meaningful verification

- `backend/tests/test_masterclass_editorial_publish.py`: pytest + isolated SQLAlchemy fixtures, `test_step_progress_follows_stable_id_when_program_reorders_steps()` и `test_cross_day_move_stops_instead_of_corrupting_positional_progress()` — переиспользуемый старт remap assertions, второй сейчас проверяет запрещённый перенос.
- `backend/tests/test_masterclass_journey.py`: TestClient + SQLite + real models; covers stable assignment checks, restore, questionnaire atomic completion, sequential progression. Нужны endpoint assertions new revision/ID, no writes on legacy body после marker.
- `backend/tests/test_calorie_course_journey.py`: TestClient, fixtures course access/progress, `test_approved_seed_release_is_versioned_and_never_erases_progress(block)` и `test_calorie_course_completes_stage_in_order_and_opens_next_at_local_six(monkeypatch)`.
- `backend/tests/test_recipe_course.py`: отдельные marks и nested recipes, authority/access reused MK. Проверить derived recipe order и сохранённую идентичность completed material.

Новый focused набор: exact permutation/no-op; add duplicate/invalid ID; immutable fields untouched; required existing/new snapshots; cross-day ordinary article completed mark retained; recipe group partial move rejected; special runtime cross-day rejected; calories swap progress+events collision-safe; expected_version conflict; rollback after forced remap/body failure; same content/history unaffected by reorder; stale completion/reveal не завершает соседний ID. Отдельный disposable PostgreSQL concurrent proof: learner acquired shared course lock vs structural writer waits, затем старый revision completion получает 409; reverse order; two simultaneous structural apply one 200/one409. Никаких learner mutations в production для теста.

## Decisions / Constraints

Для построения инструмента новых владельческих решений не нужно: explicit requiredness обязательна в каждой операции. Конкретный будущий перенос обязательной статьи может потребовать решения Сергея о target already-open/completed participants; CLI не выбирает его вместо владельца. Перенос специальных шагов меняет runtime привязки и остается отдельной конкретной задачей, не молчаливой универсальной операцией.

Нет новых таблиц/DDL для описанного remap. Это изменение существующего прогресса участников при apply, поэтому production применение должно иметь штатные backup/restore evidence; планирование/реализация API не означает разрешённую тестовую перестановку живого курса. API require_admin, allowlist course, ограничение длины/числа operations, строгий ID/anchor matching и exact affected-set validation обязательны.

Документация владельцев: `docs/knowledge-base/EDITORIAL_VAULT.md` общий workflow; продуктовые structure/runtime contracts и карточки MK/calories; `docs/modules.toml` ownership. Единственный внешний оригинал материала не помещается в code worktree. Новых библиотек для маршрута не требуется: FastAPI/Pydantic/SQLAlchemy/managed documents уже используются.
