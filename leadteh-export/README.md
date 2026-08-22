# Локальный экспорт сценариев LeadTeh

Одноразовый read-only экспортёр для бота `245278`. Он сохраняет исходные JSON без
изменений, нормализует граф сценария, не удаляет недостижимые блоки, создаёт SQLite,
отдельные Markdown-тексты и отчёты. Проект не меняет LeadTeh и использует только GET.

## Безопасность

- `.env`, HAR и весь `data/` исключены из Git;
- cookie и CSRF-токен не выводятся в лог;
- raw JSON — канонический архив, парсер его не перезаписывает;
- экспорт не переключает webhook и не удаляет данные;
- запросы идут последовательно с задержкой 1 секунда и jitter 0.2–0.8 секунды;
- 429, 5xx и сетевые ошибки повторяются до 5 раз с exponential backoff;
- ошибка одного сценария записывается в SQLite/лог и не останавливает остальные.

HAR содержит закрытые данные аккаунта и тексты сценариев. Не добавляйте его в Git и
не пересылайте значения заголовков авторизации в чат.

## Установка на Windows

Требуется Python 3.11+.

```powershell
cd leadteh-export
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## Авторизация

Проверка предоставленных HAR показала активную браузерную сессию и заголовок
`X-CSRF-TOKEN`; Bearer token не используется. Экспорт HAR не содержит session cookie,
поэтому для live-запросов локально заполните в `.env`:

```dotenv
LEADTEH_COOKIE=полное значение заголовка Cookie
LEADTEH_CSRF_TOKEN=значение заголовка X-CSRF-TOKEN
```

Значения берутся в DevTools → Network из успешного GET-запроса к
`/api/bots/245278/schemas`. Если удобнее использовать «Copy as cURL», перенесите только
эти два значения и сразу удалите временную команду с секретами.

Безопасно проверить HAR, не печатая значения секретов:

```powershell
python -m src.har C:\path\to\app.leadteh.ru.har
```

## Рекомендуемый порядок

Сначала один реальный сценарий:

```powershell
python -m src.export --scenario 1969994
```

Затем PASS 1 из `config/priority_scenarios.json`:

```powershell
python -m src.export --pass priority
```

После проверки отчётов — оставшиеся сценарии:

```powershell
python -m src.export --pass archive
```

Повторный запуск пропускает сценарии со статусом `parsed`. Принудительная повторная
загрузка:

```powershell
python -m src.export --all --force
```

Пересобрать сводные отчёты без сети:

```powershell
python -m src.report
```

Проверить целостность всех raw/parsed/SQLite/Markdown-файлов:

```powershell
python -m src.verify
```

Офлайн-восстановление ответов из HAR (полезно для проверки парсера без нагрузки на
LeadTeh):

```powershell
python -m src.from_har C:\path\to\first.har C:\path\to\second.har --scenario 1969994
```

## Результаты

```text
data/
  raw/schemas_tree.json
  raw/scenarios/{id}.json
  parsed/scenarios/{id}.json
  parsed/content/{id}/block_{block_id}.md
  parsed/content_index.json
  reports/{id}.md
  reports/summary.md
  logs/export.log
  leadteh_archive.sqlite
```

SQLite содержит таблицы `folders`, `scenarios`, `blocks`, `edges`, `texts`, `links`,
`media`, `tags`, `variables`, `conditions`, `export_runs`. Статусы сценариев:
`pending`, `downloaded`, `parsed`, `error`.

Основной старт определяется сначала по `answer.type=start`, затем по `is_main`, затем
консервативно по корням графа. Недостижимые блоки не считаются мусором и сохраняются
как `detached_component`, `orphan` или `unknown_external_entry`. Все неизвестные поля
остаются в `raw`.

## Тесты

```powershell
python -m pytest -q
```

Реальная офлайн-проверка HAR для `1969994` ожидает 30 блоков — столько же, сколько в
`data.steps`. Перед PASS 2 дополнительно проверьте несколько Markdown-файлов, граф,
6 smart-delay и условия в `data/reports/1969994.md`.
