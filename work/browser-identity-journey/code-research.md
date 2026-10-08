# Browser identity journey — code research

Исследовано: 08.10.2026. База `HEAD` и `origin/main`: `bdf55b8cf3c99d25dc71015301b478b42ac7496c`. Исходный код не изменялся.

Контекст: анонимный путь рекламы/канала → бот → персональная ссылка → интенсив/главная/checkout; связать историю браузера с CRM-контактом, показывать мессенджер в уведомлениях до отдельной привязки ЛК, добавить уведомление о незавершённом счёте через 30 минут. Пользователь принимает погрешность пересланных персональных ссылок для CRM. Это не разрешение авторизации, выдачи доступа или переноса прав по browser identity.

## 1. Entry points

- `telegram-bot/service/app/main.py`: `public_messenger_start_link(body, request, response, session)` на `POST /bot/public/start-link` готовит Telegram/MAX deep link. Создаёт `TrackingSession` и `link_prepared`; `journey_id` равен UUID сессии. Отдельный `POST /bot/public/start-link/click` фиксирует кнопку, `GET /q/{payload}` — QR. До bot start у событий нет CRM user.
- `telegram-bot/service/app/tracking.py`: `ensure_crm_identity(session, contact, telegram)` уже создаёт канонический CRM user и messenger account при входе в бота. `assign_first_touch(..., journey_context=None, mark_scenario_seen=True)` записывает start-событие и рекламные UTM/tags; персональный user известен до кабинета.
- `telegram-bot/service/app/max.py`: `_ensure_identity(session, user)` и `_assign_first_touch(...)` реализуют эквивалентный MAX-путь. MAX также использует общий resolver `resolve_start_payload` и общие tracking events.
- `backend/app/app_routes.py`: `intensive_onepage(request, db, settings)` принимает `i`/`token`, проверяет `consume_access_token`, фиксирует атрибуцию, устанавливает персональную intensive session, очищает код редиректом 303. Также `intensive_menu`, `intensive_entry`, `intensive_state`, `POST /api/intensive/events` обслуживают существующий интенсив.
- `backend/app/personal_tracking_routes.py`: `personal_masterclass_link(token, request, db, settings)` на `/m/{token}` проверяет персональный код и перенаправляет на configured homepage с подписанным `source_context`. `/p/{post_number}/{token}` фиксирует персональный переход в Telegram-публикацию. Оба вызывают reader recognition.
- `backend/app/static/homepage.js`: `restoreSourceContext()` считывает query `source_context`, сохраняет в sessionStorage `edabalans_checkout_source_v1`, очищает URL, выставляет `window.EdabalansCheckoutSourceContext`. Tilda-shell загружает серверную release-candidate HTML.
- `backend/app/static/homepage-preview/release-candidate.html`: встроенный checkout script подхватывает `EdabalansCheckoutSourceContext` или query и отправляет `source_context` вместе с ценовым кодом/email. Это actual release artifact, а не все historical versions.
- `backend/app/robokassa_routes.py`: checkout model уже содержит `source_context: str | None` с max_length 160. JSON и form routes передают контекст в `create_site_checkout`.
- `backend/app/robokassa_subscription_service.py`: `check_one_expired_direct_payment(settings)` проверяет expired invoice по OpStateExt; `check_one_pending_charge(settings)` обслуживает recurring-child invoice отдельно.
- `backend/app/owner_payment_notification_service.py`: `_message_for_payment(...)` строит HTML owner alert; `enqueue_owner_payment_notification(...)` и worker доставляют через существующий technical bot.

## 2. Data layer

