# Code research: blog-editorial-system

Дата исследования: 2026-08-31  
Контекст: развитие `platform.blog` от статической главной до редакционной системы
Markdown-статей, повторяемых CTA-вставок и обсуждаемой персонализации.

## 1. Entry Points

### Публичный блог

- `backend/app/blog_routes.py` — единственный backend entry point блога. Сейчас
  `blog_home() -> FileResponse` обслуживает только `/blog` и `/blog/`, а
  `blog_font(font_name: str) -> FileResponse` отдаёт два явно разрешённых WOFF2.
  Маршрута отдельной статьи, каталога метаданных, изображений статьи, sitemap или
  feed нет.
- `backend/app/static/blog/index.html` — вся текущая главная: CSS, HTML шести
  карточек, клиентская пагинация и theme toggle находятся в одном файле. Карточки
  не являются ссылками и содержат placeholder-тексты; рубрики и страницы
  зашиты вручную.
- `backend/app/main.py` — включает `blog_router` в общий FastAPI process. Поэтому
  будущий динамический route может использовать ту же SQLAlchemy session и общие
  сервисы, но сейчас `blog_routes.py` к БД не подключён.
- `infra/caddy/Caddyfile` — host `{$BLOG_DOMAIN}` пропускает только `/` (rewrite в
  `/blog`) и `/blog/fonts/*`; любой другой внешний path получает `404`. Для
  человекочитаемых URL статей нужен новый явный Caddy handler, даже если FastAPI
  route уже будет добавлен.
- `compose.yaml`, `.env.example` — production host настраивается через
  `BLOG_DOMAIN`, default `blog.похудение-это-есть.рф`.

### Текущий Markdown и статьи продуктов

- `backend/app/article_markup.py` — общий безопасный renderer. Основная сигнатура:
  `markdown_to_article_html(source, strip_source_metadata=False,
  component_renderer=None) -> str`. Поддерживает `h2/h3`, абзацы, списки,
  `strong/em`, HTTPS/relative links, изображения, цитаты, `:::note`, Markdown-
  таблицы и закрытые вызовы `name(...)`; `h1` из тела удаляется. Итог повторно
  проходит `sanitize_article_html(...)`.
- `backend/app/masterclass_article_components.py` — ближайший рабочий пример
  закрытой библиотеки вставок. `render_masterclass_component(name, arguments)`
  разрешает только `slider`, `dqs_score_table`, `spoiler`; неизвестное имя даёт
  `422`. Данные и HTML этих компонентов принадлежат Мастер-классу, а не блогу.
- `content/author-voice/article-component-router.md` — человекочитаемый
  маршрутизатор синтаксиса. Он прямо фиксирует границу: `platform.content`
  владеет Markdown-диалектом и маршрутизацией, но кодом, данными и видом
  продуктовых компонентов владеют продуктовые модули.
- `backend/app/course_material_service.py` — готовый образец публикационного
  сервиса: `render_material(...)`, `publish_material(...)`,
  `material_versions(...)`, `restore_material(...)`. Он рендерит и санитизирует
  Markdown, блокирует stale update через `expected_version`, создаёт неизменяемую
  `ContentItemVersion`, переключает `latest_version_id` и умеет восстановить
  старую редакцию.
- `backend/app/course_material_routes.py` — защищённые admin routes публикации
  материала и истории версий. Публичная выдача материалов курса идёт через
  отдельный runtime и доступы, поэтому напрямую использовать эти URL для блога
  нельзя.
- `tools/publish_course_material.py` — CLI-паттерн «получить текущую версию →
  проверить свежие pack/report → PUT с optimistic lock → перечитать результат».
  Blog publish CLI/API пока отсутствует.

### Бесплатный интенсив и Мастер-класс

- `backend/app/intensive_routes.py` — `public_intensive_page(day_code)` читает
  текущую версию четырёх страниц, `save_intensive_page(...)` публикует новую
  санитизированную HTML-версию с optimistic lock. Это переиспользует
  `ContentItem`/`ContentItemVersion`, но исходный Markdown не сохраняет.
