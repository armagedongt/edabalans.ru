# Исследование SEO-контура блога

Проверено: 04.10.2026. Рабочая ветка: `codex/blog-seo-workbench-20261004`.
Исследование read-only; авторские тексты, production и рекламные настройки не менялись.

## 1. Entry Points

- `backend/app/blog_routes.py` — `blog_article(slug: str, db: Session)` собирает публичный HTML, JSON-LD Article, canonical и OG. Сейчас один `article.title` используется в H1, OG, Article.headline и `<title>` с суффиксом бренда.
- `backend/app/static/blog/article.html` — публичный шаблон. Отдельного placeholder для поискового заголовка, авторского профиля или дат нет.
- `backend/app/blog_content.py` — `split_blog_metadata(markdown: str) -> tuple[str | None, str]` допускает только один начальный ключ `description`; `seo_title` сейчас вызывает 422. `blog_description(markdown: str) -> str` использует явный description либо первые два предложения безопасно отрендеренного Markdown; fallback обрезается до 300 символов.
- `backend/app/blog_draft_routes.py` — owner-only `GET /admin/api/blog/articles/{slug}` возвращает активную редакторскую версию, Markdown и историю. Это не гарантированно опубликованная версия: следующий draft может быть новее public.
- `backend/app/blog_draft_service.py` — `public_payload(db: Session, slug: str) -> dict | None` читает опубликованный body поверх manifest-контракта. HTTP-маршрута публичного exact-source JSON API в `blog_routes.py` нет.

## 2. Data Layer

- `content/blog/manifest.json` — владелец идентичности, title, category, permitted media, CTA, related. Отдельные записи содержат `original_published_at`, но `BlogArticle` сейчас не читает этот ключ.
- `backend/app/blog_content.py` — frozen dataclass `BlogArticle` содержит source_id, slug, title, excerpt, category, body_file, hero/card, related_source_ids, CTA, status, media. Нет author_id, original_date, blog_publication_date, modified_date, seo_title.
- `backend/app/models.py` — `ManagedDocumentVersion` хранит document_type/key, version_no, JSON payload, content_hash, created_by, is_active, created_at. Уникальность version и активной версии обеспечивается constraints/indexes.
- `backend/app/blog_draft_service.py` — `effective_article_payload(version)` и `public_payload(db, slug)` обновляют manifest-managed данные из Git; из БД в публичный результат переносятся Markdown/hash и выбранная карточка. Произвольная package.metadata не становится публичным SEO-контрактом автоматически.
- `backend/app/blog_draft_routes.py` — `DraftTextUpdate` меняет Markdown/card/fit с expected_version; `DraftPackage.metadata` непрозрачный dict. На входе metadata ограничена 100 KiB в `prepare_package`.

Для текущего каталога исходный baseline следует получать из `public_payload` + fallback, а не из active draft. Доказанный существующий read-only способ — remote Python в текущем backend через SessionLocal; тело команды и HTTP-сверка уже реализованы в `work/blog-seo-analytics/verify-descriptions-20261001.py`.

## 3. Similar Features

- `work/blog-seo-analytics/verify-descriptions-20261001.py` — читает server canonical опубликованный Markdown, вычисляет description и отдельно проверяет публичные meta/OG/canonical. Результаты не подменяют полный аудит текста и медиа.
- `D:/Codex/work/article-family-integration-20260925/work/blog-reader-preview-20261001/serve.py` — локальный loopback/noindex образец статьи Японии. Две contextual cards вставлены до конкретных H2 regex-якорями; это hardcoded fixture, не production renderer.
- `.../blog-reader-preview-20261001/avatar.webp` — фотография, использованная в согласованном локальном примере. Авторская подпись в serve.py: «Сергей Воронцов 🍌», роль «Тренер по питанию», текст «Пишу о питании и похудении так, чтобы вы менялись.»
- `.../blog-reader-preview-20261001/reader.js` — демонстрационный subscription gate: приглашение не показывается опознанному подписчику или при Telegram-origin fixture. Реальное определение человека/подписки и аналитика не подключены.
- `.../blog-reader-preview-20261001/README.md` — явно отделяет локальный прототип от production и документирует браузерные проверки. Прежние две inline-карточки не соответствуют новому правилу владельца «не более одной» без изменения fixture.

