# Техническое ТЗ модуля 1 «Первичный вход и атрибуция лида»

Статус: `approved_for_implementation`  
Версия: 1.0  
Дата: 22.08.2026  
Источник требований: `LEAD_ENTRY_OWNER_REQUIREMENTS.md`  
Фактическое старое поведение: `../../../TELEGRAM_BOT_CURRENT_LOGIC.md`

## 1. Результат реализации

После реализации система должна предоставлять законченный модуль, который:

1. управляет правилами входящих ссылок и несколькими публичными кодами правила;
2. обслуживает прямые Telegram deep links и `go.похудение-это-есть.рф`;
3. сохраняет web-click, `/start`, первый распознанный источник и связанные теги;
4. идентифицирует/создаёт общего CRM-пользователя и Telegram account;
5. атомарно определяет `is_first_bot_visit`;
6. возвращает исполняющему движку корневой либо явно разрешённый маршрут;
7. не перезапускает welcome знакомому пользователю;
8. предоставляет отдельный административный интерфейс со справкой и аналитикой;
9. подготавливает, но не активирует до финального теста Telegram channel invite;
10. не меняет production Tilda и не переключает `@Fitness_Talks_bot`.

## 2. Граница исполнения

Вход модуля:

- административная команда создания/изменения правила;
- HTTP `GET` на `go.`-ссылку;
- Telegram update `message` с `/start`;
- Telegram update `chat_member` или `chat_join_request`;
- ручная классификация UTM в админке.

Выход обработки `/start`:

```json
{
  "user_id": "uuid",
  "contact_id": "uuid",
  "is_first_bot_visit": true,
  "link_rule_id": "uuid-or-null",
  "public_alias_id": "uuid-or-null",
  "payload_status": "known|unknown|empty|expired_session",
  "assigned_tag_ids": ["uuid"],
  "entry_route": {
    "kind": "root|published_step",
    "sequence_code": "prepurchase_masterclass",
    "step_key": null
  }
}
```

После формирования результата управление возвращается существующему Telegram
движку. Проверка покупки, закрепа, подписки для интенсива и welcome-контент не входят.

## 3. Используемые существующие сущности

Нельзя создавать параллельные аналоги:

| Назначение | Использовать |
|---|---|
| Общий человек | `users` |
| Telegram identity и факт первого сценария | `messenger_accounts`, включая `main_scenario_seen_at` |
| Локальный контакт/чат конкретного бота | `tg_contacts` |
| Общие теги | `tags` |
| Назначения тегов | `user_tags` |
| CRM-история первого распознанного контакта | `attribution_events` |
| Правило ссылки | существующая `tg_tracking_links`, расширенная миграцией |
| Сырые клики/starts/канальные события | существующая `tg_tracking_events`, расширенная миграцией |
| Корневой маршрут | `tg_bot_routes` |
| Защита от повторной обработки update | `tg_update_receipts` |

`tg_contacts.first_source_token` временно поддерживается для обратной совместимости,
но каноническими становятся правило/alias, `attribution_events` и `user_tags`.
`last_source_token` больше не обновляется новой логикой и помечается deprecated;
удаление колонки выносится в отдельную безопасную миграцию после проверки consumers.

## 4. Новые необходимые сущности

Добавляются только структуры, для которых нет существующего эквивалента.

### 4.1. `tg_tracking_link_aliases`

Несколько публичных кодов одного `tg_tracking_links`.

| Поле | Тип/правило |
|---|---|
| `id` | UUID/text PK по текущему стилю Telegram service |
| `tracking_link_id` | FK → `tg_tracking_links`, indexed |
| `token` | уникальный, case-sensitive; legacy UUID либо новый код |
| `alias_kind` | `short` или `legacy` |
| `status` | `active`, `archived`, `disabled` |
| `telegram_invite_url` | nullable; только для `channel_invite` |
| `telegram_chat_id` | nullable |
| `creates_join_request` | bool |
| `created_by` | admin email/identity |
| `created_at`, `archived_at` | timestamptz |

