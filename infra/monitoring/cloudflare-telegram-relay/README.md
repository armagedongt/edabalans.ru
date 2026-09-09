# Telegram API relay

Отдельный Cloudflare Worker передаёт HTTPS-запросы production-бота в Telegram API.
Российская VM обращается к нему напрямую и больше не зависит от нестабильного
маршрута до европейской VM.

- `GET /health` — техническая проверка самого relay;
- `POST /telegram/<method>` — закрытая передача Telegram Bot API;
- `RELAY_TOKEN` хранится только в Cloudflare secrets и `/opt/edabalans/.env`;
- bot token передаётся только в закрытом заголовке и удаляется перед ответом;
- Cloudflare observability выключена, чтобы URL и заголовки Telegram-запросов не
  попадали в прикладные логи.
- Worker публикуется под непредсказуемым именем; фактический URL не переносится в
  документацию и хранится только в runtime-конфигурации production.

Публикация:

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm check
pnpm deploy
pnpm exec wrangler secret put RELAY_TOKEN
```

После публикации российская VM получает `TELEGRAM_API_BASE_URL` и
`TELEGRAM_GATEWAY_TOKEN`, а `TELEGRAM_PROXY_URL` очищается. Рабочая готовность
подтверждается только `/api/health/telegram` со значением
`telegram_route=relay`: эта точка означает, что настоящий long polling уже прошёл
через Worker до Telegram и вернулся в бот.

Откат: checkout последнего исправного Git SHA, затем повторить `pnpm install
--frozen-lockfile`, `pnpm test`, `pnpm check`, `pnpm deploy`. Secret сохраняется
Cloudflare; если создаётся новый Worker, `RELAY_TOKEN` нужно записать заново до
переключения production.
