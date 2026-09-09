# Аварийное восстановление Telegram через европейский Squid

Статус: `current`

Эта инструкция нужна только по прямой команде владельца вернуть прежний маршрут
Telegram, если Cloudflare relay недоступен. Она не является автоматическим failover:
переключение меняет production-конфигурацию и выполняется агентом после такой команды
без повторного выбора архитектуры.

## Зафиксированная резервная граница

- российская production VM: SSH-алиас `edabalans-prod`, IP `201.51.2.210`;
- европейская VM: Timeweb `Brainy Stork`, IP `194.87.222.184`, hostname
  `ams-1-vm-nmm7`, конфигурация 1 CPU / 1 ГБ RAM / 15 ГБ NVMe; внутренний server
  ID не хранится в Git и при необходимости определяется через список серверов API;
- SSH: `root@194.87.222.184` с локальным ключом
  `~/.ssh/edabalans_timeweb`;
- Squid: `/etc/squid/squid.conf`, порт `3128`, разрешены только CONNECT-запросы
  от `201.51.2.210` к `api.telegram.org:443`;
- эталон конфигурации: [`squid.conf`](squid.conf).

Аудит 09.09.2026 подтвердил: на европейской VM нет Docker, базы, приложения,
пользовательских данных или cron-задач проекта. Кроме обычных служб Ubuntu и агента
Timeweb Zabbix там работает только Squid. Каталог `/opt` пуст.

## Быстрое переключение на существующую VM

Выполнять по порядку. Не выводить содержимое `.env`, Telegram token,
`TELEGRAM_GATEWAY_TOKEN` или Cloudflare secrets в терминал и логи.

1. Если Timeweb VM `Brainy Stork` с IP `194.87.222.184` выключена, запустить её
   в панели или через уже авторизованный Timeweb API. При API-вызове сначала
   получить текущий server ID из списка серверов по этому IP, не спрашивая его у
   владельца. Если VM удалена, выполнить раздел
   «Воссоздание удалённой VM» ниже.
2. Проверить Squid:

   ```powershell
   ssh -i "$env:USERPROFILE\.ssh\edabalans_timeweb" -o IdentitiesOnly=yes root@194.87.222.184 "systemctl is-active squid; squid -k parse; ufw status"
   ssh edabalans-prod "curl -fsS --max-time 15 --proxy http://194.87.222.184:3128 https://api.telegram.org/ >/dev/null"
   ```

   Ожидается `active`, успешный parse, правило UFW `3128/tcp ALLOW IN
   201.51.2.210` и успешный HTTPS-запрос с российской VM.
3. До переключения бота сообщить watchdog, что аварийно требуется маршрут
   `proxy`. Код по умолчанию требует `relay`; secret переопределяет это только на
   время аварийного режима:

   ```powershell
   Set-Location infra/monitoring/cloudflare-watchdog
   'proxy' | pnpm exec wrangler secret put TELEGRAM_REQUIRED_ROUTE
   ```

4. На российской VM создать неперезаписываемую закрытую резервную копию трёх
   relay-настроек, изменить только маршрутные ключи и пересоздать только контейнер
   бота. Повторный запуск проверяет существующую копию и не может заменить её
   proxy-настройками:

   ```bash
   ssh edabalans-prod
   python3 - <<'PY'
   import os
   import tempfile
   from pathlib import Path

   def write_atomic(target: Path, content: str) -> None:
       fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
       try:
           os.fchmod(fd, 0o600)
           with os.fdopen(fd, "w") as stream:
               stream.write(content)
               stream.flush()
               os.fsync(stream.fileno())
           os.replace(temporary, target)
       finally:
           if os.path.exists(temporary):
               os.unlink(temporary)

   path = Path("/opt/edabalans/.env")
   backup = Path("/root/edabalans.telegram-relay-route.env")
   updates = {
       "TELEGRAM_PROXY_URL": "http://194.87.222.184:3128",
       "TELEGRAM_API_BASE_URL": "",
       "TELEGRAM_GATEWAY_TOKEN": "",
   }
   lines = path.read_text().splitlines()
   values = {}
   for line in lines:
       if "=" in line and not line.lstrip().startswith("#"):
           key, value = line.split("=", 1)
           values[key] = value
   if backup.exists():
       saved = dict(
           line.split("=", 1)
           for line in backup.read_text().splitlines()
           if "=" in line
       )
       if not saved.get("TELEGRAM_API_BASE_URL") or not saved.get("TELEGRAM_GATEWAY_TOKEN"):
           raise SystemExit("Existing relay route backup is incomplete; refusing to overwrite it")
   else:
       if not values.get("TELEGRAM_API_BASE_URL") or not values.get("TELEGRAM_GATEWAY_TOKEN"):
           raise SystemExit("Current config is not relay mode and no usable relay backup exists")
       fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
       with os.fdopen(fd, "w") as stream:
           for key in ("TELEGRAM_PROXY_URL", "TELEGRAM_API_BASE_URL", "TELEGRAM_GATEWAY_TOKEN"):
               stream.write(f"{key}={values.get(key, '')}\n")
   seen = set()
   result = []
   for line in lines:
       key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
       if key in updates:
           result.append(f"{key}={updates[key]}")
           seen.add(key)
       else:
           result.append(line)
   for key, value in updates.items():
       if key not in seen:
           result.append(f"{key}={value}")
   write_atomic(path, "\n".join(result) + "\n")
   PY
   chmod 600 /opt/edabalans/.env
   cd /opt/edabalans
   docker compose up -d --force-recreate telegram-bot
   exit
   ```

