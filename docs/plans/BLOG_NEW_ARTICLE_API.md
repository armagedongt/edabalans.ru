---
document_status: planned
implementation_status: planned
date: 2026-09-20
module_id: platform.blog
origin: owner-explicit
---

# ТЗ: создание новых статей в блоге из Markdown через API

## Решение владельца

Создание новых статей отложено. Текущий редактор работает только с уже
зарегистрированными статьями из `content/blog/manifest.json`. Этот документ
описывает отдельный будущий этап и не является признаком реализованной функции.

## Цель

Дать Сергею один канонический Markdown-исходник, из которого можно без deploy:

1. создать новую статью как закрытый черновик;
2. загрузить и переиспользовать изображения;
3. проверить страницу в реальном оформлении блога;
4. отправить материал на модерацию;
5. явно опубликовать готовую версию;
6. позднее исправлять тот же Markdown и выпускать новую редакцию.

Создание черновика никогда не должно само публиковать URL, карточку или медиа.

## Необходимая архитектурная граница

Сейчас публичные идентичности, SEO-поля, порядок, CTA, related и media
принадлежат Git-manifest. API не может добавлять туда запись без deploy. До
реализации создания новых статей нужен один серверный registry публикаций, а не
второй список рядом с manifest.

Будущий этап должен:

- завести серверную запись статьи с неизменяемым ID и уникальным slug;
- один раз перенести в registry все существующие manifest-записи;
- сохранить Git fallback до проверки эквивалентности рендера;
- после приёмки переключить catalog, article, sitemap и related на registry;
- оставить экспорт полного Markdown-пакета, чтобы сервер не стал единственным
  местом, из которого невозможно забрать исходник.

Переключение источника является миграцией production data: до него обязательны
backup, проверенное восстановление и отдельное подтверждение владельца.

## Модель данных

### Article identity

Обязательные поля:

- стабильный внутренний `article_id`;
- уникальный `slug`;
- `title`, `excerpt`, `category`;
- `visibility = public | internal`;
- `editorial_status = draft | moderation | approved | published | archived`;
- `source_id` и список provenance-ссылок;
- `cta_key`;
- три `related_article_id` для публичного выпуска;
- hero и card как отдельные media references;
- created/updated/published timestamps и actor;
- текущая draft version и отдельная published version.

После первого публичного выпуска slug либо неизменяем, либо его изменение
атомарно создаёт постоянный redirect. Тихо ломать старый URL запрещено.

### Markdown versions

Версия хранит чистый Markdown без H1, raw HTML, script, CTA-компонентов, header
и footer. Presentation добавляет surface adapter. У версии есть SHA-256,
номер, автор изменения и дата. `expected_version` защищает от перезаписи.
Восстановление старой версии создаёт новый draft и не меняет live автоматически.

### Media storage

Base64 внутри каждой версии запрещён для production-create. Нужны отдельные
content-addressed media objects:

- SHA-256, mime, размер, width/height;
- alt и provenance;
- immutable public URL;
- ссылки hero/card/body;
- дедупликация одинаковых bytes;
- удаление только объекта, на который больше нет draft/published references;
- backup/restore вместе с БД;
- отдельные лимиты и защита от decompression bomb.

PNG/JPEG/WebP поддерживаются первыми. GIF, видео, SVG и внешние embeds получают
отдельную явно описанную политику; их нельзя молча превращать в обычную картинку.

## API

Минимальный будущий surface:

| Метод | Маршрут | Результат |
|---|---|---|
| `POST` | `/admin/api/blog/articles` | Создать закрытую identity и draft version 1 |
| `GET` | `/admin/api/blog/articles/{id-or-slug}` | Exact metadata, Markdown, media refs, история |
| `PATCH` | `/admin/api/blog/articles/{id-or-slug}` | Version-gated metadata/Markdown draft update |
| `POST` | `/admin/api/blog/media` | Проверить, дедуплицировать и загрузить media object |
| `POST` | `/admin/api/blog/articles/{id-or-slug}/preview` | Рендер без записи |
| `POST` | `/admin/api/blog/articles/{id-or-slug}/publish` | Явно выпустить указанную draft version |
| `POST` | `/admin/api/blog/articles/{id-or-slug}/restore/{version}` | Создать новый draft из истории |
| `POST` | `/admin/api/blog/articles/{id-or-slug}/archive` | Снять/архивировать по принятой redirect-политике |
| `GET` | `/admin/api/blog/articles/{id-or-slug}/export` | Скачать переносимый Markdown-пакет |

Create и media upload должны поддерживать idempotency key. Частично загруженный
пакет не создаёт публичную статью. Повтор запроса после сетевой ошибки возвращает
тот же результат, а не второй slug или вторую копию media.

## Интерфейс

В существующей «Редакции блога» появляется кнопка «Новая статья». Форма включает:

- title, slug с явным подтверждением, excerpt, category;
- Markdown и реальный preview;
- visibility и editorial status;
- source/provenance;
- CTA key;
- загрузку body media, выбор hero и отдельной card cover;
- alt для каждого изображения;
- три related-кандидата перед публикацией;
- статусы validation/review и понятный список блокеров выпуска.

Автосохранение не публикует. При конфликте версия не затирается; локальный текст
остаётся в поле. Кнопка публикации недоступна при несохранённых изменениях.

## Редакционные и publish gates

Новая публичная статья выпускается только когда:

- есть exact source/provenance;
- writer validation и review имеют `pass`;
- factcheck-риски зафиксированы отдельно от авторского текста;
- Markdown не содержит H1, raw HTML/script, площадочные хвосты и встроенный CTA;
- назначены category, excerpt, CTA, hero, card и три published related;
- изображения локальные, проверенные и имеют provenance/alt;
- public preview не содержит внешних hotlinks и ровно один surface CTA;
- slug, canonical, OG/Article metadata и sitemap entry проходят проверку.

`internal` и `moderation` всегда получают `noindex`, отсутствуют в публичном
catalog/sitemap/related и возвращаются только после admin auth.

## SEO и публичный renderer

Server registry становится владельцем title/description/category/canonical,
hero/card, Article structured data, related и sitemap `lastmod`. Дата источника,
дата первой публикации в блоге и дата последней существенной редакции — разные
факты. Нельзя выдумывать дату или обновлять её только ради видимости свежести.

Публичный URL остаётся `/articles/{slug}`. Preview и moderation URL закрыты
авторизацией, `private, no-store`, `noindex, nofollow`. Архивация не должна
создавать случайный soft-404; политика 404/410/redirect утверждается до запуска.

## Безопасность

- использовать существующий admin login, не создавать второй пароль/кабинет;
- cookie mutation — только same-origin; программный клиент — HTTPS Basic либо
  будущий отдельный ограниченный token;
- create/publish/archive/restore пишут actor, timestamp и version;
- quotas применяются до полного разбора body;
- пути, имена media и slug проходят allowlist validation;
- SVG/HTML не исполняются; mime определяется по bytes;
- unknown/internal материалы не раскрываются через ошибки, media, поиск,
  sitemap, related, JSON-LD и cache.

## Миграция существующих статей

1. Сделать backup БД и media storage, проверить restore.
2. Импортировать manifest identity/SEO/CTA/related/media и exact Markdown.
3. Сравнить по каждой статье rendered body, число media, canonical, CTA и related.
4. Запустить dual-read в тестовом контуре: DB registry с Git fallback.
5. Проверить все существующие URL, sitemap и отсутствие дублей/404.
6. Отдельно подтвердить production source switch.
7. Сохранить rollback на Git snapshot до окончания наблюдения.
8. Только после приёмки архивировать старый write path; экспорт Markdown оставить.

## Аналитика

Создание статьи не добавляет отдельный аналитический движок. Публичный renderer
использует общий контракт событий блога: article view, scroll depth, CTA click,
popup impression/click и downstream attribution. Draft/preview действия не
смешиваются с публичной статистикой. Изменение текста сохраняет published
version ID, чтобы сравнение периодов не приписывало старой редакции новые данные.

## Проверки

### Unit

- slug/Markdown/metadata/media validation;
- SHA/dedup/reference counting;
- CTA/related/publish gates;
- export/import round-trip.

### Integration

- idempotent create и media upload;
- optimistic conflicts;
- draft не виден public;
- explicit publish меняет catalog/article/sitemap атомарно;
- internal/moderation не индексируются;
- restore создаёт draft, не меняет live;
- archive/redirect contract;
- migration и rollback всех существующих статей.

### Browser

- создать → загрузить media → preview → moderation → publish;
- ошибки/409/сеть не теряют Markdown;
- keyboard/mobile 360/430/768/1440;
- hero/card/body media и единственный CTA выглядят как в public blog.

### Operations

- backup/restore DB и media;
- orphan cleanup не удаляет используемые blobs;
- CI запускает backend, browser и migration tests;
- test contour пройден до production confirmation.

## Критерии приёмки

- [ ] Неизвестный slug можно создать только через новый explicit create route.
- [ ] Новый материал после create закрыт и не появляется в public surfaces.
- [ ] Exact Markdown экспортируется без потери provenance и media references.
- [ ] Media bytes не дублируются между версиями и статьями.
- [ ] Publish атомарен, version-gated и требует явного действия.
- [ ] Public catalog/article/SEO/sitemap читают один server registry.
- [ ] Девять текущих URL после миграции визуально и семантически эквивалентны.
- [ ] Rollback на Git snapshot проверен до source switch.
- [ ] Fresh code, security, test, infrastructure, layout и documentation reviews — pass.

## Вне будущего этапа без отдельного решения

- WYSIWYG и полноценный визуальный конструктор;
- автоматическое переписывание авторского текста;
- автоматическая публикация сразу после импорта;
- новый пользовательский login;
- изменение product CTA, popup или рекламной логики;
- импорт персональных данных и массовая рассылка.
