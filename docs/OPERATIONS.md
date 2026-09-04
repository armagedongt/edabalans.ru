# Production operations

Статус: `current`

## Развёрнутые компоненты

| Компонент | Назначение | Публичный доступ |
| --- | --- | --- |
| Caddy | HTTPS и маршрутизация | 80/443 |
| FastAPI | API приложений, публичные документы и блог | `api.edabalans.ru`, приложения через `app.edabalans.ru`, документы через `go.похудение-это-есть.рф/legal`, блог через `blog.похудение-это-есть.рф` |
| Telegram-бот | Polling, scheduler, цепочки и админка сообщений | `api.edabalans.ru/bot`, API только после входа администратора |
| PostgreSQL 17 | источник структурированных данных | нет |
| NocoDB 2026.08.0 | человекочитаемый просмотр таблиц | `data.edabalans.ru`, вход обязателен |

Каталог production: `/opt/edabalans`.

Постоянный SSH-алиас на рабочем компьютере владельца: `edabalans-prod`. Он использует
ключ `~/.ssh/edabalans_timeweb`; открытый пароль и приватный ключ в репозиторий не
попадают. Проверка подключения: `ssh edabalans-prod "hostname"`.

Секреты находятся только на сервере в `/opt/edabalans/.env` и
`/root/.config/edabalans/s3.env`. Их нельзя выводить в логи, отправлять в GitHub или
вставлять в документацию.

## Проверки

```bash
cd /opt/edabalans
docker compose ps
curl -fsS https://api.edabalans.ru/health
curl -fsS https://api.edabalans.ru/ready
curl -fsS https://api.edabalans.ru/telegram/ready
curl -fsS https://app.edabalans.ru/apps/dqs.html
curl -fsS https://data.edabalans.ru/api/v1/health
curl -fsS https://api.edabalans.ru/bot
curl -fsS https://go.похудение-это-есть.рф/legal
curl -fsS https://go.похудение-это-есть.рф/legal/disclaimer
curl -fsS https://go.похудение-это-есть.рф/legal/privacy
curl -fsS https://go.похудение-это-есть.рф/legal/consent
curl -fsS https://go.похудение-это-есть.рф/legal/offer
curl -fsS https://app.edabalans.ru/intensive/day-1
curl -fsS https://blog.похудение-это-есть.рф/
ufw status
systemctl status edabalans-backup.timer
```

Ожидается: все пять контейнеров работают, перечисленные HTTP-проверки успешны,
firewall разрешает только 22/80/443, backup timer активен.

После подключения внешний Timeweb Monitoring должен проверять раз в пять минут
три публичные точки:

- `https://api.edabalans.ru/ready` — Caddy, основной backend и PostgreSQL;
- `https://api.edabalans.ru/telegram/ready` — Telegram-сервис, PostgreSQL,
  активность scheduler и свежий успешный long polling по фактическому исходящему маршруту;
- `https://app.edabalans.ru/apps/dqs.html` — публичную доставку критичного DQS-приложения.

Проверка Telegram возвращает `503`, если polling или scheduler выключен, scheduler
завершился ошибкой либо рабочая активность давно не обновлялась. Она покрывает
российский сервер и весь реально используемый путь от него до Telegram API. Сейчас
этот путь прямой: европейский сервер отключён от Telegram-контура и потому не входит
в проверку. Если проверенный proxy будет возвращён в `TELEGRAM_PROXY_URL`, успешный
polling автоматически начнёт подтверждать и его. Локальный `/health` остаётся простой
проверкой процесса для Docker и не заменяет внешний контроль. Остальные веб-приложения используют те же
Caddy, backend и PostgreSQL; отдельный платный монитор для конкретной страницы
нужен, только если её доступность имеет самостоятельную рекламную или договорную
критичность. Проверка DQS подтверждает доставку страницы, а общая `/ready` — backend
и базу; она не имитирует нажатия человека в браузере и не заменяет функциональные
тесты приложения перед выпуском.

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

### Приватная память писателя