- `backend/app/models.py`: `TelegramTrackingEvent` — backend read model таблицы `tg_tracking_events`: string UUID id; nullable tracking_link_id, user_id, telegram_user_id; event_type; JSON metadata_json; unique nullable deduplication_key; occurred_at. Анонимные события допустимы без создания пользователя.
- `telegram-bot/service/app/models.py`: полный `TrackingEvent` той же таблицы дополнительно содержит nullable `contact_id`, `alias_id`, `processed_at`. Backend model этих колонок сейчас не объявляет; запись остальных колонок возможна при их NULL. Перед расширением модели необходимо учитывать FK target metadata, отсутствующие в backend.
- `TrackingSession` хранит hashed U-start token, tracking_link_id, alias_id, raw_query, resolved_tag_ids, expires_at, consumed_at. `create_tracking_session` выдаёт срок семь дней; `resolve_start_payload` блокирует строку и потребляет её один раз.
- `MessengerAccount`/`CrmMessengerAccount` — одна таблица messenger_accounts: platform + platform_user_id уникальны; user_id, username, first_name, linked_at, source, deliverability/preference, subscription observations. Не требуется новая CRM identity для каждого browser.
- `AttributionEvent` требует non-null user_id; он не подходит для первичного anonymous storage. `tg_tracking_events` допускает такой этап.
- `MessengerLinkToken` с purpose `intensive_access` уже связан с user_id/platform; plaintext opaque code проверяется через SHA256. Используется также источник checkout, не платные права.
- `Payment.raw_payload` уже хранит trusted_source_snapshot, account_purchase, purchase_place и status-check retry metadata. `Payment.user_id` для публичного счёта до оплаты остаётся NULL; buyer далее разрешается по email.
- `OfferCheckout` хранит payment_id, checkout_kind, expires_at, status; публичный счёт действует два часа. `OwnerPaymentNotification` имеет kind, deduplication/delivery/retry state; нет необходимости отдельного Telegram delivery engine для нового уведомления.

## 3. Similar features

- `backend/app/blog_reader_context.py`: `recognize_reader(db, request, response, secret, token)` ставит encrypted `edabalans_reader` HttpOnly/Secure/Lax cookie на 30 дней. `reader_user` проверяет purpose, срок token и active user; модуль явно не account credential. Cookie root выбирается между edabalans.ru и punycode текущего Tilda-домена.
- `backend/app/intensive_web_access.py`: `set_session`, `session_identity`, `record_entry_attribution` уже разделяют бесплатный интенсив и платный account login. Intensive cookie срок два года; reusable personal link рассчитан на 100 лет.
- `issue_checkout_source_context(secret, token_row, now=None)` / `checkout_source_context_row(db, secret, value, now=None)` реализуют HMAC-подписанный carrier на два часа. Payload содержит database token row reference и expiry, не cookie/browser visitor.
- `telegram-bot/service/app/tracking.py`: `tracking_session_context` поднимает journey_id/entry/messenger/device из `link_prepared`; это существующая связь landing→bot start, но не долговременный browser ID.
- `backend/app/static/site-cookie-notice.js`: существующий общий notice и event `edabalans:cookie-accepted`; срок notice cookie 365 дней. DOM-root cookie назначается только внутри одной registrable domain.

## 4. Integration points / data flow

### Existing advertising flow

Landing JS → API start-link → `TrackingSession` + anonymous `link_prepared` → messenger deep link U... → bot `resolve_start_payload` → `ensure_crm_identity`/MAX `_ensure_identity` → start tracking event с user_id и journey_context → CRM messenger contact. Ссылка fallback B... сохраняет link source, но не гарантирует конкретный prepared journey.

### Existing personal link / payment flow

Bot personal intensive code → `/intensive?i=...` → user/platform intensive session. Bot `/m/{token}` → `source_context` на главной → homepage sessionStorage → checkout body → `trusted_source_snapshot`.

`trusted_source_snapshot(db, settings, source_context)` намеренно возвращает только `original_acquisition` и `current_mailing_touch` со platform. Он не возвращает source_user_id или messenger contact, и не устанавливает buyer identity. В `create_site_checkout` прямые UTM `acquisition_query` сейчас имеют приоритет над этим snapshot: если query присутствует, получается `status=reported`, персональный snapshot не используется.

Owner notification `_buyer_user_id` берёт payment.user_id либо UserEmail совпадение. Поэтому исходный бот-контакт без совпавшего email не появится в уведомлении при текущем контракте. Для attribution-only контакта нужно отдельное поле snapshot/reference и отдельное разрешение источника в уведомлении; менять payment.user_id/права из cookie не требуется.

CRM `user_detail(db, user_id)` выдаёт emails, messengers, AttributionEvent и course events. Browser journey events из tg_tracking_events сейчас не включены в этот response как общий timeline; добавление истории требует чтения и UI в `backend/app/static/crm.js`.

## 5. Existing tests