Token после создания неизменяем. Уникальный индекс не позволяет переиспользование.
Архив не удаляет строку и события.

### 4.2. `tg_tracking_link_tags`

Связь правила с существующими CRM-тегами.

| Поле | Тип/правило |
|---|---|
| `tracking_link_id` | FK → `tg_tracking_links` |
| `tag_id` | FK → `tags` |
| `purpose` | `source`, `placement`, `campaign`, `other` — назначение связи, не новый вид CRM-тега |
| `created_at` | timestamptz |

Unique: `(tracking_link_id, tag_id)`. Значение `purpose` нужно только для пояснения
в админке и аналитике; оно не создаёт категорию/копию тега.

### 4.3. `tg_utm_tag_rules`

Точные правила, вручную подтверждённые владельцем.

| Поле | Тип/правило |
|---|---|
| `parameter_name` | нормализованное имя: фактический UTM key |
| `raw_value` | исходное значение для показа |
| `normalized_value` | trim + Unicode normalization + casefold |
| `tag_id` | FK → канонический `tags.id` |
| `status` | `active`, `archived` |
| `created_by`, `created_at`, `updated_at` | аудит |

Unique: `(parameter_name, normalized_value)` среди active. Никаких fuzzy/AI правил.

### 4.4. `tg_tracking_sessions`

Короткоживущая техническая связка динамических UTM с Telegram `/start`.

Она необходима потому, что Telegram deep link принимает один `start` payload и не
переносит произвольный query string после redirect.

| Поле | Тип/правило |
|---|---|
| `id` | UUID/text PK |
| `start_token_hash` | уникальный hash, исходный token в БД не хранить |
| `tracking_link_id`, `alias_id` | FK |
| `raw_query` | JSON с исходными параметрами; без cookies/PII |
| `resolved_tag_ids` | JSON snapshot только подтверждённых tag IDs на момент клика |
| `created_at`, `expires_at`, `consumed_at` | timestamptz |

TTL по умолчанию 7 дней. Token одноразово помечается consumed при `/start`, но
повторная доставка одного Telegram update безопасно возвращает тот же результат за
счёт `tg_update_receipts`. Истёкшая session ведёт в root без тегов и фиксируется как
`expired_session`.

### 4.5. Отдельная таблица «неразобранных UTM» не создаётся

Неразобранный список вычисляется из `tg_tracking_events.metadata_json/raw_query`
путём группировки комбинаций, для которых нет правил. Это соблюдает требование не
плодить сущности и сохраняет оригинальные значения.

## 5. Изменения существующих таблиц

### 5.1. `tg_tracking_links` становится правилом

Добавить:

- `name` — понятное владельцу название;
- `target_kind`: `bot_start`, `channel_invite`;
- `route_kind`: `root`, `published_step`;
- `target_step_key` nullable;
- `status`: `active`, `archived`, `disabled`;
- `created_by`, `archived_at`.

Существующие `platform`, `placement`, `campaign` сохраняются на переходе как legacy
display data, но новый интерфейс не создаёт на них независимую бизнес-логику.
Каноническая связь выполняется через tag IDs. После миграции и проверки consumers
будет отдельное решение об удалении legacy-колонок.

### 5.2. `tg_tracking_events`

Добавить:

- `alias_id` FK;
- `user_id` nullable UUID для прямой связи с CRM после идентификации;
- `telegram_user_id` nullable string для pending channel attribution;
- `deduplication_key` nullable unique/indexed;
- `processed_at` nullable;
- `metadata_json` остаётся оригинальным payload snapshot без секретов.

Допустимые `event_type` первой версии:

```text
web_click
start_first
start_repeat
start_unknown
start_expired_session
channel_join_request
channel_joined
channel_left
channel_attribution_linked
```