## 4. Integration Points

- `_public_catalog(db)` в `blog_routes.py` накладывает опубликованные description на Git-каталог; один результат используется карточками и статьёй.
- `related_cards_html(catalog, article, *, card_overrides=None)` в `blog_content.py` читает ручные `related_source_ids`, проверяет разрешение каждой ссылки и выводит карточки. Подбор не случайный и не автоматический.
- `blog_article` сейчас публикует Person только с именем «Сергей Воронцов»; author.url/@id, datePublished/dateModified и BreadcrumbList отсутствуют.
- `blog_sitemap()` содержит только loc; даты lastmod не выводятся.
- `docs/knowledge-base/BLOG_API_AUTHORING.md` фиксирует manifest-owned title/CTA/related и отсутствие production автоматического related, popup и blog-аналитики.

## 5. Existing Tests

- `backend/tests/test_blog_description.py` — pytest: fallback, выделения/ссылки без лишних пробелов, CRLF, неправильный header, кеширование и draft/public изоляция. Репрезентативные signatures: `test_explicit_description_wins_without_becoming_article_body()`; `test_description_stays_draft_until_publish_and_drives_catalog_and_page(description)`.
- `backend/tests/test_blog_draft_authoring.py` — pytest: version gates, seed/publish/draft isolation, manifest ownership, обложки и security boundary. Репрезентативные signatures: `test_existing_article_seed_publish_and_later_draft_do_not_leak(authoring)`; `test_manifest_managed_draft_refreshes_canonical_fields_before_publish(authoring)`.
- `backend/tests/test_blog_content.py`, `test_blog.py` — каталог, HTML-рендеринг и публичные маршруты.
- `backend/tests/blog-pagination.test.cjs`, `backend/tests/browser/blog-draft-authoring.e2e.mjs` — browser-side pagination и editor flow.
- Локальный `blog-reader-preview-20261001/gate.test.cjs` — пять Node checks для demo gate; не доказывают реальную subscriber интеграцию.

## 6. Shared Utilities

- `backend/app/article_markup.py` — `markdown_to_article_html`, `article_plain_text`, `safe_href`: безопасный рендеринг и извлечение текста.
- `backend/app/blog_draft_service.py` — seed/public/version serialization; готовый канал публикации существующих идентичностей без нового отдельного хранилища.
- `backend/app/public_cta_catalog.py` — действующие CTA принадлежат продуктовым владельцам; не формировать новые обещания в SEO metadata.

## 7. Potential Problems / доказанные границы

- Сохранить seo_title лишь в package.metadata недостаточно: manifest overlay его не выводит, Markdown parser отвергает новый ключ.
- `GET` редакторского API не эквивалентен публичному source: может возвратить неопубликованные изменения.
- `ManagedDocumentVersion.created_at` — время конкретной версии в БД, не доказательство первой публикации на Pikabu/в канале или первого Git-выпуска. Даты исходников и блога нельзя автоматически смешать.
- Текущий description общий для meta, OG, каталога и конечного related. При будущей смене на поисковый вариант это изменит и анонсы карточек, если не разделить контракт явно.
- Прототип читательских вставок пока не содержит реальной identity/subscription интеграции; его тестовые переключатели не переносить в public.

## 8. Constraints & Infrastructure / Wordstat

Владелец рабочих доступов — `docs/knowledge-base/YANDEX_DIRECT_OPERATIONS.md`, его штатный API-чеклист — `.codex/skills/yandex-direct-operations/SKILL.md`. Секреты не читать и не копировать в Git/отчёт; backend уже имеет `YANDEX_DIRECT_TOKEN`, значение не запрашивалось.

