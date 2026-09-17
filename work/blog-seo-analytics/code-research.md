# Исследование контура блога: SEO, аналитика и публикация

Статус: `draft`.
Дата: 17.09.2026.
Область: `platform.blog`; зависимости `platform.content`, `marketing.analytics`, `platform.auth`, `products.public-site`, `operations.proxy`. Исследование read-only, кроме этого документа; runtime не изменён.

## Entry Points

- `backend/app/blog_routes.py` — `blog_home()`, `blog_article(slug: str)`, `blog_sitemap()`, `blog_robots()`: HTML, metadata и sitemap собираются из Git-каталога при запросе. Публичный origin берётся из `BLOG_PUBLIC_ORIGIN`; JSON-LD уже содержит Article и Person, но не авторский URL и даты.
- `backend/app/blog_content.py` — `load_blog_catalog(content_dir: Path | None = None) -> BlogCatalog`, `validate_blog_catalog(catalog)`, `related_cards_html(catalog, article)`: чтение manifest, безопасное рендерирование и три связанные карточки по source ID.
- `backend/app/static/blog/article.html`, `index.html` — общая cookie-плашка и footer уже подключены внешними script URL `https://edabalans.ru/cookie-notice.js` и `site-footer.js`. На статье нет видимой строки автора/даты.
- `backend/app/static/blog/assets/blog.js` — каталог с 15 карточками на странице, тема и оглавление. Отдельного сборщика чтения, popup и связанной с CRM идентификации здесь нет.
- `infra/caddy/Caddyfile` — на blog-субдомене разрешены главная, articles, blog assets/fonts/media, robots/sitemap и favicon. Прочие пути возвращают 404: в частности, общего `/api/*` на blog-origin сейчас нет.

## Data Layer

- `content/blog/manifest.json` — единственный текущий publication manifest: source_id, slug, title, excerpt, category, body_file, hero/card provenance, related_source_ids, cta, status, media. `BlogArticle` сейчас не имеет author_id, publication/source dates, tags или related mode.
- `content/blog/articles/*.md`, `content/blog/media/*` — тела и локальные файлы публикации; Git/deploy, не PostgreSQL, являются источником активного блога.
- `backend/app/models.py::ManagedDocumentVersion` — общий reusable слой версий: document_type/key, schema_version, version_no, JSON payload, hash, created_by/at, is_active. Уникальные индексы защищают одну активную редакцию и номер версии.
- `backend/app/models.py::PublicHomepageEvent` — anonymous first-party reach events, session UUID, hashed viewer UUID, page/section/event, timestamp. Уникальность session/page/event/section делает повторные observer-события идемпотентными; user_id, attribution journey и время активного чтения отсутствуют.
- `backend/app/public_homepage_analytics_routes.py::PublicHomepageEventIn` — принимает только `page_open`/`section_seen`, единственный PAGE_ID `masterclass-homepage-2026` и закрытый набор секций. Это не универсальный article endpoint.

## Similar Features

- `backend/app/public_site_routes.py` — GET `/api/public-site/content/{slug}`, защищённые GET/PUT `/admin/api/public-site/content/{slug}`. `PublicSiteContentUpdate` содержит markdown и expected_version; текущий whitelist — семь документов главной, не статьи блога.
- `backend/app/public_site_content_service.py` — `publish_public_site_document(db, *, slug, markdown, expected_version, admin)` нормализует Markdown и публикует новую активную редакцию. DOCUMENTS ограничивает допустимые ключи; это нельзя использовать для произвольного blog slug без отдельного product service.
- `backend/app/managed_documents.py` — `publish_document(..., expected_version, admin, commit=True)`, `restore_document(...)`, `version_history(...)`: блокировка активной строки, 409 при конкурирующей редакции, SHA-256 payload, сохранение последних 20 версий, откат как новая версия.
- `tools/publish_public_site_content.ps1` и `backend/app/public_site_content_cli.py` — существующий MD→сервер publication route через SSH/stdin и service с optimistic version. Это не HTTP blog publication API и не загрузчик медиа.

