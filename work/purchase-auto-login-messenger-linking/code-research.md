# Исследование кода: покупка, автоматический вход и привязка мессенджеров

Дата исследования: 2026-09-20  
Исследованный срез: `origin/main` @ `ac63a54`.

Локальная рабочая ветка сильно отстаёт от `origin/main` и содержит многочисленные
чужие незакоммиченные файлы. Поэтому факты ниже получены через `git show` и
`git grep` именно из свежего `origin/main`; локальные незакоммиченные прототипы не
считаются production-кодом.

## Краткий вывод

Текущий production-контур уже умеет безопасно подтвердить покупку, выдать право,
создать 10-дневные ссылки Telegram/MAX, отправить их по email и держать 30-дневную
native-сессию ЛК. Но текущая последовательность обратна новой концепции:

1. после оплаты письмо предлагает выбрать Telegram или MAX;
2. только бот создаёт пароль и выдаёт его пользователю;
3. один post-paid onboarding разрешает привязать только один мессенджер;
4. success page лишь ждёт webhook и предлагает проверить почту;
5. старый шаг привязки мессенджера в дне 1 скрыт и технически умеет только
   Telegram;
6. предпочтительный мессенджер как самостоятельный факт в БД отсутствует.

Для нового поведения можно переиспользовать подтверждение платежа, выдачу прав,
шифрование пароля, native-сессию, устойчивую email-очередь, одноразовые токены и
остановку предпродажных цепочек. Нельзя переиспользовать без изменения
`AccountOnboarding.claimed_at/claimed_platform`: эта модель намеренно блокирует
вторую привязку.

Ключевое техническое ограничение автоматического входа: публичная страница
покупки вызывает checkout cross-origin с `credentials: "omit"`, а CORS настроен
с `allow_credentials=False`. Поэтому текущий AJAX checkout не может надёжно
положить first-party HttpOnly cookie домена `edabalans.ru`. Безопасная точка
привязки браузера должна быть отдельным top-level переходом через
`edabalans.ru` до Robokassa либо другим одноразовым checkout grant; одного
публичного `InvId` недостаточно.

## 1. Entry Points

### Прямая покупка Robokassa

- `backend/app/robokassa_routes.py` — HTTP-обвязка прямой оплаты.
  - `robokassa_checkout(body: RobokassaCheckoutIn, request, db, settings) -> dict`
    (`POST /api/payments/robokassa/checkout`) проверяет origin/rate limit и вызывает
    `create_payment`.
  - `robokassa_result2(request, db, settings) -> PlainTextResponse`
    (`POST /integrations/robokassa/result2`) принимает подписанный серверный webhook
    и вызывает `confirm_payment`.
  - `robokassa_status(invoice_id, db) -> dict`
    (`GET /api/payments/robokassa/{invoice_id}/status`) публично отдаёт только
    `status` и `success_kind`.
  - `robokassa_success(InvId) -> HTMLResponse`
    (`GET /payments/robokassa/success`) строит страницу через `_return_page`.
  - `_return_page(...) -> HTMLResponse` каждые 2 секунды опрашивает публичный
    status endpoint с `credentials: "omit"`. После `paid` заменяет текст, но не
    создаёт сессию и не вызывает защищённый вход.
- `backend/app/robokassa_service.py` — платёжная транзакция.
  - `create_payment(db, settings, version, price_code, email_original, *,
    offer_user_id=None, account_user=None, source_context=None,
    acquisition_query=None) -> dict` создаёт `Payment(pending)` и
    `OfferCheckout`, но не создаёт пользователя для публичной покупки и не
    сохраняет browser-bound секрет.
  - `confirm_payment(db, settings, compact_jws) -> str` проверяет JWS и сумму,
    блокирует платёж, создаёт/находит пользователя, выдаёт доступ, фиксирует
    события и ставит post-paid onboarding. Повтор webhook идемпотентен.
  - Покупка из уже авторизованного ЛК помечается `account_purchase=True`; для неё
    post-paid onboarding намеренно не создаётся, потому что сессия и пароль уже
    существуют.
- `backend/app/static/homepage-preview/release-candidate.html` и
  `backend/app/static/homepage-preview/mobile.html` — текущая форма покупки.
  `fetch(.../api/payments/robokassa/checkout, {credentials: "omit"})` получает
  `payment_form`, после чего браузер напрямую отправляет форму в Robokassa.
- `backend/app/main.py` — CORS допускает заданные origins, но
  `allow_credentials=False`. Это подтверждает, что текущий cross-origin checkout
  не является браузерной сессией.

### Покупка через Tilda

- `backend/app/tilda_routes.py` — `POST /integrations/tilda/payments` принимает
  form-urlencoded webhook с интеграционным токеном и вызывает
  `process_tilda_payment`.
- `backend/app/tilda_service.py` —
  `process_tilda_payment(db, payload, settings)` создаёт/находит пользователя,
  идемпотентно подтверждает оплату, выдаёт доступ и вызывает
  `ensure_paid_account_onboarding`.
- В legacy-заказе Tilda может не быть серверного `OfferCheckout`: продукт
  определяется по alias. Webhook приходит сервер-сервер и не может установить
  cookie покупателю. Текущая Tilda success page не связана с браузером
  одноразовым секретом.

Следствие для feature boundary: прямой Robokassa checkout можно связать с
браузером внутри своего домена. Для старого Tilda cart потребуется отдельная
инструментация checkout/return либо останется fallback «войти данными из письма».
Нельзя считать email из формы или `InvId` доказательством владения аккаунтом.

### Email и выдача учётных данных

- `backend/app/account_onboarding_service.py` — текущий post-paid onboarding.
  - `ensure_paid_account_onboarding(db, payment, settings) -> AccountOnboarding | None`
    создаёт ровно один onboarding на `payment_id`.
  - `_create_onboarding(...)` выпускает два raw token, хранит их зашифрованным
    bundle и создаёт два `MessengerLinkToken` с purpose `account_credentials`.
  - `account_access_email(...) -> EmailMessage` сейчас пишет «откройте удобный
    мессенджер, чтобы получить логин и пароль» и включает две 10-дневные ссылки.
    Пароля в email нет.
  - `process_due_account_email(settings) -> bool` берёт одну pending/retry запись
    с `FOR UPDATE SKIP LOCKED`, отправляет SMTP и делает до 8 попыток с backoff.
  - `account_email_worker(...)` запускается lifespan-задачей из
    `backend/app/main.py` при включённых флагах.
- `backend/app/account_security.py` — `generate_password`, `password_hash`,
  `verify_password`, `encrypt_password`, `decrypt_password`, `token_hash`.
  Пароль хранится как scrypt hash плюс опциональная Fernet-зашифрованная копия.
  Это уже даёт техническую возможность повторно отправить существующий пароль,
  если `password_ciphertext` заполнен.
- `backend/app/crm_service.py` — `reveal_account_password(...)` и
  `reset_account_password(...)` уже используют зашифрованную копию и аудит.