## 6. Кодирование и генерация aliases

Новый код строго `B/C + 4` символа из алфавита без `0/O/1/I/L`.

- `B` разрешён только для `bot_start`;
- `C` — только для `channel_invite`;
- генерация использует cryptographic randomness;
- при коллизии выполняется ограниченное число повторов, затем явная ошибка;
- alias можно создать повторно для существующего правила;
- token редактировать нельзя;
- legacy UUID импортируется без преобразования как `alias_kind=legacy`.

Необязательная шестая `V` не хранится как alias. Resolver сначала пытается найти
точный token. Если token имеет ожидаемую длину 6 и заканчивается `V`, он снимает
только последний символ и включает interstitial. Для legacy UUID `V` не применяется.

## 7. HTTP redirect

### 7.1. Новый публичный route

```text
GET https://go.похудение-это-есть.рф/{token}[?utm_*]
```

Caddy обслуживает отдельный `GO_DOMAIN` и reverse proxy в Telegram service. Backend
route внутри сервиса не конфликтует с `/r/{token}`. Старый `/r/` сохраняется для
совместимости.

### 7.2. Bot link без UTM

1. разрешить alias и active rule;
2. записать `web_click`;
3. если без `V` — 307 в `https://t.me/<configured_username>?start=<base_token>`;
4. если с `V` — HTML interstitial с кнопкой на тот же deep link;
5. неизвестный/disabled token — нейтральная 404 без раскрытия внутренних данных.

### 7.3. Bot link с UTM

1. сохранить оригинальный query в `web_click`;
2. применить только точные active `tg_utm_tag_rules`;
3. создать `tg_tracking_sessions` с новым непрозрачным start token;
4. перенаправить в `t.me?...start=<session_token>`;
5. неизвестные UTM остаются raw и не создают теги;
6. `/start` разрешает session обратно в rule/alias/подтверждённые tag IDs.

### 7.4. Channel invite

Active `C...` перенаправляет в сохранённый `telegram_invite_url`. До создания live
invite админка показывает состояние `Ожидает подключения канала`; публичный redirect
не должен вести на пустое назначение.

Динамические UTM для channel invite в первой версии не создают динамические invites.
Для отдельной канальной кампании владелец создаёт отдельное правило/alias.

### 7.5. Interstitial

Минимальная адаптивная страница:

- название Telegram;
- пояснение проверить VPN, если Telegram не открывается;
- основная кнопка `Открыть Telegram`;
- ссылка без автоматических внешних проверок;
- никаких сторонних скриптов, trackers и cookies;
- noindex;
- одинаковая атрибуция с вариантом без `V`.

## 8. Обработка `/start`

Вся обработка одного update выполняется в одной транзакции с блокировкой/атомарным
условным обновлением `messenger_accounts.main_scenario_seen_at`.

### 8.1. Порядок

1. проверить `tg_update_receipts`;
2. найти/create `tg_contacts`;
3. найти/create `users` и `messenger_accounts` по `(telegram, platform_user_id)`;
4. разобрать payload как alias, tracking session либо unknown;
5. атомарно определить первое посещение по `main_scenario_seen_at IS NULL`;
6. если первое и payload распознан:
   - создать один CRM `attribution_events`;
   - разрешить merged tags в конечный canonical `tag_id`;
   - назначить `user_tags` идемпотентно с source `telegram_first_touch`;
   - создать `start_first`;
7. если первое без распознанного payload — зафиксировать first visit, но не источник;
8. если повторное — `start_repeat`, без новых attribution tags;
9. неизвестный payload — дополнительный `start_unknown`, затем root;
10. выбрать root либо валидированное исключение;
11. вернуть структурированный результат движку;
12. существующая логика не должна создавать второй `SequenceRun` знакомому.