- `backend/app/product_catalog_service.py` — канонические публичные названия,
  дескрипторы и marketing context продуктов, включая Мастер-класс и бесплатный
  интенсив. `product_public(db, code)` возвращает безопасные публичные поля, но
  публичного route для этого нет; `product_catalog_routes.py` открывает только
  admin API.
- `backend/app/masterclass_offer_rules.py` и
  `backend/app/masterclass_routes.py` — персональные офферы собирает
  `build_offers(...)`; `/api/masterclass/offers` требует email, signed placement
  token и право на Мастер-класс. Это логика допродаж участнику закрытого продукта,
  не готовая публичная CTA blog API.
- `backend/app/static/site-footer.js` — уже содержит общий footer и текущую
  ссылку входа в бесплатный интенсив через Telegram. Блог подключает этот файл с
  `app.edabalans.ru`; второй footer создавать не нужно. Сам файл не является
  серверным каталогом CTA и не даёт renderer-у типизированные данные.

## 2. Data Layer

### Что уже можно переиспользовать

- `backend/app/models.py: ContentSource` — источник материала: `platform`,
  `account_key`, display name, canonical URL и sync status. Для курсов уже
  используется pattern отдельного внутреннего source (`free-intensive`,
  `masterclass-course-materials`), поэтому блог может быть ещё одним внутренним
  source без новой таблицы.
- `backend/app/models.py: ContentItem` — карточка материала. Уже есть canonical
  URL, title, author, published/status, `source_tags`, отдельные ending/CTA поля,
  `review_status`, `catalog_key`, editorial purpose/sales level, topics/meanings и
  свободный `metadata_json`.
- `backend/app/models.py: ContentItemVersion` — неизменяемая редакция с
  `version_no`, `content_hash`, `text_content`, normalized `blocks`, parser
  version и `editorial_metadata`; `ContentItem.latest_version_id` выбирает
  опубликованную редакцию.
- `ContentMedia`, `ContentLink`, `ContentMetricSnapshot` — позиции внешних медиа,
  классифицированные ссылки/CTA и метрики. Каталог намеренно хранит URL Pikabu,
  но не скачивает изображения.
- `ContentFamily`/`ContentFamilyMembership` — связывают проявления одной идеи на
  разных площадках, но не являются готовой моделью блока «Похожие статьи»:
  принадлежность семье единственная, порядок рекомендаций и ручной выбор пары
  blog-статей не хранятся.
- `backend/app/content_authoring_service.py` — `save_authoring_item(...)` создаёт
  immutable owner revision и возвращает `409` при конфликте. Текущий editor
  меняет title/text/variant/status, но не публикует публичный blog slug, category,
  excerpt, hero image или relations.

### Pikabu как исходник шести статей

- `tools/pikabu_collect.py` — collector профиля `armagedongt`; сохраняет полный
  text, ordered blocks, source tags, links, media URLs, ending/CTA, metrics и при
  явном режиме комментарии. Browser profile и snapshot обязаны находиться вне
  Git.
- `backend/app/importers/pikabu_catalog.py` и
  `backend/app/content_service.py` — validate/dry-run и подтверждённый
  идемпотентный импорт в существующие content tables.
- `docs/CONTENT_CATALOG.md` фиксирует фактический production-каталог: 205 Pikabu
  карточек в локальном контрольном снимке и защищённый server catalog. Полные
  тексты не находятся в Git; выбирать «скорость похудения», «похудение начинается
  не с похудения», материал про Японию и ещё три статьи нужно через каталог/
  Библиотекаря, сохраняя exact item IDs и provenance, а не по совпадению файлов в
  репозитории.
- `ContentMetricSnapshot` позволяет ранжировать кандидатов по views/rating/saves;
  `GET /admin/api/content/items` уже поддерживает поиск, source filter и сортировки.

### Где миграция не обязательна

- Обновление header/hero/фото/category «Личное», template статьи и первые шесть
  Git-backed Markdown-файлов можно выпустить без БД и migration, но тогда каждая
  публикация будет требовать commit/deploy.