### Native session и ЛК

- `backend/app/account_auth_routes.py` — собственная авторизация клиента.
  - `native_session_user(request, db) -> User | None` проверяет hash cookie,
    срок, статус пользователя и `password_version`.
  - `set_native_session(response, db, user, settings) -> str` создаёт случайный
    32-byte token, хранит только hash в `account_sessions`, ставит cookie
    `edabalans_account_session` на 30 дней: HttpOnly, Secure, SameSite=Lax,
    path `/`, host-only.
  - `POST /api/account-auth/login` проверяет email + scrypt password и вызывает
    `set_native_session`.
  - `GET /lk` отдаёт `backend/app/static/account-portal.html`.
- `backend/app/static/account-portal.html` — при 401 показывает форму
  email/password. Подстановки checkout credential или payment grant нет.
- `backend/app/access_routes.py` —
  `account_payload(email, db, *, progress_user_id=None) -> dict` формирует курсы,
  приложения, покупки и legal state. Messenger status в payload не входит.
- `backend/app/static/apps/account.html` — основная страница ЛК; в шапке сейчас
  бренд, email и выход. Панели Telegram/MAX, выбора основного и отвязки нет.

### День 1 мастер-класса

- `content/masterclass/course/course.json` — канонический порядок материалов.
  Сейчас в дне 1:
  1. `day-01-article-tutorial`;
  2. `day-01-article-02` — дневник питания;
  3. `day-01-article-03` — взвешивание;
  4. `day-01-questionnaire`;
  5. `day-01-messenger-link` — `hidden: true`, completion `link_requested`;
  6. `day-01-offer`.
  Соответствующая ручная галочка `day-1-check-4` тоже скрыта и необязательна.
- `backend/migrations/versions/20260908_0039_hide_legacy_messenger_step.py` —
  production-миграция, которая скрыла старый messenger step.
- `backend/app/course_structure_service.py` —
  `effective_required_step_ids(...)` фиксирует набор обязательных шагов и revision
  при первом открытии дня. Простое изменение JSON не обязательно задним числом
  добавит новый required step уже начавшим день пользователям.
- `backend/app/masterclass_routes.py` — общий complete endpoint проверяет порядок,
  но сам по себе не доказывает факт привязки messenger account. Существующий
  `completion: link_requested` означает лишь действие в UI, не успешную связь.
- `backend/app/static/masterclass.js` и фактическая оболочка
  `backend/app/static/masterclass-first-days-preview.html` — special-step UI.
  `openSpecialStep` проверяет только Telegram и генерирует Telegram deep link.
- `backend/app/masterclass_routes.py`:
  - `create_messenger_link(...)` (`POST /api/masterclass/messenger-links`) создаёт
    15-минутный token purpose `link_account`, но `MessengerLinkIn.platform`
    ограничен regex `^telegram$`, а URL всегда `t.me`.
  - `messenger_link_status(...)` уже читает и Telegram, и MAX, но генератор MAX
    отсутствует.
  - после onboarding questionnaire выбирается последняя по `linked_at` учётная
    запись Telegram/MAX и её platform/id пишутся в notification payload. Это
    случайное правило «последняя привязка», а не предпочтение пользователя.

### Telegram/MAX consumers

- `telegram-bot/service/app/masterclass_link.py` —
  `consume_masterclass_link(...)` принимает Telegram `M...` token purpose
  `link_account` или `account_credentials`, связывает identity с CRM user,
  создаёт пароль для credential claim и вызывает остановку presale.
- `telegram-bot/service/app/max.py` — `_consume_account_link(...)` принимает MAX
  token только purpose `account_credentials`, создаёт/переиспользует credential и
  останавливает presale. Обычный `link_account` для MAX не реализован.
- Оба consumer сейчас смотрят на `AccountOnboarding.claimed_at`; после первого
  выбранного messenger второй account-credential link отвергается.
- `telegram-bot/service/app/masterclass_dispatch.py` —
  `dispatch_due_masterclass_notifications(..., platform="telegram")` умеет
  отправлять адресно в Telegram или MAX по `payload.target_platform`,
  `target_platform_user_id`, `target_messenger_account_id`. Но сам preferred
  platform не вычисляет: источник должен положить его в payload.

### Маркетинговые и сервисные последовательности

- `telegram-bot/service/app/customer_lifecycle.py`:
  - `stop_presale_runs_for_user(session, user_id, *, reason) -> int` останавливает
    активные/waiting `START_ENTRY`, `WELCOME`, `PREPURCHASE` по всем Contact,
    связанным с одним CRM user.
  - `stop_presale_runs_from_purchase_events(session) -> int` реагирует на
    `masterclass_purchase_confirmed`.
  - `reconcile_masterclass_presale_runs(session) -> int` — safety net по наличию
    `ACCESS_MASTERCLASS`.
- Telegram/MAX linking также вызывает `stop_presale_runs_for_user(...,
  reason="messenger_link_confirmed")`.
- Таким образом, покупка уже прекращает presale для корректно связанной личности;
  новая привязка нужна для legacy bot identity, которую нельзя было сопоставить с
  email покупки.
- `MessengerAccount.subscription_status` — состояние подписки/членства канала,
  не consent и не preferred messenger.

## 2. Data Layer

### Существующие таблицы

- `backend/app/models.py::MessengerAccount`
  - `user_id`, `platform`, `platform_user_id`, username/name, timestamps;
  - `subscription_status`, `subscription_checked_at`, `main_scenario_seen_at`;
  - unique (`platform`, `platform_user_id`);
  - поля preferred/primary/disconnected отсутствуют.
- `MessengerLinkToken`
  - `user_id`, optional `account_onboarding_id`, `platform`, `purpose`, unique
    `token_hash`, `expires_at`, `consumed_at`;
  - уже подходит для отдельных одноразовых Telegram и MAX links.
- `AccountCredential`
  - одна запись на `user_id`;
  - `password_hash`, nullable `password_ciphertext`, `password_version`,
    `issued_via`;
  - existing credential можно переиспользовать без ротации, если ciphertext есть.
- `AccountSession`
  - hashed token, user, password version, expiry/revoke/last seen;
  - session не зависит от messenger platform.
- `AccountOnboarding`
  - unique nullable `payment_id`, encrypted claim bundle, 10-day expiry;
  - singular `claimed_platform` и `claimed_at` моделируют выбор ровно одного
    messenger;
  - durable email fields `email_status`, attempts, next attempt, sent/error.
- `Payment` + `OfferCheckout`
  - хранят pending/paid факт и snapshot checkout;
  - текущего browser-grant hash/expiry/consumed поля нет.
- `MasterclassStepProgress`, `MasterclassDayProgress`, `MasterclassEvent`
  - прогресс и идемпотентные события курса;
  - messenger linkage остаётся отдельным фактом `messenger_accounts`.