Если до первого `/start` существует подтверждённое pending-событие вступления по
нашей channel invite, источником первого контакта считается более раннее канальное
событие. Теги bot-start ссылки в таком случае не добавляются в первой версии, но
сам start и использованный alias остаются в технической статистике. Если pending-
события нет, используется распознанная ссылка текущего `/start`.

### 8.2. Мигрированные пользователи

`main_scenario_seen_at`, уже заполненный из исторического тега первого посещения,
означает знакомого пользователя. Наличие строки `tg_contacts` само по себе не должно
перезаписывать этот факт.

### 8.3. Теги

- назначаются только на первом распознанном контакте;
- existing/merged tag разрешается в конечный canonical ID;
- unique `(user_id, tag_id)` исключает дубль;
- новый Tag никогда не создаётся из `/start`, UTM или названия ссылки;
- изменение текста Tag не требует изменения rule relation;
- merge обязан перевести relation на target ID либо resolver следует merge chain.

## 9. Явные исключения маршрута

По умолчанию все rules используют root `tg_bot_routes`.

`published_step` разрешается только если:

- sequence/version существует;
- версия `published`;
- step существует и enabled;
- rule active;
- конфигурация прошла валидатор.

При любой ошибке fail-safe: root route, диагностическое событие, без 500 пользователю.
Проверки покупки и бизнес-доступа к шагу будут добавлены следующим модулем; до этого
админка помечает исключения как расширенный режим.

## 10. Telegram channel attribution

### 10.1. Клиент Telegram

Добавить методы:

- `getChat`;
- `createChatInviteLink`;
- `revokeChatInviteLink`;
- при необходимости `approveChatJoinRequest`.

Polling `allowed_updates` расширить `chat_member` и `chat_join_request`. Unknown
update не ломает loop. `tg_update_receipts.update_type` хранит новый тип.

### 10.2. События

По `invite_link.invite_link` найти alias. Сохранить Telegram user ID и событие. Если
контакт уже существует — связать сразу. Если нет — pending остаётся в событии и
связывается при будущем `/start`.

В первой версии channel attribution назначает first-touch tags только если у
пользователя ещё нет `main_scenario_seen_at`/первого распознанного источника согласно
утверждённой политике. Повторное вступление не меняет первый источник.

Реальный Bot API вызов и вступление выполняются только на финальном ручном тесте.
До этого используются mock HTTP tests и disabled live controls.

## 11. UTM admin workflow

### 11.1. Parser

Администратор вставляет URL. Сервер возвращает:

```json
{
  "url": "original",
  "parameters": [
    {
      "name": "utm_source",
      "raw_value": "pikabu",
      "normalized_value": "pikabu",
      "matched_rule": null,
      "suggested_existing_tags": []
    }
  ]
}
```

Suggestions — обычный поиск по `tags.name` и aliases, не semantic/AI.

### 11.2. Save

Каждая выбранная строка сохраняет exact rule → existing `tag_id`. Новый тег можно
создать только отдельным endpoint/action с явным подтверждением; используется общий
CRM tag service, не копия внутри Telegram.

### 11.3. Неразобранные

Группировка по нормализованному набору UTM. Поля UI:

- исходные пары;
- пример URL;
- count;
- first_seen_at/last_seen_at;
- какие exact rules уже известны;
- какие значения требуют ручного выбора.

### 11.4. Применение к прошлому

Preview endpoint возвращает число событий и изменения. Apply endpoint требует
явного подтверждения, идемпотентно проставляет interpretation/tag snapshot и не
меняет raw query. Автоматического пересчёта при save нет.

## 12. Административное приложение

### 12.1. Навигация

Отдельный пункт левого меню: `Ссылки и источники`.

Вкладки:

1. `Ссылки на бот`;
2. `Ссылки на канал`;
3. `Legacy LeadTeh`;
4. `Неразобранные UTM`;
5. `Теги и правила UTM`;
6. `Аналитика`.

### 12.2. Каталог

Колонки/карточки:

- название правила;
- тип;
- теги с актуальными именами из CRM;
- root/exception;
- основной active alias;
- число aliases;
- created/last activity;
- clicks, starts, unique starts, conversion;
- status.

Сортировки: новая/старая дата, активность, clicks, starts. Фильтры: type, status,
tag, legacy, route. Поиск по name/token/tag.

### 12.3. Редактор rule

- name;
- target kind;
- поиск и выбор existing tags;
- явная кнопка `Создать новый тег`;
- route root/exception;
- alias list;
- создать новый alias;
- copy direct `t.me`;
- copy `go.`;
- copy `go.` + `V`;
- archive/disable;
- preview фактической расшифровки.

### 12.4. Alias detail

Показывает token, kind, dates/status, три формы копирования где применимо, clicks,
starts, unique users и event table. Общая карточка rule агрегирует aliases.

### 12.5. Подсказки

У каждой сложной настройки есть короткое пояснение. Обязательные темы:

- rule против alias;
- root против exception;
- `B`, `C`, `V`;
- неизвестный payload;
- first-touch policy;
- existing tag first;
- UTM exact matching;
- legacy archive/no reuse;
- channel test pending.

При изменении канона UI-help обновляется в том же commit. Независимая трактовка в UI
не допускается.

## 13. API первой версии

Имена могут быть адаптированы к существующему `/bot-api`, но контракт должен
покрывать:

```text
GET    /bot-api/link-rules
POST   /bot-api/link-rules
GET    /bot-api/link-rules/{id}
PATCH  /bot-api/link-rules/{id}
POST   /bot-api/link-rules/{id}/aliases
PATCH  /bot-api/link-aliases/{id}/status
POST   /bot-api/link-rules/resolve-preview

POST   /bot-api/utm/parse
GET    /bot-api/utm/unresolved
POST   /bot-api/utm/rules
POST   /bot-api/utm/apply-preview
POST   /bot-api/utm/apply

GET    /bot-api/tags/search
POST   /bot-api/tags                 # явное действие, общий CRM service

POST   /bot-api/channel-invites
POST   /bot-api/channel-invites/{alias_id}/revoke

GET    /bot-api/link-analytics
GET    /bot-api/link-rules/{id}/events

GET    /go/{token}                   # внутренний route за GO_DOMAIN
```

Все admin endpoints защищены существующей admin session. Mutations возвращают
понятные 4xx, пишут admin identity и не принимают произвольный target URL вне
allow-list.

## 14. Безопасность и приватность

- bot token, invite URL и секреты не пишутся в Git;
- токен бота не попадает в access/error logs;
- публичный redirect не принимает open redirect target;
- Telegram username берётся из bot instance/config, а не из query;
- HTML interstitial экранирует данные и не содержит сторонних scripts;
- raw UTM ограничивается по длине и числу параметров;
- неизвестные payload не отражаются пользователю без escaping;
- IP/User-Agent в первую версию не сохраняются;
- Tilda cookies/browser ID не включаются;
- destructive delete для links/aliases отсутствует;
- channel controls disabled до конфигурации chat/permissions.

## 15. Миграция текущих данных

1. Создать новые таблицы/колонки nullable или с безопасными defaults.
2. Для каждой существующей `tg_tracking_links` создать rule и alias из текущего
   `token` без изменения опубликованного URL.
3. Перенести existing `tg_tracking_events` на alias по link relation.
4. Создать/связать только существующие канонические tags; не генерировать новые из
   platform/placement/campaign автоматически.
5. Добавить три известных legacy UUID идемпотентным seed/import:
   - `c5a79797-d6c6-4a36-8551-b07443e990a7` → tag `Пикабу`;
   - `120385af-6025-49f9-b586-d01f4ca4d36b` → `Пост - Не с похудения`;
   - `b1514e43-2459-456f-949b-5cc25e87bb10` → `Пост - Скорость похудения`.
