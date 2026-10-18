# Конструктор каналов и атрибуция: исследование кода

Проверено: 18.10.2026. База исследования — `cd69fe1`, ветка
`codex/channel-first-rollout`. Этот файл описывает исходный код и границы
реализации, не подтверждает выпуск. Общий подписной компонент исследуется
и меняется другим потоком; здесь нет его кода или редакционных решений.

## 1. Entry points

- `telegram-bot/service/static/app.js`, `async function links()` — существующий
  экран правил, aliases, тегов, UTM и событий. Вкладки `bot/channel/utm/events`
  сохраняются как архив прежней атрибуции, без удаления обработчиков и данных.
- `telegram-bot/service/app/main.py`, `create_tracking_link(body, admin, session)`
  (`POST /bot-api/tracking-links`) — старый API принимает platform/placement;
  вызывает `_create_link_rule(...)` и возвращает `_link_payload(...)`.
- Тот же файл, `_create_link_rule(session, body, admin, platform='', placement='',
  campaign=None)` — общая запись правила и alias в одной транзакции. Современный
  `POST /bot-api/link-rules` передаёт только name/tags/route, поэтому platform
  становится «Не указана», placement — названием правила.
- Тот же файл, `_link_payload(session, link)` — строит прямой bot `?start=`
  либо сохранённый invite URL. Сейчас не умеет `/<short_name>?startapp=`.
- `backend/app/channel_bridge_routes.py`, `verify_channel_bridge(body, settings)`
  (`POST /apps/channel-bridge/verify`) — проверяет подпись Telegram, распознаёт
  статические `ig/yt/th/pk/dz/vk/tt`; возвращает фиксированный пост `/260` и
  permission mode. Не пишет в CRM/статистику и не открывает серверную сессию.
- Там же, `/c` и `/apps/channel-bridge` — одна HTML-карточка, исходная цель
  жёстко задана `PREVIEW_POST_URL`. Динамическая цель в текущем JS запрещена.
- `backend/app/static/channel-bridge/bridge.js`, `continueToChannel(flag)` —
  вызывает `requestWriteAccess` при нужном режиме и поддержке клиента; callback
  игнорирует результат и всегда открывает канал. `openPost(event)` сохраняет
  проверенный владельцем Android-путь через location.replace и кнопку fallback.
- `backend/app/marketing_routes.py`, `marketing_overview(...)` — существующий
  защищённый отчёт `/admin/api/marketing/overview`, фильтры dates/source/campaign/
  creative/user, даты Europe/Moscow; страница `/admin/marketing` в общей оболочке.

## 2. Data layer и реальные границы schema

- `telegram-bot/service/app/models.py`, `TrackingLink` (`tg_tracking_links`) —
  стабильные id/token, platform/placement/campaign, name, target_kind,
  route_kind/sequence/step, active/status/created_by/archived_at. Нет полей
  channel destination и request_write_access. Нынешние route/step — маршруты
  опубликованного bot sequence, а не ссылки канала.
- Там же, `TrackingLinkAlias` — отдельный уникальный token, status, alias_kind,
  invite URL/chat id. `telegram_invite_url` используется Telegram invite API,
  записывать туда Mini App конфигурацию нельзя.
- Там же, `TrackingSession` — хеш одноразового U-параметра, ссылка+alias,
  raw_query, tags, expiry/consumed_at. Это уже существующий способ сохранить
  yclid/browser_context/journey рекламной посадочной.
- Там же, `TrackingEvent` — link/contact/alias/user/Telegram ID, event_type,
  JSON metadata, unique deduplication_key, processed_at/occurred_at. Новые
  наблюдения Mini App помещаются в существующую таблицу без новой схемы событий.
- `backend/app/models.py`, `TelegramTrackingLink` — сокращённая read model
  той же таблицы для отчётов; сейчас не содержит token и всех обязательных
  полей для полноценной записи. `TelegramTrackingEvent` также не мапит alias_id/
  contact_id/processed_at, присутствующие в физической таблице.
- `telegram-bot/service/app/models.py`, `CrmMessengerAccount` — текущий снимок
  subscription_status/checked_at. Это не история вступлений. Существующие
  `Contact`, `StepDelivery`, message logs и CRM identity остаются владельцами
  контактов, отправок и разрешённых связей с человеком.

### Проверенный вариант без migration