- `MasterclassNotification`
  - durable notification + JSON payload; dispatcher уже понимает явный target.
- В telegram service используются зеркальные SQLAlchemy-модели общей БД
  (`telegram-bot/service/app/models.py::CrmMessengerAccount`,
  `MasterclassNotification`). Любая миграция общего messenger contract должна
  быть отражена в обеих моделях либо читаться через общий SQL.

### Нужные новые факты (в текущей схеме отсутствуют)

1. **Предпочтительный messenger пользователя.** Устойчивее один user-level факт
   (`telegram|max|null`), а не два независимых boolean на MessengerAccount: иначе
   возможны два «основных» одновременно. Он должен ссылаться только на реально
   linked account.
2. **Одноразовая browser-to-payment связь.** Нужен random secret, в БД только
   hash + payment/checkout id + expiry + consumed/revoked timestamp. Публичный
   `invoice_id` для этого не годится.
3. **Результат delivery credentials email.** Текущая onboarding запись может
   остаться durable email job, но её смысл и copy меняются: credential создаётся
   при подтверждении оплаты, а claim links больше не являются условием создания
   пароля.

Миграция потребуется как минимум для preferred messenger и browser grant.
Изменение `claimed_at` может быть либо удалением single-choice семантики, либо
отделением payment email delivery от независимых messenger-link tokens. Второй
вариант лучше отражает реальные жизненные циклы: покупка/email одноразовы на
payment, привязка каждого messenger — на user/platform.

## 3. Similar Features

- `set_native_session` — готовая единственная функция выпуска клиентской сессии;
  payment success не должен создавать собственный формат session cookie.
- `MessengerLinkToken` + `token_hash` — готовый паттерн raw token клиенту / hash
  в БД / срок / consumption.
- `account_onboarding_service.process_due_account_email` — готовая устойчивая
  SMTP-очередь с retry; не требуется вторая email-система.
- `ensure_paid_account_onboarding` — готовая идемпотентность на payment id.
- Telegram `link_account` consumer — готовое безопасное связывание disposable
  identity с CRM user и проверка конфликтов.
- MAX `account_credentials` consumer — готовое связывание MAX identity; ему не
  хватает нормального `link_account` branch.
- Questionnaire notification payload — готовый способ адресовать доставку в
  конкретный platform account. Следует заменить выбор последнего linked account
  чтением preferred source, а не менять dispatcher.
- `stop_presale_runs_for_user` + purchase event/reconciliation — готовый единый
  механизм остановки acquisition sequences. Не нужно добавлять проверку покупки
  перед каждым сообщением.
- `crm_service.reveal_account_password` — существующий путь расшифровки пароля;
  email sender должен использовать тот же cryptographic contract, а не хранить
  второй plaintext.

## 4. Integration Points и трассировки данных

### Текущий public purchase

```text
Tilda/public page (email)
  -> POST /api/payments/robokassa/checkout [credentials: omit]
  -> Payment pending + OfferCheckout
  -> browser posts directly to Robokassa
  -> Robokassa ResultUrl2 JWS
  -> confirm_payment: User + access + purchase event + AccountOnboarding
  -> email worker: Telegram/MAX claim links
  -> one bot consumes one claim
  -> AccountCredential created + password sent in bot
  -> user manually logs in -> native session
```

### Целевой контур, который поддерживает существующая архитектура

```text
checkout creation
  -> one-time browser/payment grant (hash in DB)
  -> top-level own-domain start binds grant to browser
  -> Robokassa
  -> signed ResultUrl2 is still the only proof of payment
  -> confirm_payment creates/reuses User + AccountCredential + access
  -> durable email sends login/password + /lk
  -> success page consumes browser grant only after paid
  -> set_native_session -> button enters /lk without password in URL/HTML
```

Пароль нельзя передавать в query, localStorage, публичный status response или
HTML success page. Одноразовый grant только создаёт native session после
серверной проверки `payment_status=paid`, соответствия checkout и consumption.

### Файлы, которые затронет будущая реализация

- `backend/app/models.py` + новая Alembic migration — browser grant и preferred
  messenger contract.
- `backend/app/robokassa_routes.py`, `robokassa_service.py` и checkout JS —
  first-party binding, безопасный success consume, кнопка входа.
- `backend/app/tilda_service.py`/Tilda checkout integration — только если владелец
  требует тот же auto-login для legacy Tilda. Один webhook недостаточен.
- `backend/app/account_security.py`, `account_onboarding_service.py` — единый
  create-or-reuse credential до email; новое письмо с логином/паролем.
- `backend/app/account_auth_routes.py` — использовать `set_native_session` в новом
  grant endpoint; формат основной session не менять.
- `backend/app/access_routes.py`, `backend/app/static/apps/account.html` — статус
  Telegram/MAX, preferred и управление.
- `content/masterclass/course/course.json` — переставить и открыть messenger step
  сразу после дневника и до анкеты; обновить check/summary.
- `backend/app/course_structure_service.py`, `masterclass_routes.py` — реальный
  completion guard «linked хотя бы один messenger» и revision policy.
- `backend/app/static/masterclass.js` /
  `masterclass-first-days-preview.html` — обе кнопки, polling обоих статусов,
  выбор preferred, понятные states.
- `telegram-bot/service/app/masterclass_link.py`, `max.py` — разрешить независимую
  связь обеих платформ и не создавать/не выдавать credential в новом course-link
  flow.
- `telegram-bot/service/app/masterclass_dispatch.py` менять не обязательно:
  target contract уже есть; producer должен выбирать preferred.
- `telegram-bot/service/app/customer_lifecycle.py` вероятно переиспользуется без
  изменения, но нужны регрессионные тесты по двум Contact.
- Каноническая документация после решения:
  `docs/TILDA_PAYMENTS.md`, карточки `platform.auth`, `platform.commerce`,
  `products.masterclass.messenger-links`, `products.masterclass.runtime`,
  `COURSE_STRUCTURE_CONTRACT.md`, `COURSE_RUNTIME.md`, legal/messaging docs.

## 5. Existing Tests

### Backend pytest

- `backend/tests/test_account_password_auth.py`
  - `test_paid_payment_creates_one_idempotent_onboarding_with_two_platform_links`
  - `test_account_access_email_contains_claim_links_but_not_a_password`
  - `test_login_sets_remembered_http_only_session_and_logout_revokes_it`
  - `test_admin_can_reset_and_reveal_password_with_audit_log`
  - Эти тесты закрепляют старое поведение и должны быть сознательно заменены:
    email без пароля и single messenger claim более не соответствуют новой модели.
- `backend/tests/test_robokassa_payments.py`
  - `test_public_payment_success_waits_for_callback_then_renders_canonical_copy`
  - `test_signed_production_result_grants_access`
  - Есть хорошая граница «browser return не подтверждает платёж; только ResultUrl2».
- `backend/tests/test_tilda_payments.py`
  - покрывает paid/access/idempotency и checkout reference, но не browser return.