## Integration Points

### Cookie и consent

- `backend/app/static/site-cookie-notice.js` — единая реализация `EdabalansCookieNotice.accepted()/accept()/boot()`, событие `edabalans:cookie-accepted`. Cookie `edabalans_cookie_notice=accepted-v1`, срок год, Path=/, SameSite=Lax, Secure на HTTPS, Domain=.root для `edabalans.ru` и punycode `похудение-это-есть.рф`.
- Скрипт выполняется в origin документа, даже если загружен с edabalans.ru. Поэтому закрытие на русском apex уже разделяется с blog-субдоменом этого apex. Cookie не переносится между независимыми root-доменами edabalans.ru и русским доменом.
- Это уведомление с одним acknowledgement, не гранулярный consent manager. Сам скрипт не блокирует аналитику и не подтверждает согласие на сообщения/маркетинговую рассылку.
- `backend/app/static/homepage-preview/release-candidate.html` — first-party homepage tracker создаёт localStorage viewer/sessionStorage session и сразу отправляет page_open; IntersectionObserver threshold .3 отправляет section_seen. Ожидания события cookie-accepted в этом tracker нет.

### Identity и переходы

- `backend/app/account_auth_routes.py` — `native_session_user(request, db)`, GET `/api/account-auth/session`. Сессия `edabalans_account_session` HttpOnly/Secure/SameSite=Lax/Path=/, **без Domain**, следовательно host-only. GET session возвращает authenticated и email; это не специально минимизированный popup suppression endpoint.
- На blog нет маршрута для проверки account session; cookie основного хоста не передаётся blog-субдомену. localStorage также origin-scoped. Нельзя установить «человек есть в боте» по факту закрытия cookie, теме сайта, local viewer UUID или анонимному клику.
- `backend/app/personal_tracking_routes.py` — `/m/{token}` и `/p/{post_number}/{token}` используют уже выданный access token, записывают AttributionEvent с настоящим user_id и переходят на мастер-класс/пост канала. Source context явно не создаёт login session и не может подменять identity.
- `docs/knowledge-base/modules/catalog/marketing.analytics.md` — отчёт пути лида различает landing_button_click, landing_qr_scan, подтверждённый start_first/start_repeat и открытие дней. Подготовка URL не считается кликом; клик не считается Start. Отчёт read-only; состояние неизвестного этапа показывается «не подключено», не ложный ноль.

## Existing Tests

- `backend/tests/test_blog.py` — публичные страницы, metadata/CTA/related, whitelist media/fonts/styles, отсутствие старого бот-теста, sitemap, все опубликованные материалы. Сигнатуры: `test_blog_article_has_toc_cta_metadata_and_related_cards()`, `test_blog_is_indexable_and_sitemap_lists_all_articles()`.
- `backend/tests/test_blog_content.py` — закрытые компоненты, manifest и media/related validation. Новые author/date/auto-related поля сейчас не проверяются, потому что их нет.
- `backend/tests/blog-pagination.test.cjs` — Node VM проверяет реальный script: 15+остаток, фильтр/reset и deep-link/clamp. Pytest wrapper пропускается при отсутствии Node.
- `backend/tests/test_public_homepage_analytics.py` — `test_collects_anonymous_open_and_section_once_per_session()`, неправильные event/section, встроенный tracker. Не покрывает article progress/popups/CRM linkage.
- `backend/tests/test_public_site_content.py` — публикация с optimistic version, 409 на stale write, admin requirement, sanitization. `test_admin_update_creates_version_and_rejects_stale_write()` — близкий шаблон будущего blog publisher.

## Shared Utilities