- DB-backed блог также может технически переиспользовать `ContentSource`,
  `ContentItem`, `ContentItemVersion` и `metadata_json` без новой таблицы. Для
  этого всё равно нужны blog service/admin API и строгая schema-validation
  metadata. Сейчас нет владельца/контракта полей `slug`, `excerpt`, blog category,
  hero image, publish state, related ordering и CTA policy.

### Где migration действительно нужна

- Для анонимной узнаваемости посетителя текущей схемы недостаточно.
  `AttributionEvent.user_id` обязателен, а `payments` хранит referer/landing URL,
  но не browser identity. Нет таблиц anonymous browser, page view/click, consent,
  identity binding или CTA exposure.
- Если персонализация должна переживать устройства/домены и затем связываться с
  CRM/payment, потребуются новые псевдонимные сущности и Alembic migration либо
  другой отдельно утверждённый identity contract. Запись непроверенного client
  marker прямо в `users`/`user_tags` нарушит текущую CRM-модель.

## 3. Similar Features

- `course_material_service.py` + `course_material_routes.py` +
  `tools/publish_course_material.py` — ближайший полный publish/version/restore
  pipeline. Переиспользуемы optimistic locking, immutable versions, размер
  материала, sanitization и post-publish readback.
- `intensive_routes.py` + `static/intensive/intensive.js` — более простой
  server editor одной публичной HTML-страницы. Переиспользуемы conflict handling
  и создание internal source; contenteditable HTML не подходит как канон для
  требуемых Markdown-файлов.
- `article_markup.py` + `masterclass_article_components.py` — готовый pattern
  закрытого DSL: Markdown никогда не получает произвольный script/iframe/style,
  компонент вызывается по известному имени и renderer возвращает allowlisted
  semantic HTML.
- `backend/app/static/masterclass-first-days-preview.html` — фактически
  реализованный compact article TOC: `configureArticleToc()` строит список из
  `h2`, не показывает его при менее чем трёх разделах, назначает anchors,
  подсвечивает текущий раздел, закрывает popover по ссылке/outside click/Escape.
  Контракт находится в `COURSE_STRUCTURE_CONTRACT.md` и
  `COURSE_VISUAL_SYSTEM.md`; код сейчас встроен в preview HTML, а не вынесен в
  общую article library.
- `backend/app/static/blog/index.html` — theme toggle уже сохраняет
  `edabalans-blog-theme` и уважает `prefers-color-scheme`; этот JS/CSS можно
  вынести в общий blog shell, чтобы главная и статьи не расходились.
- `content/author-voice/editorial-linking-v1.md` — существующая редакционная
  логика CTA и перелинковки: один основной следующий шаг, рабочая ссылка,
  смежный материал продолжает мысль, а не добавляется ради количества.

## 4. Integration Points

### Редакционный workflow

- Обязательный writer entry point —
  `content/author-voice/skill/edabalans-writer/SKILL.md`.
- Для адаптации полной статьи Pikabu применим профиль `develop_existing` с
  `source_basis=full_source`; допустимый mode и preservation anchors фиксируются
  до переписывания. Пользовательская просьба сохранить текст преимущественно
  дословно означает минимально достаточный rewrite/structure route, а не новый
  материал с нуля.
- `content/author-voice/author-task.schema.json` задаёт machine task;
  `tools/author_workflow.py prepare|validate|review` создаёт retrieval pack,
  проверяет сохранность и выдаёт hash-bound report. Только `pass` считается
  publish-ready.
- `content/author-voice/material-status-v1.md` разделяет редакторскую готовность,
  owner review, source review и delivery; одна метка «готово» их не заменяет.
- Нынешний publish CLI существует только для материалов курса. Для workflow
  «чат-писатель возвращает MD → блог-чат размещает компоненты → публикация» нужен
  отдельный blog publisher с теми же gates, а не прямое копирование результата в
  HTML.

### Markdown и CTA

- Универсальная `:::note` уже централизована в `ARTICLE_STANDARD.md` и
  `article_markup.py`.
- Product CTA `masterclass`, `intensive`, `telegram` пока не существуют как
  разрешённые Markdown-компоненты. Их нельзя реализовывать как raw HTML в MD:
  renderer либо отклонит небезопасные атрибуты, либо создаст второй источник
  дизайна/ссылок.