- `backend/tests/test_masterclass_journey.py`
  - `test_legacy_first_day_messenger_step_is_hidden_by_production_migration`
  - `test_onboarding_can_generate_only_one_active_short_lived_telegram_link`
  - questionnaire ordering, rollback и linked/no-linked delivery tests.

### Telegram/MAX pytest

- `telegram-bot/service/tests/test_masterclass_link.py`
  - `test_account_claim_creates_password_once_without_premature_questionnaire`
  - `test_existing_password_hint_points_to_the_original_issue_date`
- `telegram-bot/service/tests/test_max.py`
  - `test_max_account_link_issues_short_password`
  - `test_max_account_link_rejects_second_messenger_after_telegram_claim`
- `telegram-bot/service/tests/test_customer_lifecycle.py`
  - `test_masterclass_access_stops_presale_without_per_message_purchase_checks`
- `telegram-bot/service/tests/test_masterclass_dispatch.py`
  - `test_questionnaire_delivery_uses_only_the_linked_max_contact`

### Обязательные новые тестовые границы

1. Browser grant:
   - нет/неверный/истёкший grant не создаёт session;
   - pending payment не создаёт session;
   - paid + правильный grant создаёт session через `set_native_session`;
   - grant одноразовый, replay и чужой invoice отклоняются;
   - invoice/status/HTML не раскрывают email, password, user_id или grant.
2. Credential/email:
   - новая покупка создаёт credential один раз до email;
   - повтор webhook не дублирует письмо/credential;
   - повторная покупка переиспользует существующий пароль без ротации;
   - legacy credential без ciphertext следует выбранной recovery policy;
   - password не попадает в логи, event details, status API.
3. Messenger:
   - Telegram и MAX могут быть связаны независимо;
   - повтор token идемпотентно/явно отклонён, чужой platform identity не
     переезжает без существующих conflict checks;
   - первый linked становится preferred только по заданному правилу;
   - второй linked не меняет preferred молча;
   - смена preferred влияет на questionnaire delivery.
4. Course progression:
   - messenger step стоит после дневника и до анкеты;
   - UI click не завершает step без фактического linked account;
   - хотя бы один linked account завершает required step;
   - поведение для уже начавших/завершивших день соответствует revision policy.
5. Lifecycle/consent:
   - purchase останавливает presale по Telegram и MAX contacts;
   - поздняя привязка legacy identity также останавливает presale;
   - `/stop` не отменяется повторной привязкой или покупкой;
   - автоматическая доставка идёт только в preferred, явная кнопка — в выбранный.
6. UI/browser:
   - account payload показывает linked/unlinked/preferred без platform user id;
   - mobile/desktop card позволяет привязать второй и сменить основной;
   - обязательный material корректно восстанавливает состояние после возврата из
     бота.

## 6. Shared Utilities

- `backend/app/app_service.py::normalize_email` и `EMAIL_RE` — единая
  нормализация email; не дублировать в purchase flow.
- `backend/app/account_security.py::token_hash` — SHA-256 contract для session и
  link tokens; подходит browser grant.
- `backend/app/account_security.py::{generate_password,password_hash,
  encrypt_password,decrypt_password}` — единая credential реализация.
- `backend/app/account_auth_routes.py::set_native_session` — единственный session
  issuer.
- `backend/app/account_onboarding_service.py::_send_message` и worker — SMTP и
  retry.
- `backend/app/masterclass_routes.py::resolve_masterclass_user` /
  `require_native_user` — auth boundary курса.
- `backend/app/course_structure_service.py::effective_required_step_ids` —
  versioned required-step semantics.
- `telegram-bot/service/app/customer_lifecycle.py::stop_presale_runs_for_user` —
  единый stop acquisition.
- `telegram-bot/service/app/masterclass_dispatch.py` — единый сервисный dispatcher
  Telegram/MAX по explicit target.

## 7. Potential Problems

### Безопасность и приватность

- `InvId` публичен и status endpoint не требует auth. Делать из него login token
  нельзя.
- Автоподстановка password в login form, query string или JavaScript раскрывает
  credential истории браузера, логам, referrer и расширениям. Безопасный эквивалент
  пользовательского сценария — одноразовый browser grant -> native session.
- Письмо с plaintext password расширяет поверхность доступа по сравнению с
  текущей схемой. Это явное продуктовое решение владельца; в БД всё равно следует
  сохранять только hash + зашифрованную копию, не plaintext.
- Повторное email-сообщение существующего password возможно только для записей с
  `password_ciphertext`. Legacy hash-only password восстановить нельзя.
- Одновременная связь двух платформ требует сохранить запрет переназначения уже
  принадлежащего другому user platform account.

### Race conditions и идемпотентность

- ResultUrl2, success polling, email worker и bot linking могут идти одновременно.
  Credential create-or-reuse должен выполняться под блокировкой user/credential и
  опираться на unique `AccountCredential.user_id`.
- Browser grant consumption и session creation должны быть одной транзакционной
  операцией либо иметь однозначный retry после сетевого обрыва.
- Два почти одновременных bot links не должны создать два preferred значения.
- `AccountOnboarding` идемпотентен на payment, но повторная покупка создаёт новый
  onboarding; новый email contract обязан отличать webhook retry от новой оплаты.

### Course structure

- Удаление `hidden` недостаточно: generic complete может засчитать шаг без связи.
- Required step snapshot уже сохранён у части пользователей. Без явной revision
  policy изменение затронет новых и старых непоследовательно.
- Нельзя связывать «linked сейчас» и «step когда-то выполнен» навсегда: пользователь
  может позже отвязать messenger. Нужно отдельно решить, блокирует ли отвязка уже
  пройденный курс (обычно нет).

### Preference и consent

- «Предпочтительный messenger» и «разрешение на рекламу» — разные факты.
  Preferred выбирает маршрут; он не должен автоматически возобновлять остановленную
  рассылку.
- `docs/knowledge-base/LEGAL_DOCUMENTS.md` отделяет consent на информационные/
  рекламные сообщения от обработки данных и связывает bot Start с согласием, а
  `/stop` — с отказом. В центральной БД отдельного user-level marketing consent
  сейчас нет; engine опирается на contact/sequence status.
- Сервисные сообщения анкеты уже явно адресуются platform. Общие automatic
  mailings пока не имеют единого preferred resolver.

### Tilda и домены

- Legacy Tilda webhook не доказывает, какой браузер совершил покупку. Нельзя
  «автовойти по email из webhook».
- Текущий public checkout cross-origin и без credentials. Для Robokassa нужен
  first-party top-level bind перед уходом в платёжку; простое `Set-Cookie` в
  текущем fetch не является надёжным решением.
- `account_public_url` по умолчанию указывает на кириллический Tilda-домен `/lk`,
  тогда как native session cookie host-only ставится backend-доменом. Production
  proxy/domain contract нужно проверить при реализации, чтобы кнопка не уводила
  на host, где cookie недоступна.

