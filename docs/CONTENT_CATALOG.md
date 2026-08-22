# Каталог авторских материалов

Статус: `current` для кода репозитория, migration ещё не применена в production
Проверено: 22.08.2026
План и полный будущий scope: `plans/CONTENT_CATALOG_SPEC.md`

## Назначение

Модуль хранит авторские публикации из Pikabu, а позже из Telegram и собственного
блога. Первая версия text-first: исходный текст, структурные блоки, метрики, концовка,
CTA, ссылки и метаданные медиа.

Изображения, видео и другие файлы collector **не скачивает**. Для Pikabu в БД
сохраняются исходный URL, тип, позиция и доступный preview URL. Общая таблица допускает
медиа без публичного `source_url`, потому что будущий Telegram-импорт может располагать
только платформенным идентификатором и метаданными файла. Для каждого материала
обязательна каноническая ссылка на оригинальную публикацию.

Комментарии не входят в первую версию и будут добавляться отдельным этапом.

## Компоненты

| Компонент | Назначение |
|---|---|
| `tools/pikabu_collect.py` | локальный браузерный обход профиля и постов без скачивания медиа |
| `backend/app/importers/pikabu_catalog.py` | inspect/dry-run и подтверждённый импорт JSON |
| `backend/app/content_service.py` | нормализация, версии, импорт и чтение каталога |
| `backend/app/content_routes.py` | защищённый read-only admin API |
| `/admin/content` | список материалов и карточка исходника |
| `20260822_0013_content_catalog.py` | схема PostgreSQL |

Browser collector вынесен в отдельные зависимости
`backend/requirements-collector.txt`; production backend не устанавливает Chromium.
Реальная выгрузка должна находиться вне Git-репозитория.

## Таблицы

| Таблица | Назначение |
|---|---|
| `content_sources` | площадка и авторский аккаунт |
| `content_items` | каноническая карточка, original URL, концовка и CTA |
| `content_item_versions` | неизменяемые версии текста и блоков |
| `content_media` | позиция и метаданные изображений/видео; URL обязателен для Pikabu, но может отсутствовать у других источников |
| `content_links` | wrapped и конечные URL, тип и исключение научных источников |
| `content_metric_snapshots` | изменяемые просмотры, рейтинг, сохранения, эмоции и platform-specific `details_json` |
| `content_import_runs` | отчёт каждого импорта и ошибки |

Контентные сущности не связаны с CRM-тегами людей.

## API

Все методы требуют действующую административную сессию:

```text
GET /admin/api/content/summary
GET /admin/api/content/items
GET /admin/api/content/items/{id}
```

## Граница безопасности

- migration не применяется автоматически;
- collector ничего не публикует и не редактирует на Pikabu;
- export JSON и browser profile запрещено создавать внутри Git-репозитория;
- `--apply` требует явный `--backup-confirmed`;
- до production migration выполняются backup и test restore;
- PostgreSQL и collector не публикуются наружу.