- `backend/app/models.py`, `ManagedDocumentVersion` — существующая общая таблица
  typed/keyed JSON payload, schema_version, version_no, active flag, hash,
  author/date; unique active(type,key), history и optimistic concurrency.
- `backend/app/managed_documents.py`, `active_document(db, type, key)`,
  `ensure_seed_document(...)`, `publish_document(..., expected_version, admin,
  commit=True)` — действующий версионированный механизм. `publish_document`
  поддерживает `commit=False`, поэтому запись catalog row и конфигурации может
  остаться в одной backend-транзакции. `ensure_seed_document` самостоятельно
  коммитит; его нельзя бездумно вызывать посреди такой транзакции.
- `compose.yaml:38,134` — backend и telegram-bot получают один `${DATABASE_URL}`;
  это одна PostgreSQL-база, не раздельные схемы или независимые контуры данных.
- `telegram-bot/service/app/masterclass_dispatch.py:409` — уже есть cross-service
  чтение active `course-structure/masterclass-21` из managed_document_versions
  параметризованным SQL, без копирования владельца конфигурации в bot service.

Можно хранить по одному валидированному документу
`document_type=channel-entry-link`, `document_key=<TrackingLink.id>` с целью
канала и request_write_access. Это расширение существующего механизма
конфигурации, а не вторая система настроек или event store в роли config.
`public-site-content` переиспользовать как type не нужно: его whitelist и
рендеринг принадлежат читательским страницам, не конструктору источников.

Цена этого варианта: нет FK document→link; нужно централизованно валидировать
существование и тип правила, архивирование, orphan protection и конфликты
редакций. Исторические события должны содержать snapshot source/placement/
destination/mode/version, иначе переименование изменит смысл старого отчёта.
Для атомарной записи из backend нужно расширить mapping существующей таблицы
или использовать полный параметризованный INSERT с известными обязательными
полями. Вызвать bot API, затем отдельно записать config — неатомарно.

Если всё-таки добавлять поля в `tg_tracking_links`, нужен настоящий Alembic
migration и предусмотренное подтверждение; без migration нет честного способа
выдать существующие sequence/alias поля за channel config. Существующий
managed-documents вариант позволяет избежать этой границы.

## 3. Similar features и shared utilities

- `telegram-bot/service/app/tracking.py`, `generate_alias_token(session, kind)` —
  B/C + четыре символа из безопасного алфавита, проверка aliases на коллизию.
  Статические Mini App коды и `preview/writepreview` нужно резервировать отдельно;
  новый тип не должен случайно проходить старый start router как прежняя воронка.
- Там же, `resolve_alias(...)`, `active_link(...)`, `resolve_start_payload(...)` —
  старые aliases/U-sessions и точные status checks. U-resolver погашает token;
  обычный Mini App verify с несколькими наблюдениями не должен многократно
  вызывать погашающий resolver.
- `backend/app/account_auth_routes.py`, `messenger_init_user_id(init_data,
  token, max_age_seconds=900)` — HMAC, отсутствие duplicate keys, проверка
  auth_date, положительный цифровой ID. Не создаёт учётку или права кабинета.
- `backend/app/managed_documents.py` — переиспользуемые version/hash/conflict
  механизмы; новый самостоятельный config engine не требуется.
- `telegram-bot/service/app/main.py`, `_upsert_contact(...)` — штатная CRM
  идентификация через `ensure_crm_identity`; write_access_allowed сохраняет
  контакт и возвращается без запуска welcome. Сейчас отдельный permission-event
  не сохраняется.
- `telegram-bot/service/app/telegram.py`, `subscription_status(user_id)` —
  getChatMember с tri-state результатом; restricted учитывает is_member.
  Отсутствие API-прав/ответа нельзя превращать в not_subscribed.

## 4. Integration points и путь данных

### Подтверждённый Mini App вход

1. Сервер проверяет signed initData и start_param существующим verifier.
2. Ищет статический код либо active catalog alias + active typed config.
3. Записывает отдельный вход с Telegram ID и существующим user_id, если такая
   связь уже подтверждена. До изменения CRM фиксирует known-before как наблюдение;
   неизвестный CRM человек не обязательно новый Telegram-пользователь.
4. Выдаёт короткоживущий серверный контекст наблюдения, привязанный к entry ID,
   Telegram ID и конфигурации, для callback/navigation acknowledgements.
   Клиент не присылает произвольный link/user id или целевой URL.