- Backend pytest использует SQLite fixtures и FastAPI TestClient; внешние Robokassa вызовы подменяются monkeypatch. `backend/tests/test_personal_tracking_routes.py`: `test_personal_masterclass_link_records_trusted_platform()` и reader-cookie tests проверяют доверенный platform, безопасный redirect, неизвестный token.
- `backend/tests/test_intensive_web_access.py`: code/session/progression/events/offer behavior, attribution parameters; существующий персональный поток не должен регрессировать от anonymous visitor.
- `backend/tests/test_robokassa_payments.py`: `test_checkout_uses_database_price_and_does_not_create_user()` защищает разделение source и account; `test_expired_direct_invoice_enqueues_final_failure_owner_alert(monkeypatch)` защищает только confirmed final-state error. Есть отдельный first-subscription error test.
- `backend/tests/test_owner_payment_notifications.py`: existing owner alerts, deduplication, messenger update path. Новый unpaid kind/late paid edit должен иметь отдельные scenario assertions.
- `backend/tests/test_blog_reader_context.py`, `test_blog_reader_navigation.py`: recognition-only cookie не авторизует account/rights.
- `telegram-bot/service/tests/test_tracking.py` и `test_intensive_access.py`: UTM first-touch, prepared U journey, personal links; MAX имеет собственные fixture tests.
- `backend/tests/browser/intensive-onepage-tracking.cjs`, `direct-intensive.e2e.mjs`, `intensive-offer.e2e.mjs`: реальные browser boundaries. Непрерывный cross-domain visitor/backfill/unpaid30 сейчас не покрыты, поскольку runtime отсутствует.

## 6. Shared utilities

- `backend/app/intensive_web_access.py`: aware_utc, HMAC encoding/verification, access_token_row; handles source carrier and purpose guards.
- `telegram-bot/service/app/tracking.py`: tracking_query_params, exact_utm_matches, resolve_start_payload, tracking_session_context, tag canonicalization; UTM/tags не надо дублировать в отдельный каталог.
- `backend/app/owner_payment_notification_service.py`: amount/product/source formatting, HTML escaping, outbox/retries, existing technical routing both owners.
- `backend/app/robokassa_subscription_service.py`: `_operation_state`, `_next_direct_status_check` и row-locking status reconciliation. Final failure codes:10 cancelled/expired;60 refusal in crediting/returned funds. Parse currently returns only result/state integer, не текст issuer decline.

## 7. Potential problems / observed boundaries

- One browser cookie нельзя назначить unrelated registrable domains, даже если сервер/владелец общий. Текущие roots edabalans.ru и похудение-это-есть.рф различны; будущий похудение.рф — третий root. Серверный 30x redirect может принять cookie только собственного host, не читать cookie исходного unrelated host.
- Tilda loader и homepage fetch сейчас используют `credentials:'omit'`. Простая смена на include не обеспечивает third-party cookie работу; браузеры могут блокировать third-party storage, особенно во встроенных messenger browsers. First-party carrier/local visitor необходим на Tilda root.
- Вставка source_context из query очищается после homepage.js, но до него сторонние Tilda scripts могут видеть URL. Новый carrier не должен содержать PII или account session и должен ограничивать target hosts.
- Browser identity и existing account/intensive/auth cookies имеют разные цели. Историю можно приписать link owner по принятой пользователем погрешности; платные права, passwords, email binding и account sessions по нему не выдаются.
- No browser visitor column/index currently in tg_tracking_events. JSON metadata reuse возможен без schema migration, но поиск/backfill по всем JSON events без индекса будет расти с объёмом. Новые indexed columns/table требуют explicit migration/review; schema impact это реальная развилка размера решения.
- Race: anonymous events/post identified update и async page events могут пересекаться; backfill должен охватывать current visitor identity, быть идемпотентным и не перезаписывать confirmed account owner или глобально объединять unrelated users.
- `telegram_user_id` в shared tracking model исторически Telegram label; MAX context нужно хранить platform+platform_user_id в metadata, не интерпретировать MAX ID как Telegram.
- Незавершённый счёт ≠ отказ. Через30 минут pending event не должен ставить failed, отменять invoice или останавливать поздний paid callback. OpStateExt timeout/network failure — неизвестное состояние, не customer payment refusal.
- Current direct status checker выполняется только после checkout expires_at; для30-minute уведомления нужен earlier eligibility и отдельная dedup event state. Recurring child reconciliation исключается из ordinary direct alert logic.

