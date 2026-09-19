# Review resolutions

- CLI path traversal: имя media теперь проверяется до чтения, resolved parent
  обязан совпасть с media directory; slug проверяется до построения URL;
  добавлены негативные тесты.
- Media summaries: API возвращает защищённый owner URL для каждого файла.
- Resource consumption: mutating blog API проходит admin pre-auth до чтения
  тела; Content-Length и поток ограничены 8 MiB; оба пути проверены.
- Auth coverage: добавлен интеграционный тест настоящего существующего Basic
  guard для source и media, включая anonymous 401/404.
- Media boundaries: проверены count, per-file, aggregate, edge, pixel, format,
  точные верхние границы, полный decode и SHA-integrity.
- Version conflicts: добавлен одновременный запуск двух независимых DB-сессий;
  остаются ровно одна active версия и управляемый `409`.
- Adapter output: preview-тест фиксирует закрытый media URL и typed CTA.
- Editor E2E: исполняются четыре фильтра, клавиатурный focus, preview, save,
  409, network failure и beforeunload; textarea сохраняется.
- Accessibility: textarea получил focus-visible outline, фильтры — aria-pressed.
- Evidence: перед full-page capture все lazy images принудительно прокручиваются
  и декодируются; четыре обязательные ширины пересняты.
