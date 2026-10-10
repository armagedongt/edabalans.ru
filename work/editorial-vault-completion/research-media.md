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