5. JS применяет проверенную цель, сохраняет Android navigation/fallback, отдельно
   сообщает callback true/false/not-supported/unknown и navigation requested.
   Ошибка телеметрии не препятствует переходу. Callback true не равен новому согласию.
6. Telegram service `write_access_allowed` пишет самостоятельное серверное
   событие с update dedup key; не запускает рассылку. Временную связь с входами
   можно показать как наблюдение, но при нескольких входах нельзя выдумывать
   точное соответствие одному диалогу разрешения.

Фиксировать permission observations отдельно: signed initial data, callback,
серверный webhook. Не считать клиентское сообщение доказанным новым разрешением;
не называть false отдельным доказанным отказом, когда платформа не различает
закрытие и отсутствие права. Не хранить исходный initData в event metadata.

### Подписка и bot Start

- `telegram-bot/service/app/main.py` обрабатывает chat_member/join_request,
  но сейчас пишет channel_join только при совпадении invite URL с сохранённым
  alias. Вход через прямой пост Mini App этой веткой не атрибутируется.
- Новый capture должен наблюдать членство нужного канала и Telegram ID также
  без invite, не назначая источник произвольно. Снимок getChatMember подтверждает
  состояние в момент проверки; не восстанавливает точную дату вступления.
- `tracking.py`, `resolve_pending_channel_touch(...)` сейчас ищет только
  pending channel_join/request с link. Mini App вход не должен помечаться
  «подпиской» или «стартом» ради переиспользования этой функции.
- Реальные start_first/repeat/... остаются отдельными событиями. Сначала
  permission, затем Start — допустимая последовательность; совпадение Telegram
  ID связывает их с человеком, но не доказывает причину конкретной покупки.

### Рекламная посадочная и browser journey

- `main.py`, `public_messenger_start_link(...)` (`POST /bot/public/start-link`)
  выдаёт отдельный U-session для button/QR и хранит yclid, UTM, browser_context,
  journey_id, messenger и device. Link_prepared не считается кликом.
- `_record_landing_entry(...)`, `POST /bot/public/start-link/click`, `/q/{payload}`
  фиксируют реальный button/QR этап. Нужна ветка Mini App target в том же
  контракте, а не новая посадочная или потеря yclid за общим pk/yt кодом.
- `backend/app/browser_journey_service.py`, `resolve_browser(...)`,
  `bind_personal(...)`, `record_browser_event(...)` — visitor identity,
  backfill неподписанной browser history по подтверждённой персональной ссылке,
  короткий transfer между разрешёнными origins. Не склеивать по аватарке/имени.
- `backend/app/browser_journey_routes.py` — события пишутся только accepted=true;
  механизм согласия не обходить новым SDK. Вход в Telegram WebView и cookie
  обычного браузера сами по себе не одна browser identity.
- `backend/app/personal_tracking_routes.py` — `/m/{token}` и `/p/{number}/{token}`
  уже пишут подтверждённые персональные клики; далее существующие intensive
  access token и source_context связывают статью/главную/оплату.
- `telegram-bot/service/app/engine.py`, `_record_delivery_event(...)` —
  delivery/step/attempt и dedup. Sent означает API принял, не прочитано.

## 5. Отчёты: что уже есть и что отсутствует

- `backend/app/marketing_service.py`, `marketing_dashboard(...)` — московские
  границы периода, canonical merged users, first known source, bot/course
  chronology, safe limit 100000 и явный флаг truncated. Читатели intensive
  попадают даже без Start в выбранном периоде.
- Текущие строки создаются из confirmed Start или intensive reading; человек
  с одним Mini App входом сейчас не появляется. Текущие link totals считают
  только click/web_click и Start. Нужно добавить входную когорту Mini App.
- Сейчас first_touch берётся из Start history; link metadata читается из
  текущего catalog row. Новые source snapshots должны сохраняться при записи.
- `main.py`, `link_analytics(...)` суммирует unique_starts отдельных правил;
  это не общая уникальность площадки. Новые агрегаты считают distinct identity
  на нужной группе, события — отдельно; неопознанные entry IDs не «люди CRM».
- Минимальный отдельный срез в существующей админке: период + площадка + ссылка,
  entries/repeats/known IDs, permission observations, requested navigation,
  подтверждённые Start/membership/delivery и unknown. Москва для дней, UTC storage.
- Зачёт продаж по источникам не согласован; до него можно дать сырые хронологии
  и отдельно first/last observed touch, не выдумывая attribution window.