### Установленная история двух разных механизмов

1. `work/yandex-search-20260904/README.md:22–45` описывает Cloud Wordstat API v2: Россия, все устройства, последние 30 дней, 8 запросов и около 160 ₽ из гранта Yandex Cloud. Это исторический оплачиваемый механизм, не доказательство бесплатности нового batch.
2. История чата «Я.Директ!» (`01a05eae-2663-7d93-a2a7-505db44f3b7a`, запросы 25.09.2026) содержит успешный legacy Direct v4 Wordstat: URL `https://api.direct.yandex.ru/live/v4/json/`, methods `CreateNewWordstatReport`, `GetWordstatReport`, GeoID `[225]`. Скрипт брал token только из окружения существующего backend-контейнера через `ssh edabalans-prod`, не экспортируя значение локально. Report ID `1599714092` исторический: TTL делает его непригодным для текущего чтения.

### Проверено по официальной документации 04.10.2026

- [Статистика и аналитика Direct](https://yandex.ru/dev/direct/doc/ru/best-practice/statistics) продолжает направлять подбор фраз к версии 4/Live 4.
- [CreateNewWordstatReport](https://yandex.ru/dev/direct/doc/dg-v4/ru/reference/CreateNewWordstatReport.html): до 10 фраз в запросе, до 1000 фраз на пользователя за сутки, до 5 хранимых отчётов, хранение 5 часов; подготовка обычно до минуты. Метод расходует API-баллы, а не рекламный бюджет.
- [Ограничения Direct API](https://www.yandex.ru/dev/direct/doc/ru/troubleshooting/limits): API предоставляется бесплатно; доступ ограничен квотами/баллами. Конкретный остаток баллов и нынешняя действительность токена этим исследованием не проверены.
- [GetWordstatReport](https://yandex.ru/dev/direct/doc/dg-v4/ru/reference/GetWordstatReport.html) возвращает SearchedWith/SearchedAlso, Shows за прошедший месяц. Это не уникальные люди и не прогноз органических кликов.
- [Тарификация Search API](https://aistudio.yandex.ru/ru/docs/search-api/pricing) содержит отдельные оплачиваемые Wordstat GetTop/GetDynamics/GetRegionsDistribution. Не смешивать с бесплатным Direct v4 и не вызывать Cloud как молчаливый fallback.

В этом исследовании ни один Wordstat API вызов не выполнен: нет новых отчётов, списания квоты, рекламных/remote mutations. Поддержка legacy доказана документацией и сентябрьской историей; работа конкретного доступа сегодня требует ограниченной отдельной проверки основного потока.

### Найденный конкретный архивный raw

Read-only путь: `C:/Users/Segey/.codex/worktrees/f932/edabalans.ru/marketing-attribution/work/yandex-search-20260904/wordstat-raw.json` (180895 байт). Файл содержит 8 тем, 1397 results и 128 associations. Темы: похудеть; начать худеть; похудение без диет; вес возвращается после похудения; срывы при похудении; похудеть без силы воли; как похудеть навсегда; правильное похудение.

Дата исследования — 04–05.09 по README; filesystem mtime 04.09.2026 23:58:59. Сам JSON не содержит timestamp/регион/устройства/операторы, поэтому точный период не восстанавливать из mtime. Отдельных кластеров мёда, Японии и 10 тысяч шагов этот архив не содержит. Raw не копировался в Git.

## 9. External Libraries

Новые внешние библиотеки для обсуждаемой SEO metadata задачи не выявлены. Текущий стек — FastAPI/Pydantic/SQLAlchemy, Python JSON/HTML/regex; Wordstat исторически вызывался стандартным `urllib.request`, без SDK. Исследование API выполнено по официальной документации, не по сторонним клиентам.