- `backend/app/article_markup.py` — `markdown_to_article_html`, `article_plain_text`, `safe_href`: единая безопасная Markdown-семантика. Blog передаёт собственный закрытый component renderer; смена transport не должна обходить его.
- `backend/app/public_cta_catalog.py` — владельцы продуктов поставляют разрешённые CTA; blog renderer уже добавляет `data-tracking-key` ссылке. Рендер tracking атрибута не является доказательством работающего сборщика кликов.
- `backend/app/auth.py::require_admin` — общая административная защита, используется content PUT. Публичный reader и publisher не должны иметь одинаковые полномочия.
- `content/article-components/typography.css`, `note.css` — общий с МК presentation contract; blog выдаёт точные файлы через whitelist. Редакционные gate принадлежат Writer, не SEO-сервису.

## Potential Problems

- Отправка новых article events в homepage endpoint будет отвергнута валидатором. Относительный fetch `/api/...` на blog вообще попадёт в Caddy404 до FastAPI.
- Cross-origin проверка apex identity потребовала бы точного CORS/credentials контракта; широкое раскрытие `/api/*` на blog или перенос auth cookie Domain расширяет security boundary. Из чтения кода не следует разрешение на такое изменение.
- Scroll percentage всего документа включает hero/related/footer и не доказывает чтение текста. Надёжный article reading signal требует отдельно определить активное видимое время и прогресс authored body; не называть scroll «прочитал».
- Пользователь утвердил предложение popup несвязанному посетителю. Это правило не требует утверждать, что он отсутствует в боте; состояние без серверной идентификации — unknown/unlinked. Ошибка identity API не является отрицательной проверкой пользователя.
- Current file assets immutable URL: обновление байтов под прежним media URL ломает cache contract. Версии, происхождение и исторические доступные имена необходимо сохранять при API публикации.
- source date, первая подтверждённая публикация текста и публикация конкретной blog edition — разные поля. «Pikabu минус один день» — оценка, не подтверждённая дата; runtime не содержит основания для такого утверждения.
- Current related ровно три published, уникальны и не self. Автоматизация не должна обходить этот invariant, ссылаться на draft или считать 136 рабочих групп уже пригодными материалами.
- Managed publication создаёт PostgreSQL runtime source; простое добавление PUT при сохранении текущего Git-reader даст два расходящихся источника. Media upload, atomic bundle, cache invalidation и rollback не решаются одним reused version function.

## Constraints & Infrastructure

- `backend/requirements.txt` — FastAPI0.141.1, SQLAlchemy2.0.52, Alembic1.19.1, Markdown3.8.2, PostgreSQL driver psycopg3.3.4. Исследование existing APIs не вводит новой библиотеки, поэтому внешняя библиотечная документация не требовалась.
- Поля author/date/topics и deterministic related можно реализовать в существующем Git manifest без DB migration и без правок фактуры. Авторская страница требует FastAPI route + точного Caddy route и sitemap/tests; отдельного SEO data store сейчас нет.
- Настоящий DB-backed publication через reuse managed_document_versions технически возможен без обязательной новой version table. Однако перенос активных blog bundles, запись media/metadata, backup/recovery и однозначный reader source — самостоятельная согласуемая граница импорта, не механическая подмена файлов.
- First-party blog analytics persistence отсутствует; добавление нового event model требует Alembic migration. Добавление SEO goals в существующую Метрику и расширение рекламного отчёта зависит от владельца marketing attribution, не от blog text renderer.
- Caddy предоставляет blog ограниченный public namespace. Для новых endpoint выбирать явный маршрут, не открывать blog→весь API.

## Граница минимального текущего пакета

Уже существующий `platform.blog` владеет SEO rendering/publication/related и является найденным владельцем контура, `platform.content` — голосом/правами/markup, `marketing.analytics` — сквозным lead reporting. Из текущей структуры не следует необходимость отдельного дублирующего SEO-модуля. README может маршрутизировать эти существующие источники, не создавать копии их правил.

Прямые изменения текущих статей ограничиваются конкретно указанными историческими media/продажным повтором; фактура не разрешена к обновлению. Транспорт API, новые cookies/identity и import130документов не являются автоматически выполненным этапом от одной заявки на рекомендации.