Каноническая память автора хранится на рабочем компьютере вне Git. Для защиты от
потери компьютера создаётся отдельный AES-256-GCM архив с внутренним манифестом и
SHA-256 каждого исходного файла. В Object Storage загружаются только `.aes256`,
его `.sha256` и безопасный `.json` без исходных текстов и абсолютных путей.

Локальный ключ находится в
`C:\private\edabalans-content-authoring\secrets\author-memory-backup.key`; вторая
копия находится на VM в
`/root/.config/edabalans/author-memory-backup.key` с правами `600`. Ключ не
загружается в Object Storage и не попадает в Git.

Создание выполняется `tools/backup_author_memory.py create` из bundled Python с
пакетом `cryptography`. В архив включаются только `voice/v1`, каталог
`corrections` и глобальный `sergey-development-workflow`; временный рабочий корпус
целиком не резервируется этим маршрутом. Перед удалением локальной копии выполнить
тестовое восстановление в пустой временный каталог командой
`tools/backup_author_memory.py restore` и сверить итоговый отчёт.

На сервере artifacts хранятся в бакете
`edabalans-postgres-backups-ajessi9majsb7glatojn` под префиксом
`author-memory/`; сервер использует уже защищённые S3 credentials из
`/root/.config/edabalans/s3.env`.

После передачи трёх artifacts в
`/var/backups/edabalans/author-memory/incoming` загрузку и сверку размера выполняет:

```bash
/opt/edabalans/infra/scripts/upload-author-memory-backup.sh
```

Успешная команда обязана вывести `Verified` для зашифрованного архива, checksum и
metadata. Временные серверные copies удаляются только после этой проверки.

## Контрольные точки безопасности

- SSH по ключу проверен в отдельной сессии; вход по паролю пока не отключён.
- UFW разрешает только 22, 80 и 443.
- PostgreSQL не имеет host-публикации 5432.
- Публичная регистрация NocoDB отключена.
- Fail2ban защищает SSH, unattended-upgrades активен.
- Docker-логи ограничены тремя файлами по 10 МБ.
- На VM включён swap 2 ГБ.

## Порядок переноса очередного legacy-приложения

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

После изменения правил ручной проверки сначала запускается отчёт без записи:

```bash
docker compose exec backend python -m app.importers.apply_access_review_policy
```

Перед первым применением обязательны свежий backup и настоящее test restore:

```bash
docker compose exec backend python -m app.importers.apply_access_review_policy \
  --apply --backup-confirmed
```

Команда идемпотентна, не удаляет покупки и доступы, сохраняет `conflict` и меняет
только статусы ручной проверки по последнему снимку Tilda.

### Каталог Pikabu

Collector запускается локально и сохраняет JSON и browser profile только вне Git:

```powershell
pip install -r backend/requirements-collector.txt
playwright install chromium
python tools/pikabu_collect.py `
  --output C:\private\pikabu\catalog.json `
  --browser-profile C:\private\pikabu\browser-profile
```

Collector не скачивает изображения и видео: в JSON остаются только URL. Сначала
обязателен inspect без записи:

```bash
docker compose exec backend python -m app.importers.pikabu_catalog /tmp/catalog.json
```

Перед migration и первым `--apply` выполняются ручной backup и test restore. После
этого владелец отдельно подтверждает импорт:

```bash
docker compose exec backend python -m app.importers.pikabu_catalog \
  /tmp/catalog.json --apply --backup-confirmed
```

Реальный JSON после проверки не коммитится и удаляется из временного каталога.
Повторный запуск с `--refresh` обновляет форматирование, позиции медиа, метрики и
доступные комментарии. В отчёте отдельно сверяются `comments_reported` и
`comments_loaded`; расхождение допустимо только как явно видимый partial.

### Каталог Telegram-канала

Используется штатный JSON-export конкретного публичного канала из Telegram Desktop.
Файл остаётся вне Git. T1 читает тексты, entities, реакции, опросы и метаданные
вложений, но не копирует фото/видео и не принимает export группы обсуждений.

