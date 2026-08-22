# Telegram-модуль edabalans.ru

Изолированный Telegram-сервис и его раздел в общей админке. Он использует общую
PostgreSQL, связывает Telegram-контакт с `users.id` и проверяет покупки в CRM,
но его код и таблицы имеют собственный префикс `tg_`.

Сейчас здесь есть:

- проектная схема PostgreSQL в `schema/postgresql.sql`;
- локальный импорт архивных сообщений LeadTeh в SQLite;
- просмотр библиотеки сообщений и черновика цепочки;
- контракт будущего соединения с CRM Core;
- тесты ключевых правил импорта;
- реальный Telegram webhook и идемпотентная обработка update;
- исполняемый движок MESSAGE/DELAY/CONDITION/DB_READ/DB_WRITE/GOTO/STOP;
- 30-постовый шаблон до покупки и отключённая ветка после покупки;
- персональный ускоренный режим, ручные сообщения, ссылки и разовые рассылки;
- специализированная админка `/bot`.

Реальная выгрузка LeadTeh и построенная SQLite-база находятся только локально в
`runtime/` и не попадают в Git.

## Быстрый запуск

Из корня репозитория:

```powershell
.\leadteh-export\.venv\Scripts\python.exe telegram-bot\prototype\import_legacy.py
.\leadteh-export\.venv\Scripts\python.exe telegram-bot\prototype\server.py
```

После запуска открыть `http://127.0.0.1:8765`.

## Что считается готовым на этом этапе

- архив LeadTeh импортируется без изменения исходников;
- текст, эмодзи, ссылки и базовая Telegram-разметка сохраняются;
- вместо медиа показывается понятная заглушка;
- рабочий пост можно создать только как копию архивного;
- цепочка отображается вертикально: сообщение → задержка → условие;
- архитектура не привязана навсегда к Telegram и допускает MAX через адаптер;
- граница с общей CRM реализована через `users.id`, `messenger_accounts` и `payments`.

## Запуск сервиса локально

```powershell
.\leadteh-export\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir telegram-bot/service --port 8001
```

Админка: `http://127.0.0.1:8001/bot`. Токен хранится только в
`telegram-bot/.env`; файл исключён из Git.

## Production

1. Сделать и проверить backup PostgreSQL.
2. Применить Alembic-миграцию `20260822_0006`.
3. Заполнить три `TELEGRAM_*` переменные в серверном `.env`.
4. Запустить контейнер `telegram-bot` и проверить `/health`.
5. Установить webhook на `https://api.edabalans.ru/telegram/webhook` с secret token.

Основной LeadTeh-бот этим контуром не переключается. Подключён только
`@TetrisgfgfgfBot`.