### Документационные расхождения

- `COURSE_RUNTIME.md` сейчас утверждает, что messenger step скрыт, потому что новый
  покупатель связывает messenger при создании аккаунта. Новая концепция это
  отменяет.
- `platform.auth` и `TILDA_PAYMENTS.md` описывают email -> messenger -> password;
  после изменения они должны быть обновлены вместе с кодом.
- AGENTS.md содержит старое неподвижное ограничение «Tilda — единственный вход»,
  тогда как `origin/main` уже реализует native password session. Перед
  реализацией интегрирующий поток должен синхронизировать этот канон, иначе
  инструкции и production расходятся.

## 8. Constraints & Infrastructure

- Backend: FastAPI `0.141.1`, SQLAlchemy `2.0.52`, Alembic `1.19.1`, PostgreSQL,
  `cryptography 50.0.0`; Telegram service использует те же версии FastAPI/
  SQLAlchemy/cryptography.
- SMTP worker живёт внутри backend lifespan и включается settings:
  `account_onboarding_enabled`, `account_email_worker_enabled`, SMTP credentials,
  bot usernames, `account_public_url`.
- Native session duration: `account_session_days` (по умолчанию 30).
- Current messenger link lifetimes: paid credential claim 10 дней; course
  `link_account` 15 минут.
- Наружу backend/DB не публикуются напрямую; маршрутизация идёт через Caddy.
- Production payment/Tilda setting changes требуют отдельного явного подтверждения
  владельца. Миграция БД также является отдельной production точкой.
- Тексты письма и нового обязательного учебного материала — пользовательский текст;
  по AGENTS.md их финальная редактура должна пройти через `edabalans-writer`.
- Владельцы модулей по `docs/modules.toml`:
  - auth/session — `platform.auth`;
  - payment/onboarding/email/account page — `platform.commerce`;
  - progress — `products.masterclass.runtime`;
  - tokens/link contract — `products.masterclass.messenger-links`;
  - Telegram/MAX consumption — соответствующие messaging modules.

## 9. External Libraries

Новая внешняя библиотека для описанного поведения не требуется. Существующих
FastAPI responses/cookies, SQLAlchemy row locks, Alembic, `secrets`, SHA-256,
Fernet и SMTP достаточно. Специальный внешний API Robokassa/Tilda не исследовался
за пределами уже реализованного project contract: детали их production return URL
нужно подтверждать существующей документацией провайдера только при выборе
конкретной схемы browser binding.

## Решения, которые действительно нужны от владельца

1. **Охват auto-login.** Достаточно ли автоматически входить после нового прямого
   Robokassa checkout, а legacy Tilda оставлять с email/password fallback? Для
   Tilda тот же результат потребует отдельного изменения checkout/success setup.
2. **Старые участники дня 1.** Рекомендуемая безопасная граница: обязательным новый
   шаг становится для тех, кто ещё не прошёл анкету/день; завершивших день не
   откатывать, а показывать им необязательную панель связи в ЛК. Нужна фиксация.
3. **Место шага.** Фраза «после дневника и до анкеты» допускает два порядка из-за
   материала о взвешивании. По последнему описанию логичен прямой порядок:
   дневник -> привязка -> взвешивание -> анкета. Нужна редакционная фиксация.
4. **Что управляет preferred.** Рекомендуемая единая семантика: preferred —
   адрес всех автоматических сервисных и разрешённых рассылочных сообщений;
   явные кнопки «отправить в Telegram/MAX» всегда переопределяют выбор на одну
   отправку. Нужно подтвердить, относится ли preferred также к маркетингу.
5. **Отвязка последнего messenger.** Рекомендуем не откатывать уже завершённый
   course step, а предупреждать, что доставки не будет. Нужно подтвердить.
6. **Legacy password без ciphertext.** Его нельзя узнать и отправить. Варианты:
   не менять пароль и направить к ручному восстановлению; либо один раз сбросить и
   отозвать все sessions. Рекомендуется не делать скрытый reset при повторной
   покупке.
7. **Повторная покупка.** Рекомендуется: право обновляется штатно, password не
   ротируется, email повторно сообщает существующие credentials только если их
   можно расшифровать, новые messenger links создаются только по явному запросу из
   ЛК. Требуется продуктовая фиксация.

## Updated: 2026-09-20 — полный контур сообщений и отказоустойчивые состояния

### 10. Все производители сообщений Telegram/MAX

Ниже «producer» означает код, который инициирует исходящую доставку или создаёт
устойчивую запись, которую затем доставляет scheduler. Простые ссылки на Telegram/
MAX в HTML сайта сюда не включены.