Локальный inspect без подключения к PostgreSQL:

```powershell
$env:PYTHONPATH = "backend"
python -m app.importers.telegram_catalog `
  "C:\private\telegram\result.json" `
  --channel-username Fitness_Talks
```

Перед первым `--apply` выполняются ручной backup и настоящее test restore. Migration
`20260822_0013` выпускается отдельно и не применяется обычным автодеплоем. После
этого владелец подтверждает импорт:

```bash
docker compose exec backend python -m app.importers.telegram_catalog \
  /tmp/telegram-channel/result.json \
  --channel-username Fitness_Talks --apply --backup-confirmed
```

Повторный импорт не создаёт дубли публикаций или версий. Новая версия появляется
только при изменении исходного контента; изменившиеся реакции и голоса создают
отдельный metric snapshot.

Просмотры и реакции, которых нет в Telegram Desktop JSON, собираются из публичной
страницы канала отдельным text-only шагом. Файл и browser profile остаются вне Git:

```powershell
python tools/telegram_public_metrics_collect.py `
  --channel Fitness_Talks `
  --output C:\private\telegram\public-metrics.json `
  --browser-profile C:\private\telegram\public-browser-profile `
  --headless
```

Сначала выполняется dry-run, после подтверждённого backup — импорт:

```bash
docker compose exec backend python -m app.importers.telegram_public_metrics \
  /tmp/telegram-public-metrics.json
docker compose exec backend python -m app.importers.telegram_public_metrics \
  /tmp/telegram-public-metrics.json --apply --backup-confirmed
```

Публичная страница не отдаёт надёжное число репостов и комментариев. Эти значения
не подменяются нулями и остаются пустыми до подключения подтверждённого источника.

### Единый рабочий каталог материалов

Запечатанный локальный снимок передаётся на сервер вне Git. До записи обязательны
fresh backup, test restore и dry-run с контрольными числами. Снимок размещается в
именованном release-каталоге, например
`/srv/edabalans-private/content-catalog/releases/2026-08-29`, с доступом только
root. Штатный backend этот каталог не видит; для импорта запускается одноразовый
контейнер без портов и с read-only bind mount:

```bash
docker compose run --rm --no-deps --user 0 \
  -v /srv/edabalans-private/content-catalog/releases/2026-08-29:/catalog:ro \
  backend python scripts/import_content_authoring_catalog.py --catalog /catalog
```

Первый пакет должен показать 1 138 активных проявлений, 74 семьи, 961 единичный
материал, 70 групп кандидатов и 686 проявлений с медиа-привязкой. Dry-run также
пересчитывает распределение по пяти источникам, включая 18 ответов Pikabu, и
возвращает `snapshot_digest`. Digest обязан совпасть с локальным dry-run. После
применения migration `20260829_0029` импорт запускается так:

```bash
docker compose run --rm --no-deps --user 0 \
  -v /srv/edabalans-private/content-catalog/releases/2026-08-29:/catalog:ro \
  backend python scripts/import_content_authoring_catalog.py --catalog /catalog \
  --apply --backup-confirmed --expected-digest <snapshot_digest>
```

Сразу повторить ту же apply-команду: второй отчёт обязан показать ноль созданных
карточек, редакций, членств и кандидатов. Исходный каталог на сервере после
успешной сверки переводится в read-only; рабочее редактирование выполняется только
через `/admin/content`. Saved Messages, «Готовые посты» и подборки апреля–мая этой
командой не импортируются.

### Единая библиотека и MCP Библиотекаря

Migration `20260829_0030` добавляет только новые таблицы библиотеки: источники,
неизменяемые версии, связи, очередь решений и журнал использования. Она не
переписывает каталог публикаций, курсы, покупки или клиентские данные.

До выпуска обязательны свежий backup, настоящее test restore и проверка migration
на восстановленной базе. В server env задаётся отдельный случайный
`KNOWLEDGE_MCP_TOKEN`; значение не выводится в логи и не хранится в Git.