## 6. Existing tests

Pytest + FastAPI TestClient + SQLite fixtures; JS bridge проверяется Node VM
в `backend/tests/browser/channel-bridge.test.cjs` с Android/Desktop поведением.

- `backend/tests/test_channel_bridge.py` — signed/forged/expired input, static
  source modes, public fallback, no cookies. Пример:
  `test_entry_code_must_be_covered_by_telegram_signature()`.
- `telegram-bot/service/tests/test_tracking.py` — alias first touch, U/yclid,
  MAX journey, QR, browser context, invited channel touch. Пример:
  `test_prepared_bot_start_carries_browser_context(tmp_path, monkeypatch)`.
- `backend/tests/test_marketing_analytics.py` — Московские дни, merge, firstknown,
  entry→Start, join request ≠ subscription, unknown vs collection missing,
  truncated safety, reading-without-Start, auth.
- `backend/tests/test_browser_journey.py` — binding/consent/backfill/transfer/
  retention. `backend/tests/test_personal_tracking_routes.py` — trusted messenger
  origin and no cookie on unknown personal link.

Для новой границы нужны config validation/version conflict; archive isolation;
старые коды; forged/replay entry; callback result idempotency; динамическая цель
и fallback на реальном bridge JS; new-vs-existing unknown; no-Start entry в
отчёте; distinct на группе; события вне периода; no message sent при capture.

## 7. MAX — факты существующего кода

- `telegram-bot/service/app/max.py`, `MaxClient` — действующий API/webhook,
  общий CRM и tracking catalog. `subscription_status(...)` буквально возвращает
  None; готовой проверки членства MAX в этой реализации нет.
- `backend/app/account_auth_routes.py` уже проверяет MAX initData для входа
  существующей Mini App тем же verifier с MAX token. Это не готовый channel
  redirect adapter и не право отправить сообщение.
- Документ `docs/knowledge-base/modules/max/START_AND_ATTRIBUTION.md` описывает
  bot_started/U-sessions и общий runtime; назначения канала/контактов берутся из
  MAX_CHANNEL_URL/MAX_CONTACT_URL. Перед выпуском канального Mini App нужен
  отдельный проверенный URL/registration и тест открытия конкретного поста.
- Репозиторий не содержит MAX requestWriteAccess-аналога; нельзя показывать
  MAX отказ/согласие как ноль. В первом срезе capabilities явные: unknown/
  unsupported, существующая MAX bot link остаётся работоспособной.

## 8. Constraints, smallest slice и handoff

Владельцы: `messaging.telegram.attribution` — каталог/bridge/events/journey;
`marketing.analytics` — отчёты; `messaging.max` — MAX transport; `platform.content`
— общий managed_documents mechanism. Единый `admin_catalog` в docs/modules.toml
описывает навигацию; нового admin host, users, bot engine или config table нет.

Первый самостоятельный результат, не зависящий от будущих текстов каналов:

1. Existing catalog + typed versioned per-link config, constructor в общей
   маркетинговой админке, stable short code, source/postname, default permission
   true и переключатель false, валидированная цель закреп/пост. Старый links()
   остаётся доступен с архивной подписью, старые rows/handlers не архивируются
   массовым UPDATE и не удаляются.
2. Signed bridge entry/callback/navigation facts в существующей таблице,
   динамический target без потери проверенного мобильного пути. Capture не
   запускает ни Start, ни автоматическое сообщение.
3. Защищённый простой report period/source/link и raw chronology с честной
   unknown-колонкой. Далее подключить snapshots membership и server permission,
   Start/deliveries; не выдавать неполную первую ступень за всю сквозную аналитику.
4. Существующая Direct landing U-session ветка Mini App, сохранение browser/
   yclid контекста; это готовая зависимость для последующего чата Direct/VSL.
5. Только после этих зависимостей передать Direct/VSL контракт и результаты:
   новые event types/metadata, даты начала сбора, личные/browser связи, current
   article URL, список уже подключённых событий и известных gaps. Статью после
   переписывания должен заново разметить её аналитический владелец.

В этом исследовании ничего не отправлено другим чатам и не создано, production
не изменялся, внешние API не вызывались, секреты и персональные данные не читались.
Новых внешних библиотек для этого среза не требуется: FastAPI/Pydantic/SQLAlchemy
и существующий verifier/version-store уже присутствуют.
