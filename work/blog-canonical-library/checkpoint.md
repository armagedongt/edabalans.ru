# Checkpoint

СТАТУС: committed-and-reviewed

СДЕЛАНО: реализованы закрытый versioned API, owner-каталог, Markdown-редактор,
preview/media routes, CLI паковки и тестовый реальный пакет. Публичный Git-каталог
не переключён. Документация `platform.blog` обновлена.

ГРАНИЦА: `platform.blog`; новые blog draft service/router/static editor/tests/docs. Auth/Caddy/public Git articles не меняются.

ДАННЫЕ: migration/import/production writes отсутствуют. Реальный материал
«Все знают, никто не делает» проверен в локальной SQLite: exact Markdown, три
WebP и provenance. Тестовая БД вне Git.

ПРОВЕРКИ: 62 targeted pytest pass; browser E2E pass на 360/430/768/1440;
CLI dry-run и реальный localhost PUT pass. Findings code/security/test/layout
устранены; финальные security и layout review clean, оставшиеся code/test
findings закрыты тестами границ, concurrency, adapter и безопасного slug.

КОММИТ: `b307d4f` в feature-ветке
`codex/blog-canonical-editor-20260920`, отправленной в origin без deploy.

СЛЕДУЮЩИЙ ШАГ: отдельное решение о merge и тестовом серверном выпуске; публичный
источник статей этим коммитом не переключается.

MAIN/PRODUCTION: local.