Полные исходники передаются на сервер вне Git в именованный release-каталог,
например `/srv/edabalans-private/knowledge/releases/2026-08-29`, доступный только
root. Сначала выполняется dry-run:

```bash
docker compose run --rm --no-deps --user 0 \
  -v /srv/edabalans-private/knowledge/releases/2026-08-29:/import:ro \
  backend python scripts/sync_knowledge_library.py /import
```

После сверки количества объектов и digest тот же пакет применяется одной
транзакцией:

```bash
docker compose run --rm --no-deps --user 0 \
  -v /srv/edabalans-private/knowledge/releases/2026-08-29:/import:ro \
  backend python scripts/sync_knowledge_library.py /import \
  --apply --backup-confirmed --expected-digest <digest>
```

Повторный apply обязан сохранить прежнее число текстовых версий. После импорта
проверяются `/admin/library`, поиск и чтение полного источника, `401` у `/mcp/`
без токена и MCP initialize/search/read с токеном.

Локальный Codex получает тот же токен через переменную окружения
`EDABALANS_KNOWLEDGE_TOKEN`; в глобальном `config.toml` указывается только:

```toml
[mcp_servers.edabalans_knowledge]
url = "https://api.edabalans.ru/mcp/"
bearer_token_env_var = "EDABALANS_KNOWLEDGE_TOKEN"
```

Проектные редакционные skills устанавливаются принятыми runtime-копиями:

```powershell
python tools/install_edabalans_writer_skill.py --install
python tools/install_edabalans_librarian_skill.py --install
python tools/install_edabalans_writer_skill.py --check
python tools/install_edabalans_librarian_skill.py --check
```

Обе проверки выполняются одним выпуском, даже если менялся только один skill. Это
не hard links на рабочий checkout: локальная правка соседнего чата не должна
самовольно менять правила новых задач. После первой настройки MCP или изменения
skill нужно открыть новую задачу либо перезапустить Codex.

## Автоматическая публикация

Push в ветку `main` запускает `.github/workflows/production.yml`:

1. classifier определяет migration/startup-data impact и затронутые backend,
   Telegram, Caddy и Compose;
2. проверяется module registry, его тесты и deploy policy;
3. производная карта модулей пересобирается из целевого commit для tests/build;
4. проверяется Docker Compose;
5. собираются и тестируются только затронутые backend и/или Telegram;
6. VM видит успешный тест через публичный GitHub API;
7. сервер получает конкретный проверенный Git-коммит и так же пересобирает карту;
8. пересобираются и перезапускаются только затронутые сервисы; изменение Compose
   остаётся полным инфраструктурным обновлением;
9. проверяются общие health endpoints;
10. при ошибке возвращается предыдущая версия кода тем же выборочным маршрутом.

Обычный выпуск, меняющий только код без стартовой записи постоянных данных, не
создаёт дополнительный backup: для него достаточны ежедневные резервные копии и
автоматический откат к предыдущей версии кода. Свежий backup перед выпуском
сохраняется для migration, импортов, изменений Telegram `seed_defaults()` или его
вызова при старте и других операций, которые могут изменить или удалить постоянные
данные.

Классификацию выполняет один исполняемый источник
`infra/deploy/classify-deploy-impact`; server deploy читает его прямо из целевого
Git-коммита до checkout, а CI
прогоняет на временных Git-историях случаи code-only, backend, документации,
Telegram, Caddy, Compose, migration, `seed.py` и изменения точного вызова
`seed_defaults()`. Документы, которые входят в backend image, считаются backend
impact; чистые правила агента и deploy-control без runtime-зависимости не требуют
пересборки приложения.

GitHub не получает SSH-ключ или иной доступ к VM. Сервер сам проверяет `main` раз в
две минуты и разворачивает только коммит с успешно завершённой проверкой `Test`.
Оба серверных deploy-скрипта явно выполняют GitHub smart-HTTP fetch через
`HTTP/1.1`: на текущей VM Git через HTTP/2 периодически обрывал чтение публичного
репозитория сообщением `expected flush after ref listing`, после чего ошибочно
пытался запросить Username. Это транспортная совместимость, а не GitHub credential;
токен или пароль для чтения публичного `main` не требуется.