6. Если tag отсутствует или ambiguous — mapping остаётся review, migration не
   создаёт новый tag и не падает целиком.
7. Старый `/bot-api/tracking-links` либо адаптируется совместимо, либо получает
   documented transition endpoint; текущая админка переключается атомарно.

## 16. Caddy и окружение

Добавить переменную:

```text
GO_DOMAIN=go.похудение-это-есть.рф
```

Caddy получает отдельный site block с HTTPS и reverse proxy только на публичные
redirect/interstitial routes Telegram service. Admin/API через `go.` не публиковать.
Наружу по-прежнему только 80/443; PostgreSQL закрыт.

DNS уже указывает `go.похудение-это-есть.рф` на `201.51.2.210`.

## 17. Автоматические тесты

### 17.1. Unit/service

- генератор `B/C + 4`, исключённые символы и collision retry;
- строгий parser `V`;
- alias never reused;
- active/archive/disabled resolution;
- UTM exact normalization/matching без fuzzy;
- unresolved grouping;
- apply preview/apply idempotency;
- merged tag resolves to canonical ID;
- first start assigns once;
- repeat start never assigns new source tags;
- unknown payload → root;
- expired tracking session → root;
- route exception validation/fallback;
- event deduplication;
- aggregate rule stats = aliases, alias stats separate.

### 17.2. API/UI

- auth required;
- create/edit/archive rule;
- create second alias;
- legacy import;
- tag search/create explicit;
- UTM parse/manual rule;
- filters/sorting;
- no XSS from names/UTM;
- responsive admin and help text presence;
- JS syntax check.

### 17.3. Telegram mocked

- `/start` empty/known/unknown/session/repeat;
- duplicate update;
- chat_member/join_request with known/unknown invite;
- pending join linked on later start;
- Bot API create/revoke payload;
- polling allowed_updates.

### 17.4. Migration

- fresh database to head;
- current production revision to head on separate PostgreSQL;
- old links/events preserved;
- downgrade only if non-destructive and tested; production rollback primarily via
  backup + previous containers.

## 18. Тестовый deploy и ручная приёмка

До deploy:

- проверить актуальный backup и restore instructions;
- не импортировать персональные выгрузки;
- не менять main bot token;
- проверить diff Caddy/compose/env example;
- автоматические tests green.

Deploy:

- применить migration;
- обновить Telegram service/Caddy;
- проверить `/health`, admin auth, HTTPS `go.`;
- создать test rule и aliases;
- проверить redirect, `V`, `/start` тестового бота;
- показать владельцу UI.

Только после первых UI-правок провести live invite test. Если test bot не добавлен
в администраторы канала, этот единственный пункт может быть выполнен при переносе на
основного бота и не блокирует готовность остального модуля.

## 19. Критерии готовности

Модуль готов к показу, когда:

- требования и ТЗ находятся в knowledge base;
- schema/API/files описаны фактическими именами;
- миграция прошла на отдельной PostgreSQL;
- все автоматические tests green;
- `go.` имеет валидный HTTPS;
- админ создаёт rule, выбирает existing tags и получает aliases;
- legacy UUID разрешаются без изменения URL;
- первый тестовый `/start` назначает только выбранные existing tags;
- повторный `/start` не перезапускает цепочку и не меняет attribution;
- unknown token безопасно ведёт в root;
- UTM не создаёт tag автоматически;
- статистика агрегируется rule → aliases;
- production Tilda и `@Fitness_Talks_bot` не изменены;
- база знаний обновлена с `planned` на фактический `current` только после deploy.

## 20. Условия остановки

Если одна проблема не решена двумя точечными попытками, требуется неизвестный секрет,
внешний доступ или ручное действие владельца, работа останавливается с коротким
отчётом. Нельзя повторять одинаковые проверки, перечитывать весь репозиторий или
расширять scope на welcome/Tilda/production bot.
