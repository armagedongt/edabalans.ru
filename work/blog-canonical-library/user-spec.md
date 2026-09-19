---
created: 2026-09-20
status: approved
type: feature
module_id: platform.blog
---

# User-spec: закрытый API и Markdown-редактор блога

> **Executor instruction.** If the project has Project Knowledge, first read its main `SKILL.md`,
> then only the materials it routes to for this task. Read `decisions.md` if it exists. Work from
> the root of the project this spec belongs to. Implement the entire user-spec. Use the execution
> skills appropriate to the work.

## What We Are Building

Подключаем к существующему backend закрытый API пакетов статей: точный Markdown, metadata, provenance и изображения. Автор после общего входа `edabalans.ru/admin` видит закрытые материалы в блоге, открывает предпросмотр и делает небольшие текстовые правки в простом textarea-редакторе.

## Why

Это проверяет основу массовой публикации без нового deploy для каждой правки и без второго независимого авторского текста. Девять действующих Git-backed статей и их публичные URL остаются неизменными.

## Expected Behavior

1. Admin загружает пакет по стабильному slug через API. Новый пакет и любая правка получают статус `moderation`.
2. `visibility=public|internal` и `editorial_status=moderation|approved` независимы, но все DB-пакеты этого этапа закрыты независимо от metadata. Публичного approve/source-switch нет.
3. Существующий `ManagedDocumentVersion` хранит активную редакцию и последние 20 версий. `expected_version` защищает от перезаписи; идентичный payload не создаёт версию.
4. Owner-каталог, preview, source и media доступны только существующему admin. Anonymous получает прежний Git-каталог без DB-данных.
5. Редактор сохраняет только текст, не требует повторной передачи metadata/media, не теряет локальную правку при 409/сетевой ошибке и предупреждает перед закрытием.
6. Surface adapter рендерит чистый Markdown общим renderer, переписывает packaged media URL и добавляет typed CTA из metadata. CTA, header/footer и script в MD не хранятся.
7. Владелец видит четыре фильтра: «Все», «Публичные», «Служебные», «На модерации». В редакторе всегда видны название, статус и номер текущей редакции.

## API Contract

Маршруты:

- `GET /admin/api/blog/articles` — summary без Markdown и base64;
- `GET /admin/api/blog/articles/{slug}` — точный source package и история;
- `PUT /admin/api/blog/articles/{slug}` — create/replace полного пакета;
- `PATCH /admin/api/blog/articles/{slug}/text` — только `{expected_version, markdown}`;
- `POST /admin/api/blog/articles/{slug}/preview` — preview текущего либо переданного Markdown без записи;
- `GET /blog/drafts/{slug}`, `/edit`, `/media/{name}` — закрытые owner surfaces.

Полный PUT JSON:

```text
expected_version: integer >= 0
title: 1..200 chars
excerpt: optional, 0..500 chars (для будущей публичной карточки; test fixture может не иметь)
category: one of BLOG_CATEGORIES
markdown: 1..250000 chars and <=250 KiB UTF-8
visibility: public | internal
editorial_status: moderation (единственное разрешённое значение этого этапа)
cta: existing public CTA key
sources: 1..20 absolute http(s) URLs or content:// provenance IDs
source_id: optional stable external/library ID, max 160
media: 0..8 objects {
  name: safe lowercase *.png|*.jpg|*.webp,
  content_base64,
  provenance: non-empty URL/text <=2000,
  alt: optional text <=500; renderer берёт точный alt из Markdown image syntax
}
hero: optional media name; when present it must exist in media
metadata: JSON object <=100 KiB; сохраняется целиком для source_revision/source_sha256/source_date/version_evidence и других provenance-полей, но не исполняется и не выводится anonymous
```

Markdown images reference only `/media/{name}` entries from the same package. External image URLs, H1, raw HTML/comments and product component calls are rejected. GET returns version, SHA256 of exact UTF-8 Markdown, metadata, media summaries with name/hash/provenance/alt and protected media URLs; only the full admin GET may include Markdown, never base64. Media bytes are returned solely by the guarded media route. Validation errors are 422, missing/hidden resources 404, unauthenticated API 401, cross-origin mutation 403, stale version 409.

## Acceptance Criteria