Обычный deploy использует уже скачанные на VM базовые Docker-образы и не выполняет
`docker compose build --pull`: небольшая правка кода не должна зависеть от внешнего
лимита Docker Hub. Обновление базовых образов — отдельная операционная точка: перед
таким обновлением на сервере выполняется интерактивный `docker login`, затем
осознанный `docker compose build --pull` и штатные health-checks. Токен Docker Hub
остаётся только в защищённой конфигурации root на VM, не в Git и не в `.env` проекта.
Если нужного базового образа в кэше нет — например, после восстановления VM,
очистки Docker-кэша или смены версии Python, — Docker всё равно должен скачать его.
Это не обычный code-only deploy: сначала восстановить авторизованный доступ Docker Hub
и выполнить явное обновление образов, затем повторить выпуск.

Выборочный deploy не является ослаблением проверок. Compose и module registry
проверяются всегда, затем все опубликованные health endpoints проверяются после
обновления. Пропускаются только build/test/restart сервиса, чей код, image context,
конфигурация и зависимости не изменились.

Если коммит содержит новую миграцию PostgreSQL, автоматическая публикация блокируется.
Такие изменения сначала проверяются отдельно и выпускаются вручную после объяснения
последствий владельцу.

Защита выполняется в двух местах. GitHub проверяет текущий push, а серверный
`edabalans-deploy` дополнительно сравнивает весь диапазон между реально установленным
коммитом и целевым. Поэтому следующий commit без migration-файла не может случайно
протащить ещё не выпущенную миграцию. После backup, test restore и проверки миграции
на отдельной PostgreSQL ручной выпуск выполняется только явной командой:

```bash
ALLOW_DATABASE_MIGRATIONS=1 /usr/local/sbin/edabalans-deploy <full-commit-sha>
```

Перед ручным выпуском migration-коммита проверить jobs именно этого SHA: тесты и
сборка должны завершиться успешно, а единственной ожидаемой причиной красного
итога остаётся `Block automatic database migrations`. Локальный полный тестовый
прогон не заменяет эту проверку CI.

После успешных health-checks deploy автоматически обновляет установленные
`/usr/local/sbin/edabalans-deploy` и `edabalans-deploy-poll` из проверенного коммита.
Для первого выпуска этой схемы старая серверная копия штатно публикует code-only commit,
после чего обе копии устанавливаются один раз вручную из уже проверенного
`/opt/edabalans/infra/deploy/`; дальнейшие выпуски синхронизируют их сами.

Если такой выпуск упал уже после возможного изменения схемы, скрипт не запускает
старый контейнер, который не знает новую Alembic revision. На сервере остаётся
целевой commit с matching migration files для ручного восстановления; автоматический
downgrade базы не выполняется.

## Тестовый Telegram-бот

Контейнер `telegram-bot` доступен снаружи только через Caddy. Публичны маршруты
`/telegram/webhook`, `/bot` и `/bot-api/*`; PostgreSQL по-прежнему не публикуется.
Админка использует ту же подписанную admin-сессию и пароль, что `/admin` и CRM;
повторный вход на `api.edabalans.ru/bot` после общего логина не требуется.

Production сейчас использует прямое исходящее HTTPS-соединение с Telegram API:
`TELEGRAM_PROXY_URL` оставлен пустым. Старый HTTP-прокси 27.08.2026 принимал TCP,
но не пропускал запросы Telegram и вызывал постоянный `ConnectTimeout`. Возвращать
прокси можно только после отдельного `getMe` smoke-check и полного polling-цикла
без ошибок в логах.

Проверки без вывода токена:

```bash
docker compose ps telegram-bot
docker compose exec telegram-bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read().decode())"
curl -fsS https://api.edabalans.ru/telegram/ready
```

Модуль после покупки Мастер-класса выпущен в безопасном тестовом режиме:

- `POSTPURCHASE_DISPATCH_ENABLED=true` разрешает dispatcher читать outbox;
- `POSTPURCHASE_TEST_ONLY=true` запрещает доставку всем, у кого нет явно
  включённого `masterclass_test_profiles`;
- ускорение конкретного владельца и сброс только его тестового прогресса остаются
  служебной операцией тестового контура и не входят в пользовательскую админку;
- выключать `POSTPURCHASE_TEST_ONLY` можно только после сквозного ручного прогона
  всех 20 дней и повторной проверки текстов в Telegram-админке.

### Режим ремонта основного Telegram-бота

Для безопасного подключения чистового username до завершения авторских текстов в
production `.env` используются:

```dotenv
TELEGRAM_MAINTENANCE_MODE=true
TELEGRAM_MAINTENANCE_ALLOWED_USER_IDS=<Telegram ID владельца через запятую>
TELEGRAM_CHANNEL_ID=<числовой ID основного канала>
```

В этом режиме сторонний пользователь сохраняется как contact со статусом
`maintenance_waitlist`, получает `tpl_maintenance_notice` и не может запустить ни
одну цепочку или другую отправку. Разрешённые ID работают с ботом полностью.
Токен бота и список owner ID не хранятся в Git. Числовой ID канала не является
секретом, но фактическое production-значение также хранится в `.env`. При его
наличии новая опубликованная версия Welcome использует реальный `getChatMember`;
ошибка Telegram/API работает fail-open.

Снимать режим можно только после заполнения текстов и сквозного теста. Перед
переключением проверить список `maintenance_waitlist`; после запуска именно он
является аудиторией уведомления «бот снова работает».

## Выпуск модуля после покупки мастер-класса

Migration `20260822_0015` добавляет только новые таблицы и индексы модуля; она не
удаляет и не переписывает клиентские данные. Перед ручным выпуском обязательны
обычный backup и настоящее тестовое восстановление. После выпуска проверить:

```bash
curl -fsS https://api.edabalans.ru/health
curl -fsS https://api.edabalans.ru/ready
docker compose exec backend alembic current
docker compose exec telegram-bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read().decode())"
```

Сначала оставить в `/opt/edabalans/.env`:

```dotenv
POSTPURCHASE_DISPATCH_ENABLED=false
MASTERCLASS_OFFERS_URL=
```

В текущем ЛК не настраивать и не проверять отдельный вход по почтовому коду.
Единственный пользовательский вход выполняет закрытая Tilda Members Area, а
frontend получает email из авторизованного профиля Tilda. SMTP-параметры и
`APP_AUTH_SECRET`, если они остаются в окружении для другого контура, не являются
частью входа в ЛК. Секреты в GitHub и документацию не копировать.

После проверки рабочих текстов, production-бота, общей Tilda-страницы предложений
и хотя бы одного связанного тестового контакта записать настоящий URL и отдельно
включить `POSTPURCHASE_DISPATCH_ENABLED=true`. Это операционный переключатель:
изменение не требует новой migration, но требует перезапуска `telegram-bot`.

## Выпуск 20-дневного приложения Мастер-класса

Migration `20260823_0017` добавляет `masterclass_day_progress` и
`masterclass_step_progress`. Она не меняет оплаты, доступы и ранее сохранённые
события. Перед ручным выпуском обязательны штатный backup и настоящее тестовое
восстановление.

Migration `20260824_0021` добавляет в прогресс дня только IANA-часовой пояс.
Существующие строки получают безопасное значение `Europe/Moscow`; покупки,
доступы и отметки прохождения не пересчитываются. После выпуска следующий день
рассчитывается на 06:00 по часовому поясу, сохранённому при первом открытии дня.

После выпуска проверить:

```bash
curl -fsS https://app.edabalans.ru/embed.js
curl -fsS https://app.edabalans.ru/apps/masterclass-course.html
docker compose exec backend alembic current
```

