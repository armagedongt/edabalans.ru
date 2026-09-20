---
title: "Блог: Markdown → API → модерация"
document_status: current
module_id: platform.blog
---

# Блог: редактирование и выпуск существующих статей

Контур позволяет править и выпускать без deploy все статьи, зарегистрированные
в `content/blog/manifest.json`. Manifest остаётся владельцем
slug, SEO, рубрики, hero/card, CTA, related и разрешённых media. PostgreSQL
хранит отдельно черновую и опубликованную версии чистого Markdown.

Редакция открывается после обычного входа администратора через пункт «Блог»
или напрямую на `https://edabalans.ru/blog`. Она намеренно находится на домене
`edabalans.ru`: существующая admin-cookie действует там и не может быть общей с
публичным доменом `похудение-это-есть.рф`. Публичный домен не раздаёт редактор и
закрытое API; второй логин не создаётся.

Создание неизвестного slug сейчас запрещено. Подробное ТЗ будущего добавления
статей находится в `docs/plans/BLOG_NEW_ARTICLE_API.md`.

## Жизненный цикл

1. При первом открытии редакции backend идемпотентно создаёт draft из текущего
   Git Markdown каждой manifest-статьи. Из тела извлекается единственная CTA:
   она по-прежнему добавляется surface adapter-ом из manifest.
2. Сергей открывает статью, меняет Markdown и нажимает «Сохранить».
3. Сохранение создаёт новую draft version со статусом «На модерации». Публичная
   страница не меняется.
4. «Предпросмотр» собирает текущий текст в реальном оформлении блога без записи.
5. «Опубликовать» после отдельного подтверждения копирует именно сохранённую
   expected version в `blog-article-published`.
6. Публичный URL читает Markdown из published snapshot; SEO, media, CTA и
   related каждый раз берутся из актуального manifest. До первого выпуска
   сохраняется Git fallback. Следующая черновая правка снова не видна до нового
   выпуска.

## Формат исходника

Для совместимости full PUT JSON хранит `slug`, `title`, `excerpt`, `category`, `visibility`,
`editorial_status`, `cta`, `sources`, `source_id`, `hero`, `media`. Все остальные
поля сохраняются как непрозрачная `metadata`, поэтому evidence, хеши и сведения
о версии источника не теряются.

`visibility` имеет два значения:

- `public` — будущая публичная статья, пока только на модерации;
- `internal` — служебный материал, видимый только администратору.

Оба варианта закрыты авторизацией и `noindex`; `visibility=public` не означает,
что статья уже опубликована.

Full PUT разрешён только для slug, уже существующего в manifest. Изображение в
таком пакете указывается как `![alt](/media/name.webp)`. Сам файл
лежит в папке media и передаётся в том же пакете. API сверяет тип файла,
декодирует изображение полностью и ограничивает количество и размер.
Весь HTTP-пакет ограничен 8 MiB ещё до разбора JSON и проверки полей.
Такой пакет остаётся закрытым preview: текущий public publish принимает только
Markdown с media из manifest. Серверное добавление/замена публичных media входит
в отложенное ТЗ нового registry и blob storage.

## API

Все ответы закрытого контура получают `Cache-Control: private, no-store`,
`X-Robots-Tag: noindex, nofollow` и `X-Content-Type-Options: nosniff`.

| Метод | Маршрут | Назначение |
|---|---|---|
| `GET` | `/admin/api/blog/articles` | Список активных редакций |
| `GET` | `/admin/api/blog/articles/{slug}` | Exact Markdown, metadata, media manifest и история |
| `PUT` | `/admin/api/blog/articles/{slug}` | Создать или целиком заменить пакет |
| `PATCH` | `/admin/api/blog/articles/{slug}/text` | Сохранить только Markdown, не теряя metadata/media |
| `POST` | `/admin/api/blog/articles/{slug}/preview` | Проверить и собрать предпросмотр без сохранения |
| `POST` | `/admin/api/blog/articles/{slug}/publish` | Выпустить сохранённую expected version после `confirm=true` |

`expected_version` обязателен: `0` при создании, текущий номер при изменении.
Устаревшая вкладка получает `409`, а активная версия остаётся прежней.
Одинаковый пакет не создаёт лишнюю версию. Хранятся последние 20 редакций.

Браузерные изменения с cookie допускаются только с точным same-origin `Origin`.
Автоматический клиент использует существующий HTTP Basic. Пароль не передаётся
аргументом командной строки и не сохраняется в Git.

Неизвестный slug получает `404`; маршрут не является create API. Публикация
служебного материала запрещена. API возвращает `editorial_status=published`,
когда активный draft совпадает с публичной версией, иначе `moderation`.

## Команда замены пакета существующей статьи

Собрать пакет и проверить наличие всех файлов без сети (полная проверка формата
выполняется API перед сохранением):

```powershell
python backend/scripts/publish_blog_draft.py `
  --metadata path/to/article.metadata.json `
  --markdown path/to/article.md `
  --media-dir path/to/media `
  --dry-run
```

Для загрузки в разрешённый тестовый контур задаются
`EDABALANS_ADMIN_USER`, `EDABALANS_ADMIN_PASSWORD`, `--api-base` и текущий
`--expected-version`. Секреты остаются только в окружении.

## Текущие ограничения

- редактор правит только Markdown; hero/card, media, SEO, CTA и related остаются
  manifest-backed;
- нет WYSIWYG, автоматического related, popup и blog-аналитики;
- закрытые материалы не попадают в sitemap, публичный каталог или поиск;
- неизвестные slug и кнопка «Новая статья» не поддерживаются.

## Проверка

Интеграционные тесты проверяют seed всех manifest slug, статью с 39 media
без base64-копий, неизвестный slug, точечную правку, конфликт версий, retention,
анонимный отказ, Git fallback и цепочку save → explicit publish → новая draft
правка без утечки в public. Browser test проверяет редактор и выпуск на
360/430/768/1440 и входит в production CI.
