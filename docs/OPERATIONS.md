# Production operations

## Развёрнутые компоненты

| Компонент | Назначение | Публичный доступ |
| --- | --- | --- |
| Caddy | HTTPS и маршрутизация | 80/443 |
| FastAPI | API приложений и публичные документы | `api.edabalans.ru`, приложения через `app.edabalans.ru`, документы через `go.похудение-это-есть.рф/legal` |
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
curl -fsS https://data.edabalans.ru/api/v1/health
curl -fsS https://api.edabalans.ru/bot
curl -fsS https://go.похудение-это-есть.рф/legal
curl -fsS https://go.похудение-это-есть.рф/legal/disclaimer
curl -fsS https://go.похудение-это-есть.рф/legal/privacy
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

Защита выполняется в двух местах. GitHub проверяет текущий push, а серверный
`edabalans-deploy` дополнительно сравнивает весь диапазон между реально установленным
коммитом и целевым. Поэтому следующий commit без migration-файла не может случайно
протащить ещё не выпущенную миграцию. После backup, test restore и проверки миграции
на отдельной PostgreSQL ручной выпуск выполняется только явной командой:

```bash
ALLOW_DATABASE_MIGRATIONS=1 /usr/local/sbin/edabalans-deploy <full-commit-sha>
```

Если такой выпуск упал уже после возможного изменения схемы, скрипт не запускает
старый контейнер, который не знает новую Alembic revision. На сервере остаётся
целевой commit с matching migration files для ручного восстановления; автоматический
downgrade базы не выполняется.

## Тестовый Telegram-бот

Контейнер `telegram-bot` доступен снаружи только через Caddy. Публичны маршруты
`/telegram/webhook`, `/bot` и `/bot-api/*`; PostgreSQL по-прежнему не публикуется.
Админка использует тот же Basic Auth, что CRM.

Проверка webhook без вывода токена:

```bash
docker compose ps telegram-bot
docker compose exec telegram-bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read().decode())"
```

Модуль после покупки Мастер-класса выпущен в безопасном тестовом режиме:

- `POSTPURCHASE_DISPATCH_ENABLED=true` разрешает dispatcher читать outbox;
- `POSTPURCHASE_TEST_ONLY=true` запрещает доставку всем, у кого нет явно
  включённого `masterclass_test_profiles`;
- ускорение конкретного владельца и сброс только его тестового прогресса доступны
  в `/admin/masterclass`;
- выключать `POSTPURCHASE_TEST_ONLY` можно только после сквозного ручного прогона
  всех 21 дней и повторной проверки текстов в Telegram-админке.

### Режим ремонта основного Telegram-бота

Для безопасного подключения чистового username до завершения авторских текстов в
production `.env` используются:

```dotenv
TELEGRAM_MAINTENANCE_MODE=true
TELEGRAM_MAINTENANCE_ALLOWED_USER_IDS=<Telegram ID владельца через запятую>
```

В этом режиме сторонний пользователь сохраняется как contact со статусом
`maintenance_waitlist`, получает `tpl_maintenance_notice` и не может запустить ни
одну цепочку или другую отправку. Разрешённые ID работают с ботом полностью.
Токен бота и список ID не хранятся в Git.

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

Перед публикацией самописных лекций также настроить отправку одноразовых кодов из
российского почтового ящика. В production `.env` задаются `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_SSL` и
`SMTP_STARTTLS`, а также отдельный случайный `APP_AUTH_SECRET`, не совпадающий с
`ADMIN_PASSWORD`. Для Яндекс Почты использовать отдельный пароль приложения. После
перезапуска backend выполнить реальный вход тестовой почтой и проверить, что код
приходит, действует 10 минут, допускает не более пяти попыток, одноразовый, а
повторная отправка ограничена одной минутой.
Секреты в GitHub и документацию не копировать.

После проверки рабочих текстов, production-бота, общей Tilda-страницы предложений
и хотя бы одного связанного тестового контакта записать настоящий URL и отдельно
включить `POSTPURCHASE_DISPATCH_ENABLED=true`. Это операционный переключатель:
изменение не требует новой migration, но требует перезапуска `telegram-bot`.

## Выпуск 21-дневного приложения Мастер-класса

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

Затем пройти тестовым участником минимум такой сценарий: вход по коду из письма,
первый материал, попытка перескочить второй материал, анкета, привязка мессенджера,
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
- новый независимый `APP_AUTH_SECRET` и рабочие SMTP-параметры;
- закрытая копия страницы Tilda с одной вставкой и одним `ST100`;
- проверка входа, последовательности материалов, галочек, таймера и оффера тестовым
  участником;
- оставить `POSTPURCHASE_DISPATCH_ENABLED=false`.

Низкоприоритетные отклонения общей платформы, не блокирующие закрытый тест курса:

- Swagger `/docs` публично доступен; перед широким запуском решить, оставить ли его
  публичным или закрыть на уровне конфигурации/Caddy;
- старые DQS, силовые и метаболизм используют email-only совместимый API; перевод
  на подтверждённую app-session делать отдельными версиями, а не ломать текущие T123;
- лимит попыток passwordless-входа хранится в памяти одного процесса и сбрасывается
  при рестарте; для нескольких backend-реплик его следует перенести в PostgreSQL/Redis;
- health NocoDB сообщает технологию заголовком `X-Powered-By`; это можно убрать в
  Caddy как небольшое инфраструктурное ужесточение.