Затем пройти тестовым участником минимум такой сценарий: вход в закрытую Tilda
Members Area без повторной авторизации внутри приложения, первый материал, попытка
перескочить второй материал, анкета, привязка мессенджера,
экран предложения, открытие задания и сохранение галочек. В базе должны появиться
строки в обеих таблицах прогресса и события в `masterclass_events`.

На единственной странице `Личный кабинет` в Tilda нужен один блок T123 с кодом из
`docs/TILDA_MASTERCLASS_EMBEDS.md` и один штатный блок корзины ST100. Серверный
каталог открывает Мастер-класс внутри этой страницы. Переключать страницу Tilda до
успешного теста на закрытой копии нельзя.

Исходящие события для будущего Telegram-модуля уже сохраняются, но отправка
сообщений этим выпуском не включается. `POSTPURCHASE_DISPATCH_ENABLED` должен
оставаться `false`, пока тексты и исполняемый граф модуля не утверждены отдельно.

## Подготовленный выпуск согласий личного кабинета

Migration `20260824_0022` добавляет версионированную историю подтверждений
дисклеймера и политики обработки данных. Миграция не меняет покупки, права и
прогресс, но после публикации приложения пользователи без двух актуальных
подтверждений не смогут открыть серверные программы.

До обязательного включения нужны утверждённые полные тексты, backup, test restore и
проверка на тестовом аккаунте: две отдельные галочки, повторный запрос без дублей,
открытие каталога после подтверждения и запрет прямого URL до подтверждения.
Предварительные HTML-редакции предназначены для проверки механики, а не для
юридического запуска.

Production-выпуск `20260824_0022` выполнен 24.08.2026 после свежего backup и
изолированного test restore. Gate активен для закрытого теста единственного
пользователя-владельца. Перед добавлением клиентов нужно выпустить новые финальные
версии обоих документов и проверить повторное подтверждение.

## Подготовленный выпуск единого каталога цен

Migration `20260823_0020` добавляет только версионируемый каталог цен и поля
снимка цены в checkout/оплату. Начальная версия создаётся как черновик. Она не
влияет на действующие платежи, пока в production явно установлено:

```dotenv
PRICING_CATALOG_ENABLED=false
```

Перед будущим включением Сергей сначала перепубликует серверные карточки трёх
тарифов и настроит для них одну общую группу Tilda. Затем в `/admin/pricing`
публикуется проверенная версия и выполняются три тестовые оплаты разными email.
Только после проверки ID checkout, суммы, версии и выданных ресурсов допускается
переключить флаг в `true` и перезапустить backend. Старые платежи не мигрируются и
не пересчитываются.

## Контрольный аудит перед выпуском Мастер-класса — 23.08.2026

Фактически снаружи отвечают `api.edabalans.ru/health`, `/ready`, текущий
`app.edabalans.ru/embed.js` и health NocoDB. Новый маршрут
`apps/masterclass-course.html` и API-манифест пока дают `404`: версия этого рабочего
дерева ещё не развёрнута, и вставлять её в боевую Tilda рано.

Перед ручным выпуском migration `20260823_0017` обязательны:

- backup и тестовое восстановление по стандартной процедуре;
- закрытая Tilda Members Area, из профиля которой загрузчик получает email без
  повторного входа;
- закрытая копия страницы Tilda с одной вставкой и одним `ST100`;
- проверка входа, последовательности материалов, галочек, таймера и оффера тестовым
  участником;
- оставить `POSTPURCHASE_DISPATCH_ENABLED=false`.

Низкоприоритетные отклонения общей платформы, не блокирующие закрытый тест курса:

- Swagger `/docs` публично доступен; перед широким запуском решить, оставить ли его
  публичным или закрыть на уровне конфигурации/Caddy;
- приложения внутри текущего ЛК используют email авторизованного профиля Tilda;
  дополнительную app-session или passwordless-вход не добавлять без отдельной
  явно согласованной задачи владельца;
- health NocoDB сообщает технологию заголовком `X-Powered-By`; это можно убрать в
  Caddy как небольшое инфраструктурное ужесточение.
