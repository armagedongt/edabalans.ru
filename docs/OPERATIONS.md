# Production operations

## Развёрнутые компоненты

| Компонент | Назначение | Публичный доступ |
| --- | --- | --- |
| Caddy | HTTPS и маршрутизация | 80/443 |
| FastAPI | API приложений | только через `api.edabalans.ru` |
| PostgreSQL 17 | источник структурированных данных | нет |
| NocoDB 2026.08.0 | человекочитаемый просмотр таблиц | `data.edabalans.ru`, вход обязателен |

Каталог production: `/opt/edabalans`.

Секреты находятся только на сервере в `/opt/edabalans/.env` и
`/root/.config/edabalans/s3.env`. Их нельзя выводить в логи, отправлять в GitHub или
вставлять в документацию.

## Проверки

```bash
cd /opt/edabalans
docker compose ps
curl -fsS https://api.edabalans.ru/health
curl -fsS https://api.edabalans.ru/ready
curl -fsS https://data.edabalans.ru/api/v1/health
curl -fsS https://api.edabalans.ru/bot
ufw status
systemctl status edabalans-backup.timer
```

Ожидается: все четыре контейнера работают, три HTTP-проверки успешны, firewall
разрешает только 22/80/443, backup timer активен.

## Резервные копии

Бакет: `edabalans-postgres-backups-ajessi9majsb7glatojn`.

Ежедневно сохраняются:

- `edabalans` — рабочая база приложений;
- `nocodb_meta` — пользователи и настройки NocoDB.

Ручной запуск:

```bash
/opt/edabalans/infra/scripts/backup-postgres.sh
```

Проверка настоящего восстановления в изолированные временные базы:

```bash
/opt/edabalans/infra/scripts/test-restore-postgres.sh
```

Скрипт не заменяет рабочие базы. Он скачивает последние дампы из S3, проверяет
SHA-256, восстанавливает временные базы, проверяет таблицы и удаляет только временные
базы.

## Контрольные точки безопасности

- SSH по ключу проверен в отдельной сессии; вход по паролю пока не отключён.
- UFW разрешает только 22, 80 и 443.
- PostgreSQL не имеет host-публикации 5432.
- Публичная регистрация NocoDB отключена.
- Fail2ban защищает SSH, unattended-upgrades активен.
- Docker-логи ограничены тремя файлами по 10 МБ.
- На VM включён swap 2 ГБ.

## Следующий этап

Для каждого приложения нужны исходные материалы без немедленного production-cutover:

1. код Apps Script;
2. код Tilda T123;
3. названия листов и заголовки колонок;
4. несколько обезличенных примеров строк;
5. описание ожидаемых запросов и ответов.

После этого создаются миграции PostgreSQL, совместимые FastAPI endpoints и тесты на
фиктивных данных. Реальные персональные данные импортируются только после отдельной
проверки и подтверждения владельца.

### Импорт каноничного снимка Tilda Members Area

Исходный CSV хранится только в закрытом S3 или во временном каталоге сервера. Перед
каждым импортом запускаются штатный backup и тестовое восстановление. Импорт
идемпотентен: повторный запуск с тем же `source` и тем же файлом не создаёт дублей.

```bash
docker compose exec backend python -m app.importers.tilda_members \
  /tmp/members.csv --source tilda_members_YYYYMMDDTHHMMSS
```

После импорта проверяются число аккаунтов, созданных доступов, `needs_review`, две
необновляемые группы, очередь `processing` и карточки Tilda в CRM.

## Автоматическая публикация

Push в ветку `main` запускает `.github/workflows/production.yml`:

1. проверяется Docker Compose;
2. собирается backend;
3. запускаются автоматические тесты;
4. VM видит успешный тест через публичный GitHub API;
5. при успехе создаётся свежий backup обеих PostgreSQL-баз;
6. сервер получает конкретный проверенный Git-коммит;
7. Docker-контейнеры обновляются;
8. проверяются API, PostgreSQL и NocoDB;
9. при ошибке возвращается предыдущая версия кода.

GitHub не получает SSH-ключ или иной доступ к VM. Сервер сам проверяет `main` раз в
две минуты и разворачивает только коммит с успешно завершённой проверкой `Test`.

Если коммит содержит новую миграцию PostgreSQL, автоматическая публикация блокируется.
Такие изменения сначала проверяются отдельно и выпускаются вручную после объяснения
последствий владельцу.

## Тестовый Telegram-бот

Контейнер `telegram-bot` доступен снаружи только через Caddy. Публичны маршруты
`/telegram/webhook`, `/bot` и `/bot-api/*`; PostgreSQL по-прежнему не публикуется.
Админка использует тот же Basic Auth, что CRM.

Проверка webhook без вывода токена:

```bash
docker compose ps telegram-bot
docker compose exec telegram-bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read().decode())"
```