- Точные product names/descriptors должен поставлять `product_catalog_service.py`;
  цена/персональные условия принадлежат commerce/masterclass offers; Telegram
  tracking links принадлежат `messaging.telegram.attribution`. `platform.blog`
  может выбирать placement, но не должен копировать эти факты в карточки.
- Важная текущая потеря: course publisher хранит в `text_content` уже
  отрендеренный HTML, а не исходный Markdown. Если блог должен принимать и позже
  редактировать MD, источник Markdown должен иметь явного владельца (Git-файл или
  отдельное versioned поле/representation); класть его неформально в JSON без
  контракта создаст второй источник.
- Компоненты, отрендеренные в HTML в момент публикации, не обновятся при смене
  product link/copy без новой редакции статьи. Если CTA должен всегда читать
  актуальные product facts, нужен runtime resolver или управляемая массовая
  пересборка; это отдельное решение user-spec.

### CRM, интенсив и узнаваемость

- `users`, `user_emails`, `messenger_accounts`, `payments`, `user_accesses` и
  `user_tags` позволяют классифицировать уже доказанно известного человека.
- Новый web-интенсив (`products.intensive`) хранит содержание четырёх страниц,
  но не создаёт enrollment/progress человека. Новый Telegram-интенсив хранит
  прохождение в Telegram sequence runs; старый импорт оставил CRM tag
  «Старый интенсив - Пройден полностью». Единой функции
  `has_seen_or_completed_intensive(user_id)` в backend нет.
- Персональный `build_offers()` рассчитан на участника закрытого Мастер-класса и
  не является fallback для анонимного читателя. Для публичной статьи безопасный
  baseline — неперсональный CTA; персональный вариант возможен только после
  доказанной identity и отдельной продуктовой политики.
- `backend/app/static/embed.js` сохраняет Tilda identity в
  `localStorage['edabalans_identity_v1']` на origin, где загружено приложение.
  `localStorage` не доступен между `app.edabalans.ru`, основным русским доменом и
  `blog.похудение-это-есть.рф`. Admin cookie имеет domain `.edabalans.ru` и также
  не относится к русскому домену. Поэтому блог сейчас не узнаёт пользователя.
- Telegram attribution (`telegram-bot/service/app/tracking.py`) уверенно
  связывает identity только после Telegram `/start`/account event. Его
  first-touch и tags нельзя трактовать как историю анонимного браузера до link.

### Медиа и фото

- В tracked repository нет фотографии Сергея для blog hero. Источник фотографии
  нужно получить из принадлежащего владельцу файла/каталога и зафиксировать alt,
  cropping и право использования; случайное внешнее изображение не заменяет её.
- Pikabu collector сохраняет только remote media URL. Для надёжной собственной
  публикации нужен либо явно разрешённый external HTTPS URL, либо собственное
  asset storage/route. Текущий blog route отдаёт только два имени font files;
  произвольные image paths не обслуживаются.

## 5. Existing Tests

- Framework: backend — `pytest`/FastAPI `TestClient`; часть pure unit tests
  написана на `unittest`. CI строит backend Docker image и запускает весь
  `backend/tests`.
- `backend/tests/test_blog.py` покрывает только публичность текущей главной,
  hardcoded structure, две URL формы, font whitelist/cache и статические маркеры
  пагинации/theme/footer. Репрезентативные тесты:
  `test_blog_home_is_public_and_uses_the_accepted_structure()` и
  `test_blog_fonts_are_self_hosted_and_whitelisted()`.
- `backend/tests/test_article_markup.py` проверяет таблицы, broken column count и
  Markdown links. Нет тестов blog CTA directives, hostile component arguments,
  stable heading anchors или полной blog article rendering.
- `backend/tests/test_content_authoring_catalog.py` проверяет immutable owner
  revisions, import idempotency, conflict detection и обязательную admin auth.
  Репрезентативный тест:
  `test_owner_save_creates_immutable_revision_and_detects_conflict()`.
- `backend/tests/test_intensive_editor.py` проверяет публичное чтение после
  admin save, stale version, unknown day и восстановление старого текста.