5. Доказать восстановление через реальные production-границы:

   ```powershell
   ssh edabalans-prod "cd /opt/edabalans && docker compose ps telegram-bot"
   curl.exe -fsS https://edabalans.ru/api/health/telegram
   ```

   Ожидается healthy-контейнер, HTTP `200`, `"status":"ready"`, пустой список
   `reasons` и `"telegram_route":"proxy"`. После этого отправить основному боту
   обычное тестовое сообщение и дождаться содержательного ответа. Watchdog должен
   закрыть уже открытый incident только после пяти полных минут и минимум десяти
   последовательных успешных проверок; реклама возобновляется по тем же правилам.

## Возврат с Squid обратно на Cloudflare relay

Сначала убедиться, что relay снова исправен. На российской VM восстановить только
три маршрутных ключа из закрытой копии, не откатывая остальные изменения `.env`,
и пересоздать только `telegram-bot`:

```bash
ssh edabalans-prod
python3 - <<'PY'
import os
import tempfile
from pathlib import Path

def write_atomic(target: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

path = Path("/opt/edabalans/.env")
backup = Path("/root/edabalans.telegram-relay-route.env")
if not backup.exists():
    raise SystemExit("Relay route backup is missing")
saved = dict(
    line.split("=", 1)
    for line in backup.read_text().splitlines()
    if "=" in line
)
if not saved.get("TELEGRAM_API_BASE_URL") or not saved.get("TELEGRAM_GATEWAY_TOKEN"):
    raise SystemExit("Relay route backup is incomplete")
updates = {
    "TELEGRAM_PROXY_URL": "",
    "TELEGRAM_API_BASE_URL": saved["TELEGRAM_API_BASE_URL"],
    "TELEGRAM_GATEWAY_TOKEN": saved["TELEGRAM_GATEWAY_TOKEN"],
}
lines = path.read_text().splitlines()
seen = set()
result = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in updates:
        result.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        result.append(line)
for key, value in updates.items():
    if key not in seen:
        result.append(f"{key}={value}")
write_atomic(path, "\n".join(result) + "\n")
PY
chmod 600 /opt/edabalans/.env
cd /opt/edabalans
docker compose up -d --force-recreate telegram-bot
exit
```

Затем удалить временный override, чтобы watchdog снова использовал маршрут
`relay` по умолчанию:

```powershell
Set-Location infra/monitoring/cloudflare-watchdog
'y' | pnpm exec wrangler secret delete TELEGRAM_REQUIRED_ROUTE
curl.exe -fsS https://edabalans.ru/api/health/telegram
```

Финальная readiness обязана вернуть `"telegram_route":"relay"`. Резервную копию
`/root/edabalans.telegram-relay-route.env` удалить только после доказанного
восстановления relay; файл содержит production secrets и не должен покидать сервер.

## Воссоздание удалённой VM

Если VM `Brainy Stork` удалена, создать в европейской локации Timeweb Ubuntu VM не слабее
1 CPU / 1 ГБ RAM / 15 ГБ диска с публичным IPv4. Новый IP подставить вместо
`194.87.222.184` во всех командах этого runbook. Установить существующий публичный
ключ `edabalans_timeweb`. Затем с рабочей машины войти именно на новую европейскую
VM и только внутри этой SSH-сессии выполнить установку и настройку firewall:

```powershell
ssh -i "$env:USERPROFILE\.ssh\edabalans_timeweb" -o IdentitiesOnly=yes root@<NEW_EU_IP>
```

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y squid ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow from 201.51.2.210 to any port 3128 proto tcp
ufw --force enable
exit
```

С рабочей машины скопировать эталон и включить сервис:

```powershell
scp -i "$env:USERPROFILE\.ssh\edabalans_timeweb" infra/telegram-proxy/squid.conf root@<NEW_EU_IP>:/etc/squid/squid.conf
ssh -i "$env:USERPROFILE\.ssh\edabalans_timeweb" root@<NEW_EU_IP> "squid -k parse && systemctl enable --now squid"
```

После этого продолжить с шага 2 быстрого переключения, используя новый IP. Токены,
базу и файлы бота на европейскую VM не переносить: она остаётся только слепым
CONNECT-прокси.