| Producer | Автоматический/ручной | Telegram сейчас | MAX сейчас | Источник и фактическая граница |
|---|---|---:|---:|---|
| Sequence engine | автоматический по графу и таймерам | да | да | `telegram-bot/service/app/engine.py::advance_run`; sender выбирается в `main.py::_sequence_sender` по `BotInstance.code`. Обслуживает `welcome_intensive`, `prepurchase_nurture`, а также существующие disabled-каркасы `postpurchase_masterclass` и `postmasterclass_nurture`. |
| Start router | автоматический ответ на Start/повторный Start | да | да | `start_router.py::execute_start_decision` и `send_system_content`; Telegram вызывает из `main.py::process_update`, MAX — из `max.py::_deliver_welcome`. Отправляет entry, навигацию, статус интенсива/уже купленного МК и запускает sequence run. |
| Accelerated sequence run из админки | ручной технический запуск | да | да | `POST /bot-api/contacts/{contact_id}/accelerated-run`; sender выбирается по конкретному Contact. Это не отдельный текстовый движок, а ручной запуск того же sequence engine. |
| Разовые broadcasts | ручной launch/schedule, затем scheduler | да | нет | `main.py::{create_broadcast,launch_broadcast,schedule_broadcast,_deliver_broadcast}`. `_broadcast_contacts` исключает `BotInstance.code == "max"`, все launch/test/retry используют `client()` Telegram. |
| Ручное сообщение конкретному Contact | ручной | да | да | `POST /bot-api/contacts/{contact_id}/messages`; `_sequence_sender` выбирает платформу. Текст без медиа/кнопок. |
| Ручное сообщение по `user_id` | ручной | формально да | формально да | `POST /bot-api/users/{user_id}/messages` берёт просто самый свежий Contact независимо от preferred и передаёт его в общий manual producer. Поэтому при двух мессенджерах адресат сейчас не детерминирован продуктовым правилом. |
| Masterclass notification outbox | автоматический | почти все типы | только 2 типа | Producer — `backend/app/masterclass_routes.py::queue_notification`, consumer — `masterclass_dispatch.py::dispatch_due_masterclass_notifications`. `main.py::dispatch_masterclass_notifications(platform="max")` жёстко разрешает MAX только `messenger_identity` и `messenger_questionnaire`. |
| Начальная анкета: данные и копия | автоматический после submit | да | да, если payload явно MAX | `finish_questionnaire` пишет `messenger_identity` и `messenger_questionnaire` с точным target account. Сейчас выбирается последний `linked_at`, не preferred. Telegram link consumer также может поставить эти две записи с target Telegram. |
| Опросник питания дня 2 | автоматический после submit | да | нет | Kind `current_diet_questionnaire`, content `tpl_postpurchase_current_diet`; payload не содержит target. MAX scheduler этот kind не берёт. |
| Копия итогового саморевью | автоматический после submit | да | нет | Kind `closing_review_copy`; MAX scheduler не берёт. |
| Напоминание «день не открыт к 18:00» | автоматический | да | нет | Kind `course_day_unopened_18h`; создаётся в `finalize_course_day`, перед отправкой повторно проверяется актуальность. |
| Возврат после 72 часов без активности | автоматический | да | нет | Kind `course_stalled_72h`; создаётся `course_event`, новые события отменяют pending. |
| Последний шанс предложения | автоматический | да | нет | Kind `sales_last_chance_due`; `content_code_for` выбирает актуальный шаблон по stage/access. |
| DQS link при reveal дня 4 | автоматический один раз | да | нет | `reveal_course_application`; заранее требует именно linked Telegram account + active Telegram Contact. Kind `dqs_app_link`. |
| DQS resend из ЛК | ручной явный запрос пользователя | да | нет | `POST /api/masterclass/dqs/link-to-telegram`; route, ошибка `telegram_not_linked`, cooldown и название жёстко Telegram-only. |
| Account credential/link reply | автоматический ответ на bot Start по одноразовой ссылке | да | да | Telegram: `masterclass_link.py::consume_masterclass_link`, затем `main.py::process_update`. MAX: `max.py::_consume_account_link`, затем `send_html`. Сейчас эти consumers ещё создают credential/password. |
| Apps menu / app deep link | автоматический ответ на команду/Start/callback | да | да | `app_menu.py::{send_menu,refresh_menu}`. Telegram использует URL/Web App, MAX — `open_app` по `max_app_payload`; DQS в MAX намеренно остаётся обычной браузерной ссылкой. |
| Telegram web-login verification | автоматический ответ на одноразовый login token | да | нет эквивалентного message flow | `web_login.py::consume_web_login` + `main.py::process_update` отправляют code/invalid/used templates. MAX mini-app auth существует отдельно, но это другой контракт, не сообщение с verification code. |
| Maintenance notice | автоматический ответ во время ремонта | да | нет общего MAX-пути | `main.py::_handle_maintenance_contact` всегда вызывает Telegram `client()`. MAX имеет dependency health, но его Start flow не использует этот producer. |
| `/stop` confirmation | автоматический ответ на ручную команду | да | нет | Telegram после остановки runs пытается отправить подтверждение. MAX получает `bot_stopped/dialog_removed`, меняет Contact/runs, но ответ пользователю уже невозможен и не отправляется. |
| MAX intensive assignment links | автоматический ответ на Start payload `iz1..iz3` | нет отдельного TG-аналога | да | `max.py::MAX_ASSIGNMENT_ROUTES`, `_send_max_assignment`; это специально подготовленные MAX-тексты первых трёх заданий. |
| MAX one-shot test chain | ручной/технический | нет | да | `max.py::start_max_one_shot_chain` и callback continuation; состояние в `UserVariable`. |
| Owner payment alert | автоматический внутренний alert владельцу | да | нет | Backend outbox вызывает `POST /internal/owner-payment-alert`; `main.py::owner_payment_alert` использует прямой Telegram `sendMessage` и отдельную идемпотентность `OwnerPaymentAlertDelivery`. Это не клиентский preferred. |
| Cross-messenger bridge | автоматический relay человеческих сообщений | да, как target/source | да, как target/source | `cross_messenger_bridge.py` зеркалит текстовые посты Telegram -> MAX и practice chat в обе стороны, хранит receipt/message/delivery. Это отдельный бот/контур и не должен использовать preferred клиента. |
| Callback/edit/delete | реактивный служебный ответ | да | частично | Telegram callback answer/menu edit и MAX callback answer/edit существуют. Bridge поддерживает text edit в обе стороны и delete только MAX -> Telegram при включённом флаге. Это не новый контент producer, но влияет на паритет. |

Полный список `MasterclassNotification.notification_kind`, который умеет
интерпретировать dispatcher: `messenger_identity`, `messenger_questionnaire`,
`current_diet_questionnaire`, `closing_review_copy`, `dqs_app_link`,
`course_day_unopened_18h`, `course_stalled_72h`, `sales_last_chance_due`, а также
legacy/непроизводимые текущими routes `recipes_followup`. Kinds
`owner_closing_review`, `dqs_support`, `review_followup`, `post_review_day_2/4/7`
явно возвращают `None` в `content_code_for` и сейчас не доставляются этим
dispatcher.

#### Где нужен единый preferred resolver

Фактические точки, где выбор платформы сейчас делается по-разному:

- `finish_questionnaire` — последний linked account;
- `manual_message_by_user` — самый свежий Contact;
- DQS — Telegram hard-code;
- общий Masterclass scheduler — фактически Telegram, кроме двух явно
  target-ориентированных видов;
- sequence engine — платформа уже задана Contact/run и не переключается на
  preferred пользователя;
- broadcasts — только Telegram audience snapshot.

Следовательно, добавление поля preferred само по себе не изменит доставку. Нужен
один shared resolver уровня CRM/messaging: `user_id + delivery_class -> exact
linked active Contact`. Producers должны сохранять выбранные `platform`,
`messenger_account_id` и `platform_user_id` в outbox/recipient snapshot до
внешнего вызова. Иначе смена preferred между enqueue и send даст непредсказуемый
канал и нарушит идемпотентность.

#### Что невозможно отправлять совершенно одинаково

- Telegram channel membership, join request и `createChatInviteLink` не имеют
  эквивалента в текущем MAX client. `MaxClient.subscription_status` намеренно
  возвращает `None`; Telegram subscription gate нельзя механически копировать.
- Telegram `pin_message`/постоянное menu button не реализованы в `MaxClient`.
  Sequence config `pin_after_send` в MAX будет просто пропущен из-за отсутствия
  метода.
- Telegram `video_note` в MAX превращается в обычное video; voice/audio/document
  вообще не поддержаны `MaxClient.send_content`. MAX умеет photo, video и
  video_note-as-video. Telegram `file_id` непереносим в MAX; нужен локальный файл
  или поддержанный remote image.
- Telegram `tg-spoiler` и custom emoji MAX удаляет; HTML дополнительно
  локализуется `_platform_text`. Поэтому байт-в-байт одинаковый body не означает
  одинаковое отображение.
- MAX limit — 4000 UTF-16 units; Telegram text — 4096 символов, а media caption в
  validation ограничен 1024. Единый контент должен проходить более строгий
  platform-aware validator или иметь варианты.