- `tools/tests/test_publish_course_material.py` проверяет CLI publish gate и
  hash-bound validation artifacts; это ближайший шаблон blog publish tests.
- Отсутствуют E2E тесты публичного article URL, TOC keyboard/focus behavior,
  related links, CTA click target, OpenGraph/canonical metadata, image fallback,
  theme consistency между главной и статьёй и category filtering.

## 6. Shared Utilities

- `article_markup.safe_href()` — разрешает relative/http/https/mailto и блокирует
  protocol-relative/control characters.
- `article_markup.safe_image_src()` — по умолчанию только абсолютный HTTPS;
  relative path разрешается лишь в course semantics.
- `article_markup.sanitize_article_html()` — allowlist tags/attributes, удаление
  script/style/iframe/object/svg/math, запрет `h1` внутри body.
- `article_markup.article_plain_text()` — plain text для word count и проверок.
- `content_authoring_service.save_authoring_item()` — row lock, revision conflict,
  immutable version и перенос media/links в owner revision.
- `course_material_service.material_hash()` и `publish_material()` — стабильный
  content hash, max bytes, publish/restore pattern.
- `managed_documents.py` — versioned JSON documents; применим к небольшому
  blog manifest, если карточки будут управляться как один документ, но не
  заменяет версии длинных тел статей.
- `site-footer.js` — общий публичный footer; уже подключён блогом.
- `product_catalog_service.product_public()` — публичные product facts без цен и
  персональных условий.
- `product_identity.purchased_products()` и access queries — подтверждённые
  покупки/права известного `user_id`; не выполняют browser identification.

## 7. Potential Problems

### Контент и публикация

- Текущие шесть карточек — hardcoded placeholders. Без единого article manifest/
  query главная, related блок и canonical URL неизбежно разойдутся.
- `ContentFamily` не хранит редакционный порядок похожих статей. Автоматическая
  topical similarity также отсутствует; рекомендации должны иметь явный source
  и проверяемый fallback.
- Renderer не создаёт стабильные heading IDs. Preview Мастер-класса назначает
  `article-section-N` только в DOM; ссылки не являются устойчивыми между
  перестановками. Для публичных shareable anchors нужен единый deterministic
  contract.
- Current Markdown parser не поддерживает произвольный HTML/code fences и
  намеренно должен продолжать их не принимать. «Кодовые вставки» пользователя
  должны означать закрытые directives/component calls, не вставку JS/HTML.
- Внешние Pikabu media URLs оставляют блог зависимым от hotlink/изменения URL.
  Копирование авторских файлов в собственное хранилище требует provenance и
  управляемого asset path.
- Старый публичный пост не является актуальным медицинским источником.
  Writer workflow требует отдельного fact/source review существенных тезисов
  перед публикацией на сайте.

### Security

- Публичный MD/HTML нельзя отдавать без `sanitize_article_html`; raw script,
  iframe, event handlers и styles уже запрещены каноном.
- Article slug нельзя напрямую соединять с filesystem path. Нужен regex/lookup
  по известному slug и `404`; текущий font route показывает правильный whitelist
  pattern.
- Product offer endpoints нельзя вызывать из анонимного блога с email из
  query/localStorage. Клиентский marker не доказывает CRM identity и может
  раскрыть персональное состояние/цены другому человеку.
- CTA redirect должен использовать только разрешённые HTTPS/internal destinations
  и `rel="noopener"` для new tabs; существующий sanitizer уже даёт базовую
  защиту.

### Privacy и аналитика

- `docs/plans/WEBSITE_CLICK_PURCHASE_ATTRIBUTION.md` — явный owner plan со
  статусом `planned`. Он предусматривает first-party pseudonymous browser ID,
  30-дневное окно attribution и cookie до 365 дней только после отдельного
  согласования обработки.
- Этот plan прямо запрещает подключать production tracking/cookie на всём Tilda
  site без отдельной команды. Текущий запрос на обсуждение связи не доказывает
  согласование exact cookie lifetime, consent UI, retention/delete и checkout
  propagation.
