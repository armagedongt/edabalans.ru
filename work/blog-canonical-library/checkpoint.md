# Checkpoint

СТАТУС: test-contour-passed-production-blocked

СДЕЛАНО: реализованы закрытый versioned API, owner-каталог, Markdown-редактор,
preview/media routes, CLI паковки и тестовый реальный пакет. Публичный Git-каталог
не переключён. Документация `platform.blog` обновлена.

ГРАНИЦА: `platform.blog`; новые blog draft service/router/static editor/tests/docs. Auth/Caddy/public Git articles не меняются.

ДАННЫЕ: migration/import/production writes отсутствуют. Реальный материал
«Все знают, никто не делает» загружен штатным CLI в изолированный localhost
контур с отдельной SQLite: exact Markdown, три WebP и provenance. Тестовая БД,
логи и screenshots находятся вне Git.

ПРОВЕРКИ: после синхронизации с актуальным `origin/main` — 612 backend pytest
pass, 3 skip, 6 subtests; 51 профильный blog pytest pass; 134 tools unittest
pass, 8 platform skip. Browser E2E pass на 360/430/768/1440; штатный CLI PUT,
private headers, anonymous denial и отсутствие draft в sitemap проверены.
Findings code/security/test/layout устранены; финальные security и layout review
clean, оставшиеся code/test findings закрыты тестами границ, concurrency,
adapter и безопасного slug.

ПЕРЕД PRODUCTION: infrastructure review подтвердил изоляцию теста и выявил две
границы. Browser E2E пока не включён в обязательный GitHub release gate. Кроме
того, media bytes сейчас повторяются внутри каждой полной JSON-версии; для одного
пилота это допустимо, но до массовой библиотеки примерно из 130 статей нужны
дедупликация изображений и отдельное правило их retention/backup.

КОММИТЫ: `b307d4f`, `3e07157` и merge актуального `origin/main` в feature-ветке
`codex/blog-canonical-editor-20260920`. Ветка отправляется в origin без deploy.

СЛЕДУЮЩИЙ ШАГ: добавить browser release gate и спроектировать дедуплицированное
хранение media; после повторной проверки — отдельная приёмка владельца и только
затем merge в `main`.
Отдельного server staging в проекте нет; push в `main` автоматически ведёт в
production, поэтому test-only проверка выполнена локально и публичный источник
статей не переключён.

MAIN/PRODUCTION: unchanged.
