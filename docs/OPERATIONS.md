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
