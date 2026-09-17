# Checkpoint — 17.09.2026

## Подготовлено локально

- Создан отдельный worktree `edabalans-cross-messenger-bridge` от свежего
  `origin/main`; основная грязная рабочая папка Сергея не затронута.
- Зафиксирована новая схема: посты Telegram → MAX-канал, а разговор — между
  двумя обычными чатами практики.
- Добавлены будущие таблицы пары, карты сообщений, receipt входящих событий и
  delivery-попыток; миграция `20260917_0042`.
- Добавлены отдельные методы Telegram/MAX для reply, правки и удаления.
- Telegram polling запросит `channel_post`, `edited_channel_post` и
  `edited_message`, не ломая текущие update-типы.

## Проверено

- `python -m compileall telegram-bot/service/app backend/migrations/versions/20260917_0042_cross_messenger_bridge.py`
- `python -m pytest tests/test_cross_messenger_bridge.py tests/test_telegram.py tests/test_max.py -q --basetemp .pytest-bridge`
  — 59 passed.
- По официальной документации MAX подтверждено: обычные групповые чаты принимают
  image/video/audio/file и нативные reply; для канальных комментариев этот путь
  не подходит.

## Следующий технический шаг

Подключить обработчики к Telegram update и отдельному MAX webhook, после чего
проверить реальные payload MAX на тестовом чате. В документации MAX не описан
полный путь скачивания пользовательских входящих вложений обратно в Telegram;
это не повод урезать требование к медиа, а обязательный живой тест сразу после
окончания модерации бота.

## Внешняя пауза

MAX-бот `Ответ из чата` (`@id230409966750_1_bot`) создан и находится на
модерации до 24 часов. До её конца невозможно получить production token,
добавить бота в тестовый чат и провести проверку фактических webhook/media.