- [ ] Подключён настоящий backend router: list/get/PUT package/PATCH text/POST preview, owner preview/editor/media.
- [ ] Markdown до 250 KiB; до 8 PNG/JPEG/WebP, 1 MiB каждый и 4 MiB суммарно; format/hash/full decode проверяются до записи; ширина и высота не больше 6000 px, суммарно не больше 25 млн пикселей на изображение.
- [ ] Первая запись `expected_version=0`, обновления version-gated; stale 409 и невалидный пакет не меняют active version.
- [ ] Text-only PATCH сохраняет metadata/media и возвращает материал в moderation.
- [ ] Owner responses/errors имеют `private, no-store`, `noindex, nofollow`, `nosniff`; cookie mutations защищены same-origin, Basic API работает программно.
- [ ] Anonymous не получает title/body/media DB-пакета, его нет в sitemap, related, JSON-LD и публичных карточках.
- [ ] Реальный подготовленный материал external_id 10123213 из сохранённых read-only артефактов предыдущего этапа (`C:/Users/Segey/.codex/visualizations/2026/08/30/01a05492-5878-7312-b4ea-15b5fb4daee4/blog-audit-catalog/work/blog-canonical-library/prototype/real-article.md`, соседние `real-article.metadata.json` и `media/01..03.webp`) проходит API round-trip в изолированной SQLite DB и остаётся на модерации; это не карточка A002 из общего аудита. Его дополнительные provenance-поля сохраняются в `metadata`, excerpt остаётся пустым, alt уже находится в Markdown.
- [ ] После 21 последовательной различной редакции остаются ровно последние 20, включая активную; удаляется только самая старая неактивная редакция.
- [ ] Owner-фильтры показывают точные множества: «Публичные» по visibility, «Служебные» по internal, «На модерации» по editorial_status; «Все» объединяет их без дублей. Редактор всегда показывает title, status и version.
- [ ] Прежние blog tests проходят; editor проверен на 360/430/768/1440 и клавиатурный путь.
- [ ] При 409 или network failure textarea сохраняет введённый текст, остаётся dirty и не показывает успех; beforeunload предупреждает о несохранённых изменениях.
- [ ] Fresh code/security/test/layout reviews возвращают `clean`; если после двух разрешённых волн остаётся finding, критерий не пройден и finding явно передаётся владельцу.

## Constraints

Не менять auth engine, Caddy, клиентский ЛК, курс, девять публичных статей и production data. Не делать WYSIWYG, media editor, popup/analytics, массовый импорт и публичный выпуск. Inline base64 media в версии допустимо только как атомарный малый test slice; это не финальное хранилище 130 статей.

## Risks

- **Private leak:** server guard до чтения и negative tests для HTML/API/media/cache/sitemap.
- **Lost update:** optimistic version, local dirty state, без auto-merge/retry.
- **Media abuse:** allowlist formats, size/pixel limits, Pillow verify/load, no SVG/GIF/video.
- **False production claim:** isolated test DB; main/production статусы сообщаются отдельно.

## Accepted Decisions

- Используем общий административный вход, не новый кабинет и не ник как identity.
- Канон — чистый Markdown плюс metadata/media; presentation добавляется adapter-ом.
- Existing ManagedDocumentVersion используется без migration; публичная authority остаётся `content/blog/manifest.json`.
- Сергей явно утвердил реализацию словами «реализуй автономно» после показа конкретного ТЗ.

## Testing

**Unit tests:** package validation/render transformations — это минимальная граница для чистых правил Markdown/media и не требует подменять DB/router.

**Integration tests:** real router + SQLite + DB reopen: create/read/text update/idempotency/stale/invalid/anonymous/CSRF/private headers/public regression, filter sets и retention после 21 редакции. Эта граница нужна для транзакции, version conflict, access control, cache/index headers и повторного чтения.

**E2E tests:** owner editor open → видимые title/status/version → edit → preview → save; переключение четырёх owner-фильтров; 409/network failure, beforeunload, keyboard path. Browser нужен для DOM/fetch/dirty-state, которые API-тест не доказывает. Responsive captures 360/430/768/1440 отдельно доказывают композицию и отсутствие overflow.

## Verification

### Agent Verification

| Step | Expected Result |
|---|---|
| API package round-trip | MD и media hashes совпадают после новой DB-сессии |
| Text patch и stale patch | Новая версия сохраняет media; stale 409 ничего не портит |
| 21 редакция | Хранятся последние 20, active не удалён |
| Owner-фильтры и editor metadata | Состав карточек точен; title/status/version видимы |
| Anonymous requests | Закрытые сведения не выдаются и не индексируются |
| Existing blog suite | Девять Git-backed статей не изменились |
| Browser editor | Нет overflow; preview/save/failure state работают |
