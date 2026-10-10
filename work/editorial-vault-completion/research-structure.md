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