## 8. Constraints & infrastructure / concrete change surface

- Docs owners: messaging.telegram.attribution (links/start identity), platform.crm (canonical contacts), products.intensive (web entry/progress), products.public-site (homepage), platform.commerce (checkout/owner payment notifications), operations.proxy (Caddy). Canonons: LINKS_AND_ATTRIBUTION.md, INTENSIVE_PAGES.md, CRM_DATA_MODEL.md, ROBOKASSA_PAYMENTS.md, PROJECT_IDENTITY.md.
- `infra/caddy/Caddyfile`: PUBLIC_DOMAIN routes generic backend; API_DOMAIN generic backend; APP_DOMAIN backend apps; GO_DOMAIN has `/api/*`, `/m|p/*`, intensive redirects, short redirects. BLOG_DOMAIN allows only explicit reader/context/recognize and blog routes; new browser endpoints on that host need explicit allow route. Caddy shared physical server не меняет cookie root boundaries.
- `backend/app/config.py` содержит app_auth_secret, payment knobs and canonical target settings. Auth signing secret нельзя выводить или хранить в docs/JS.
- Backend dependencies: FastAPI0.141.1, SQLAlchemy2.0.52, Alembic1.19.1, cryptography50.0.0, PostgreSQL via psycopg3.3.4. Для подписанного carrier существующих stdlib HMAC/Fernet достаточно; external SDK не требуется.
- Concrete runtime files for requested behavior: new browser identity service/routes; backend app/main router registration; models/migration only if indexed visitor persistence selected; app_routes intensive integration; personal_tracking_routes outgoing carrier; homepage.js + release-candidate inline checkout; intensive onepage tracking/runtime; bot main/tracking/MAX to carry visitor in prepared journey; CRM service/js timeline; owner notification service source contact fallback; robokassa service snapshot merge; subscription checker30-minute queue.
- Actual Tilda HTML injection/publish cannot be replaced by repository-only commit if live Tilda page не loads modified existing loader. `backend/app/static/homepage-tilda-shell.html` is test shell, not live Tilda publish API. Current actual homepage loader homepage.js обновляется сервером при deploy; archived intensive Tilda loader `tilda-loader.js` fetches `/intensive/archive` with omit credentials. Additional global injection across Tilda pages needs explicit live settings HTML deployment or owner copy/publish; provision script can be prepared in repo.
- Switching live Tilda homepage/domain/DNS and faster page loaders user explicitly deferred to separate task. Browser attribution code can reuse present loader without domain migration or changing account engine.

## 9. External libraries

Новая external library для этой функции не установлена/не требуется исследованием. Context7 инструменты в доступном tool catalog не найдены; описаны только APIs, уже применённые в repository. Внешние правила cookie/Robokassa parent должен сверить по первичной официальной документации перед ответом о browser constraints и issuer rejection detail.

## Updated: 2026-10-08 — generic redirects and browser SDK carrier

### Exact generic `/go` trace

`telegram-bot/service/app/main.py:1061` `_go_response(token, request, session)` вызывается `/go/{token}` (1088) и `/r/{token}` (1093). После resolve_alias и active_link:

- `query = tracking_query_params(request.query_params.multi_items())` сохраняет только `utm_*` и yclid; произвольный visitor parameter в query не проходит этот helper.
- `start_payload = alias.token`; только `if query and link.target_kind == "bot_start"` вызывает `create_tracking_session(session, link, alias, query)`. Без UTM общая ссылка остаётся B...; individual prepared journey для неё не создаётся.
- Для channel_invite открывается alias.telegram_invite_url; для `to=max` configured MAX username, иначе configured Telegram username.
- `web_click` создаётся с tracking_link_id, alias_id и metadata `{"raw_query": query, "warning": suffix_warning, "path_token": token}`. Ни visitor cookie, ни visitor ID, ни journey_id сейчас нет.
- Созданная generic `/go` U-сессия также не имеет `link_prepared` companion event. `tracking_session_context` ищет именно deduplication_key `link_prepared:{row.id}`; поэтому такой U-start возвращает raw UTM, но пустой journey_context. Это отдельный разрыв относительно landing public/start-link flow.

