# Этап вложений — проверка 10.10.2026

Граница: локальные PNG/JPG/WebP, выборочная публикация, неизменяемые серверные
байты и существующая авторизация материалов. Этап HTML→MD и структурный API
ещё не реализованы; курс тренировок исключён решением Сергея.

- Client media + vault: 44 passed, 1 Windows symlink skip (после совместимости
  существующих Git assets проверяется повторно).
- Blog targeted editorial: 7 passed; после добавления stream limit входит в
  объединённую проверку границ.
- Объединённая проверка homepage/recipe/calories/blog границ: 35 passed.
- Полные client media/vault + recipe/homepage/calories: 87 passed, 1 skipped.
- Реальный HTTP блога проверяет ingest → draft → publish → PNG bytes, скрытие до
  публикации, owner preview, прежние metadata, чужую область и поддельный raster.
- Рецепт проверяет closed day, самостоятельное право рецептов и восстановление
  старой редакции с сохранёнными calculator cards и удалением новой фотографии.
- Главная проверяет, что новая фотография меняет исключительно src существующего
  тега. Начальный HTML сохраняет прежний SHA256.
- Локальный status: 223 clean, 8 архивов unsupported, 1 существующий черновик бота
  сохранён. Проверка не публикует его.
- Inventory generate/check: 56 modules, 4912 files, 452 routes, 116 tables.

Пять оставшихся действующих рецептов подключены существующим production API
после совпадения MD hash с calculator source_hash и полного rendered HTML.
Версии: farro/alfredo/pasta 4→5, chicken-cabbage 5→6, yogurt-bark 3→4.
HTML и calculator cards не изменились. В папке обновлены только эти пять файлов
и два ошибочно заблокированных обзорных материала; 225 остальных хешей сохранены.
Доказательства вне Git:
`D:/Codex/evidence/article-style-unification-20261008/recipe-adoption-20261010/`.

Новый программный код пока локальный; клиент не установлен и media API не выпущен.
Свежие code/security/test/docs reviews этого этапа ещё предстоят.