- Telegram Web App button и MAX `open_app` требуют разных payload. DQS сейчас
  специально открывается обычной ссылкой в обоих.
- Telegram callback/update id и MAX callback/webhook receipts различаются;
  подтверждение доставки нельзя нормализовать до простого boolean.
- Cross-messenger bridge поддерживает только текст: media помечается
  `unsupported_media_pending`. Его нельзя считать общим media producer.

### 11. Надёжная state machine browser grant

#### Почему простой consume создаёт лишние sessions

`set_native_session` каждый раз генерирует новый random token и новую строку
`AccountSession`. Если endpoint успел commit, но браузер потерял response/
`Set-Cookie`, повторный клик вызовет ещё одну session. Текущая модель не может
повторно выдать тот же token, потому что хранит только hash. Отмечать grant
`consumed` сразу тоже нельзя: пользователь останется без cookie и без безопасного
retry.

#### Нужные устойчивые сущности

`PaymentBrowserGrant` (новая таблица либо эквивалентная auth-owned запись):

- `id`, `payment_id` unique, `grant_token_hash` unique;
- `status`: `issued | session_issued | closed | expired | revoked`;
- `expires_at`, `first_bound_at`, `last_bound_at`;
- nullable `account_session_id` unique;
- `session_replay_until`, `consumed_at`, `failure_code`;
- audit timestamps, но без email/password/raw token.

`AccountSession` должен иметь nullable unique `source_browser_grant_id` либо grant
должен хранить unique `account_session_id`. Это и row lock обеспечивают ровно одну
session на grant.

Raw browser grant остаётся только в short-lived HttpOnly cookie. Для повторной
выдачи **того же** session cookie без хранения plaintext session token можно
детерминированно получить session token как HMAC server secret от
`grant_raw + payment_id + credential.password_version + domain separator`.
В `AccountSession` по-прежнему хранится только его hash. Raw grant сам является
bearer-секретом, поэтому HMAC не ухудшает его модель, но не позволяет вычислить
session token по утечке одного DB hash.

#### Переходы

```text
checkout created
  -> grant ISSUED (payment pending, raw token только в checkout handoff)

top-level /payments/.../start с raw grant
  -> validate hash/payment/expiry
  -> Set-Cookie edabalans_checkout_grant (HttpOnly, Secure, SameSite=Lax)
  -> record first_bound_at/last_bound_at
  -> redirect/form POST в Robokassa
  -> повтор этого же handoff: переустановить ту же grant cookie, новый Payment не создавать

success page до ResultUrl2
  -> state WAITING_PAYMENT, только polling

ResultUrl2 paid
  -> payment является единственным доказательством оплаты
  -> credential/access готовы

POST claim-session + grant cookie
  -> lock PaymentBrowserGrant
  -> verify grant belongs invoice, not expired/revoked, payment=paid
  -> if ISSUED: derive stable session token, insert AccountSession once,
     save account_session_id, status=SESSION_ISSUED, replay_until
  -> Set-Cookie edabalans_account_session
  -> if SESSION_ISSUED: find the same session, derive the same raw token,
     повторно Set-Cookie; новую строку не создавать

browser confirms /api/account-auth/account with new cookie
  -> optional POST acknowledge grant
  -> CLOSED/consumed_at; удалить short-lived grant cookie

replay_until passed
  -> CLOSED; claim больше не переиздаёт cookie
```

#### Повторный клик и потерянный `Set-Cookie`

- Повтор кнопки success при сохранённой grant cookie всегда возвращает ту же
  `AccountSession`, а не создаёт новую.
- Если первый session `Set-Cookie` потерян, grant cookie остаётся и повторный клик
  переиздаёт детерминированно тот же session token.
- Если потеряна именно grant cookie, сервер не имеет доказательства, что это тот
  же браузер. Состояние должно быть `browser_binding_missing`: не создавать
  session по `InvId`, показать обычный вход данными из email. Без второго
  независимого bearer-секрета безопасно восстановить browser binding невозможно.
- Повтор клика на public checkout до ухода в Robokassa должен использовать уже
  созданный handoff/grant текущей формы, а не молча создавать новый счёт. Для
  reload можно держать только non-secret payment/resume id в sessionStorage;
  восстановление raw grant выполняется лишь через ещё действующий first-party
  handoff, не через публичный invoice endpoint.
- Если session была позже отозвана или password version изменился, старый grant
  не должен создавать новую session: `closed/revoked`, обычный login/reset.
- Два параллельных claim запроса сериализуются `SELECT ... FOR UPDATE`; unique
  `source_browser_grant_id` является вторым барьером.

#### Error states API

| Code | Условие | Session mutation | UI |
|---|---|---|---|
| `waiting_payment` | webhook ещё не подтвердил paid | нет | продолжать bounded polling |
| `browser_binding_missing` | нет/неверная grant cookie | нет | вход по email/password, не просить повторную оплату |
| `grant_expired` | grant просрочен до claim | нет | вход по email/password |
| `grant_mismatch` | grant не относится к invoice | нет + security event | не раскрывать существование аккаунта |
| `credential_pending` | paid, но credential transaction ещё не видна | нет | короткий retry; затем support |
| `session_issued` | первая успешная выдача | ровно одна row | открыть `/lk` |
| `session_reissued` | retry в replay window | нет новой row | открыть `/lk` |
| `grant_closed` | acknowledgement/replay window завершены | нет | обычный login |

### 12. UX/error state machine обязательной привязки

#### Текущие ограничения API

- `GET /api/masterclass/messenger-links/status` возвращает только
  `{platform, linked}`; он не знает attempt/token/error/preferred.
- Telegram generator проверяет формат username, но не доступность бота.
- MAX course `link_account` generator/consumer отсутствует.
- Ошибки token expiry/conflict показываются только внутри бота; сайт их не видит.
- UI может открыть deep link, но Telegram/MAX не дают браузеру надёжный callback.
  Поэтому возвращение фокуса не равно успешной привязке.
- В MAX account-link mutation и отправка confirmation сейчас находятся в одной
  DB-транзакции вокруг внешнего HTTP-вызова. При timeout после фактического приёма
  сообщения результат неопределён; robust `retryable/uncertain/failed` логика есть
  для MAX assignments/app menu, но не для account linking.

#### Серверный источник состояния попытки

Для понятного UI нужен persisted attempt contract (расширенный
`MessengerLinkToken` либо отдельный `MessengerLinkAttempt`):

- public `attempt_id` (не bearer token), `user_id`, `platform`, purpose;
- `status`: `created | awaiting_start | processing | linked | expired | failed`;
- `failure_code`: `platform_unavailable | account_conflict | invalid_token |
  delivery_uncertain | delivery_failed`;
- `expires_at`, `started_at`, `linked_at`, `last_checked_at`;
- token raw никогда не возвращается status endpoint после создания.

