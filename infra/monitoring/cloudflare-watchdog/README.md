# Внешний production-watchdog

Cloudflare Worker раз в минуту проверяет общую готовность платформы и глубокую
готовность Telegram. Incident открывается после трёх последовательных ошибок.
Состояние хранится в одном SQLite-backed Durable Object и сериализует аварийные
действия.

## Поведение

1. Недоступна `/ready`: Worker запрашивает reboot российской VM.
2. `/ready` доступна, `/telegram/ready` недоступна: Worker запрашивает reboot
   европейской VM, затем российской VM при ошибке дольше пяти минут.
3. Через десять минут от первой ошибки Worker вызывает `Campaigns.suspend` для
   явно перечисленных кампаний.
4. Alert, каждое аварийное действие и восстановление отправляются владельцу через
   `sendMessage` существующего Telegram-бота.
5. Реклама никогда не возобновляется автоматически.

При отсутствии `ACTIONS_ENABLED` автоматические действия выключены. Реальное
включение выполняется только в Cloudflare runtime после теста уведомления.

## Runtime-настройки

Secrets:

- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_ALERT_CHAT_ID`;
- `TIMEWEB_API_TOKEN`;
- `TIMEWEB_RU_SERVER_ID`;
- `TIMEWEB_EU_SERVER_ID`;
- `YANDEX_DIRECT_TOKEN` — добавляется после готовности рекламного кабинета;
- `YANDEX_DIRECT_CLIENT_LOGIN` — только для агентского доступа;
- `YANDEX_CAMPAIGN_IDS` — ID через запятую.
- `ACTIONS_ENABLED` — `true` только после alert drill и проверки остальных secrets.
- `DRILL_TOKEN` — случайный secret для изолированного production-drill.

Значения не копируются в Git, документацию или логи. Токен Telegram используется
только для исходящего `sendMessage`; входящие updates продолжает получать
единственный polling-процесс на российском сервере.

Timeweb-токен создаётся с ограниченными правами: только «Облачные серверы —
Управление». Права на базы, S3, DNS, баланс и остальные сервисы не выдаются;
удаление без Telegram-кода не разрешается. API Timeweb ограничивает право уровнем
сервиса, поэтому Worker дополнительно знает только два явных server ID.

## Проверка и публикация

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm check
pnpm deploy
```

Постоянный `workers.dev` URL выключен: Worker вызывается только cron-триггером, поэтому
посторонние запросы не могут израсходовать бесплатную суточную квоту и остановить
мониторинг. При первичной установке `workers_dev` кратковременно включается только на
время authenticated drill и сразу после него выключается повторным production deploy.

После первой публикации нужно проверить активный cron и выполнить authenticated drill:
три запроса `POST /drill/fail`, четвёртый такой же запрос для проверки deduplication,
затем `POST /drill/recover`. Drill использует отдельный Durable Object, реальные
Cloudflare secrets и Telegram `sendMessage`, но принудительно пропускает все recovery
actions. Ожидаются ровно два сообщения: тестовая авария и восстановление. После этого
можно включить `ACTIONS_ENABLED=true`.

Cloudflare Worker выпускается отдельно от серверного deploy командой `pnpm deploy`
из этой папки. После выпуска в журнале операции фиксируются Git SHA и Cloudflare
account/subdomain без secrets. Откат: checkout последнего исправного Git SHA,
`pnpm install --frozen-lockfile`, `pnpm deploy`; Durable Object сохраняет открытый
incident, поэтому откат к несовместимой версии состояния запрещён.

Первый выпуск локального systemd-watchdog требует bootstrap: действующий deployer
ещё не содержит команд установки новых units. После первого server deploy units
вручную копируются из `/opt/edabalans/infra`, запускаются, затем проверяются
`systemctl is-active edabalans-telegram-watchdog.timer` и журнал oneshot. Все
последующие выпуски обновляют и проверяют их штатным deployer.

## Журнал выпуска

- 05.09.2026 — Cloudflare account `253c4e986be90daca60abe0e21ae65f7`,
  workers.dev subdomain `armagedongt`, Git SHA `ae63ee02ec1c71666db626dbde0b9cc8cf0948c9`.
  Cron `* * * * *` активен; authenticated drill дал четыре ожидаемых `503`, затем
  `200` на восстановлении; Cloudflare Observability показал 20 успешных событий и
  0 ошибок. Постоянный workers.dev и preview URL выключены. Timeweb recovery включён;
  Яндекс.Директ получит `YANDEX_CAMPAIGN_IDS` отдельно после подтверждения точного
  списка кампаний из рекламного рабочего потока.