- Опубликованная privacy policy уже говорит о cookie banner на первом посещении,
  но сам blog его не реализует. Добавление tracking до фактического consent
  flow создаст расхождение реализации и юридического документа.
- «Человек когда-то мелькал в базе» слишком широкое и неисполняемое правило:
  CRM может знать email из покупки, Telegram account или старого импорта, но
  браузер не знает, какой из этих users открыл страницу. User-spec должен
  определить доказательство identity и точный predicate intensive/masterclass.

### Data consistency

- `ContentItem.text_content` используется неоднородно: импортированный raw/plain
  text, owner-edited text и rendered semantic HTML у course publisher. Blog
  service обязан явно назвать representation/parser version и не угадывать тип.
- Использование `metadata_json` позволяет обойти migration, но без Pydantic schema,
  version и index приведёт к невалидным slug/category/related IDs. Если поля
  нужны для database filtering/uniqueness, отдельные columns/index могут быть
  предпочтительнее JSON; это решение должно быть принято до API.
- CTA, отрендеренный при publish, может устареть относительно product catalog.
  Dynamic CTA, напротив, требует fallback при DB/API failure и cache policy.

## 8. Constraints & Infrastructure

- Runtime: FastAPI `0.141.1`, SQLAlchemy `2.0.52`, Pydantic Settings `2.15.0`,
  PostgreSQL 17; `Markdown==3.8.2` установлен, но public/course content уже
  использует собственный закрытый renderer `article_markup.py`.
- Caddy ставит HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin` и gzip/zstd. Новый article/
  asset route должен остаться внутри этого host block.
- Автодеплой идёт из `main`; CI запускает module inventory, compose validation,
  Docker build и backend pytest.
- `.github/workflows/ci.yml` намеренно блокирует автоматический production deploy,
  если diff содержит Alembic migration. Поэтому статический/существующие-table
  этап можно выпустить штатно, а anonymous tracking migration требует отдельного
  backup/migration production шага и явного подтверждения владельца.
- По `AGENTS.md` реальные snapshots, cookie, browser profiles, персональные данные
  и private author corpus не попадают в Git. До импорта персональных данных нужен
  backup и restore check.
- `platform.blog` владеет публичной оболочкой/routes; `platform.content` — голосом,
  Markdown dialect, каталогом и writer workflow; `products.intensive` и
  `products.masterclass*` — продуктовой логикой; `platform.crm` — identity; Caddy
  и HTTPS — `operations.proxy`. Реализация затронет несколько module cards и
  registry relations, но не должна переносить продуктовые факты в blog HTML.
- В tracked assets нет author photo. Фото является обязательным входным asset,
  а не технической деталью, которую можно сгенерировать или заменить чужим.

## 9. External Libraries

- Для первой версии новый внешний пакет не требуется: внутренний renderer уже
  покрывает разрешённый Markdown и закрытые directives, FastAPI/SQLAlchemy дают
  routes и version storage.
- Установленный `Markdown 3.8.2` используется в других внутренних поверхностях,
  но для публичных авторских материалов его raw-output нельзя принимать без
  существующего sanitizer. Переход на него не устраняет component allowlist,
  XSS validation или стабильные heading IDs.
- Browser collection Pikabu использует Playwright из отдельного collector
  окружения; Chromium намеренно не входит в production backend. Публикация блога
  не должна запускать collector на web request.

## Итоговая трасса данных

```text
Pikabu/каталог (original item + metrics + media URLs)
  → author-task JSON с exact item_id и full_source
  → edabalans-writer: prepare → draft.md → validate/review → pass report
  → blog publisher: проверка report + placement закрытых CTA directives
  → article_markup + product-owned component renderers + sanitizer
  → immutable article version / Git artifact (выбор канона до реализации)
  → public article route
  → homepage card + related article links из того же metadata source
```

Персонализированная ветка не присоединяется к этой трассе автоматически:

```text
anonymous browser
  → consented first-party browser identity (сейчас отсутствует)
  → доказанная привязка к CRM user_id (сейчас отсутствует)
  → точный predicate intensive/masterclass (сейчас не унифицирован)
  → выбор CTA без раскрытия персональных данных
```