Status endpoint требует native session и сверяет `attempt.user_id`. Авторитет
для завершения шага — не attempt status и не delivery confirmation, а наличие
`MessengerAccount(user_id, platform, linked_at)`.

#### UI состояния и переходы

```text
CHECKING
  -> LINKED: хотя бы один MessengerAccount linked
  -> UNLINKED: ни одного linked
  -> CHECK_FAILED: сеть/API недоступны

UNLINKED
  -> GENERATING(platform) по кнопке Telegram/MAX

GENERATING
  -> LINK_READY(deep_link, expires_at, attempt_id)
  -> PLATFORM_UNAVAILABLE (503/health failure)
  -> GENERATION_FAILED (retryable backend/network)

LINK_READY
  -> AWAITING_START после открытия приложения
  -> EXPIRED по server time/status

AWAITING_START
  -> VERIFYING при visibilitychange/focus + немедленный status poll
  -> всё ещё AWAITING_START: бот открыт, но пользователь не нажал Start
  -> PROCESSING: webhook получил token
  -> LINKED: MessengerAccount зафиксирован
  -> ATTEMPT_FAILED(code)
  -> EXPIRED

LINKED
  -> server-side complete messenger course step
  -> если linked один и preferred пуст: назначить его preferred атомарно
  -> показать второй messenger как необязательный
```

Polling должен быть bounded: сразу при возврате, затем короткий backoff, после
30–60 секунд оставить ручную кнопку «Проверить ещё раз». Бесконечный spinner не
доказывает работу бота.

#### Обязательные error states

| Ситуация | Серверный факт | Что показывает UI | Можно ли завершить step |
|---|---|---|---:|
| Token expired до Start | attempt/token `expired`; linked отсутствует | «Ссылка истекла», одна кнопка создать новую для той же платформы, рядом выбрать другую | нет |
| Bot unavailable при генерации | 503/health, token не выдаётся либо attempt failed | «Бот временно недоступен», retry и кнопка другой платформы; support только после повторов | нет |
| Пользователь открыл бот, но не нажал Start | token остаётся `awaiting_start`, linked отсутствует | короткая инструкция «В боте нажмите Start/Начать», кнопки «Открыть снова» и «Проверить» | нет |
| Возврат в браузер без linked state | status `linked=false` | не показывать успех; перейти в `awaiting_start`, затем manual check/regenerate | нет |
| Telegram/MAX account уже связан с другим user | attempt `failed/account_conflict` | не раскрывать чужой email; «Этот аккаунт уже связан с другим кабинетом», support/другой messenger | нет |
| MAX принял link, confirmation response потерян | `MessengerAccount.linked_at` уже commit; delivery `uncertain` отдельно | считать привязку успешной, сообщить «Связь готова; подтверждение в MAX могло не отобразиться» | да |
| MAX HTTP call uncertain до commit linkage | в исправленном flow не должно существовать: link commit предшествует outbox send | UI ждёт authoritative linked status, не текст в MAX | только после linked |
| MAX confirmation окончательно failed | linked есть, delivery failed | step завершён; предложить повторить сервисное подтверждение, не перепривязывать account | да |
| Сеть сайта временно недоступна | attempt неизвестен | «Не удалось проверить», не менять локально completion; retry | нет до server confirmation |
| Одна платформа связана, вторая недоступна | linked есть | обязательное условие выполнено; вторую оставить optional | да |

#### Порядок DB и внешней отправки для MAX

Обязательный link нельзя делать зависимым от доставки красивого подтверждения:

1. webhook lock token/attempt;
2. проверить expiry/conflict;
3. связать `MessengerAccount`, consume token, выставить preferred при необходимости;
4. commit authoritative linkage;
5. создать/обработать отдельную idempotent confirmation delivery;
6. `sent`, `retryable`, `uncertain`, `failed` относятся только к сообщению,
   не откатывают linkage.

Этот паттерн уже частично реализован для MAX assignments через persisted
`TrackingEvent.metadata_json.max_delivery_status`, но account-link branch его не
использует. Для нового flow лучше отдельный outbox/delivery row с unique key
`messenger-link-confirmation:{attempt_id}`.

#### Нужные дополнительные тесты

- expired token отображается сайту и регенерация инвалидирует предыдущий active
  token той же platform;
- открытие deep link без Start не меняет course progress;
- return/focus без linkage не даёт optimistic completion;
- Telegram unavailable и MAX unavailable дают platform-specific retry без
  разблокировки анкеты;
- account conflict не раскрывает чужую личность;
- MAX timeout после commit linkage: status linked=true, confirmation uncertain,
  повтор webhook не перепривязывает и не создаёт дубль;
- MAX connect timeout до внешнего request можно безопасно retry; read timeout
  после request не приводит к автоматическому duplicate confirmation;
- concurrent Telegram/MAX success: оба account link сохраняются, preferred
  выставляется ровно один раз по принятому правилу;
- уже linked user после reload сразу минует attempt UI и серверно завершает step;
- отключение/отвязка после завершения не переписывает исторический step progress,
  если владелец принимает рекомендованную семантику.

#### Ещё два решения владельца

8. **Аварийный обход обязательного шага.** Если оба бота недоступны длительно,
   должен ли существовать только ручной owner override или пользовательский skip?
   Для действительно обязательной привязки безопаснее только audit-logged owner
   override, без публичного skip.
9. **Preferred при почти одновременной привязке двух платформ.** Нужен один
   детерминированный договор: первая успешно commit-нутая платформа становится
   preferred, вторая не меняет её без явного выбора пользователя.

## 13. Точный владелец публичного checkout в T123

Проверка актуального `main` закрыла вопрос о месте изменения checkout:

- Tilda T123 хранит только устойчивый загрузчик
  `<script src="https://edabalans.ru/homepage.js" defer></script>`;
- [`backend/app/static/homepage.js`](../../backend/app/static/homepage.js)
  загружает `/preview/homepage-release-candidate?embed=tilda` и монтирует его в
  страницу без iframe;
- каноническая разметка, форма email и checkout JavaScript принадлежат
  [`backend/app/static/homepage-preview/release-candidate.html`](../../backend/app/static/homepage-preview/release-candidate.html);
- форма сейчас делает cross-origin `POST /api/payments/robokassa/checkout` с
  `credentials: 'omit'`, получает `payment_form` и напрямую отправляет браузер в
  Robokassa;
- [`backend/app/app_routes.py`](../../backend/app/app_routes.py) в режиме
  `embed=tilda` меняет только pricing endpoint и не создаёт отдельную копию
  checkout-кода.

Следствие: browser-bound grant и first-party переход реализуются в серверном
`release-candidate.html`/Robokassa backend. Сам фрагмент T123 менять не нужно,
если URL `/homepage.js` остаётся прежним. Документ `PUBLIC_SITE.md` содержит
устаревшие абзацы про Tilda ST100 и должен быть приведён к фактическому direct
Robokassa-контракту вместе с реализацией.