Existing SDK-compatible boundary состоит из небольшого расширения public input, prepared metadata и context whitelist; bot engine/replay/account processing не требуется переписывать. Для generic redirects аналогичный prepared event/carrier необходимо создавать отдельно и для общих ссылок без UTM; существующий TrackSession resolver и first-touch consumers уже умеют передать подготовленный context на start.

### Exact landing preparation

- `backend/app/static/homepage-preview/direct-intensive-loader.js:24` только fetches `/preview/direct-intensive` с credentials omit, вставляет DOM и выполняет scripts полученного HTML. Непосредственного API start-link body в loader нет.
- `backend/app/static/homepage-preview/direct-intensive.html:215`: anonymous attribution читает sessionStorage `edb_direct_intensive_attribution_v1`, накладывает текущие query UTM/yclid и сохраняет назад. Это source storage на текущем root, не browser identity storage.
- `direct-intensive.html:261` `prepare(channel, entry)` делает POST CONTENT.links.apiUrl, mode cors, credentials omit, abort2500ms; exact body `JSON.stringify({messenger:config.apiMessenger,entry,alias:CONTENT.links.alias,landing_variant:ACTIVE_VARIANT,...attribution})`.
- `direct-intensive.html:289` готовит четыре отдельных состояния: button/qr для tg/max; fallback постоянный alias. SDK visitor context должен быть готов до этих подготовок, иначе один из четырёх prepared journeys потеряет связь с anonymous browser.
- `telegram-bot/service/app/schemas.py:25` `PublicMessengerStartLinkIn` имеет `ConfigDict(extra="forbid")`. Простое добавление visitor field frontend сейчас даст422; schema необходимо расширить bounded field, передавая opaque visitor carrier, не произвольный user_id.
- `telegram-bot/service/app/tracking.py:122` `tracking_session_context(session,row)` пропускает только `("journey_id","entry","messenger","device")`; visitor carrier нужно явно включить или обработать до этого return. Метаданные JSON не передаются целиком.

### Actual start events and bot identity

`bot_scenario_started` literal отсутствует во всём Python/doc repository. Фактические raw DB events — `start_first`, `start_repeat`, `start_maintenance`, `start_unknown`, `start_expired_session` (TG); MAX uses first/repeat with platform metadata.

- `tracking.py:271`: TG metadata `payload_status`, `raw_query`, `is_first_bot_visit`, затем `**journey_context`. Contact id и user id — отдельные columns.
- `max.py:1007`: MAX metadata `messenger:"max"`, `payload_status`, `raw_query`, `**journey_context`, `max_delivery_status:"pending"`, `max_intensive_token_id`; later delivery добавляет max_message_id и меняет status. Telegram-named tracking_user column хранит MAX user ID в этом пути.
- `main.py:1294`: resolve_start_payload→assign_first_touch получают context существующим argument. `max.py:1502` делает equivalent flow. Если prepared context содержит новый visitor field после whitelist, можно связать bot identity с anonymous visitor именно здесь, без переписывания scenario engine.
- `telegram-bot/service/app/models.py:23`: `BotInstance`/tg_bot_instances хранит id, code, username, display_name, token_env_name, active/production flags. Только username/code/display_name пригодны для CRM source; token_env_name не секретное значение, но не нужен в публичной истории.
- `models.py:35`: Contact/tg_contacts содержит bot_instance_id FK и user_id; unique bot_instance_id+telegram_user_id. Соединение tracking.contact_id→Contact.bot_instance_id→BotInstance обеспечивает точное имя бота при known event. Telegram `ensure_contact` обновляет contact и вызывает ensure_crm_identity ещё до first-touch обработки; MAX `_ensure_contact` также получает bot instance и account.

История общей anonymous ссылки не может быть восстановлена из текущих данных по browser без новой visitor capture: ни generic web_click, ни direct landing source sessionStorage не дают постоянную browser связь. После внедрения SDK идентификатор/подписанный carrier сохраняется root-local и переносится в prepared bot journey; персональная ссылка другого root затем даёт user association уже записанным anonymous events. Исторические события без visitor связать достоверно по этому механизму невозможно.
