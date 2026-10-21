# Исследование кода: финансовый план и факт

Дата: 21.10.2026. Исследовано локальное состояние ветки `codex/finance-actuals-spec` от `origin/main` (`2b6b41e`); production и реальные записи не читались. Документ описывает существующие контракты, не подтверждает полноту исторических данных.

## 1. Точки входа и владельцы

- `docs/README.md`, `docs/modules.toml`, `docs/knowledge-base/PROJECT_IDENTITY.md` — маршрутизация, ownership и действующие адреса. `/finance` и снимки планов принадлежат `products`; commerce, CRM, attribution и marketing остаются владельцами исходных фактов.
- `docs/FINANCE_MODEL.md`, `docs/knowledge-base/modules/catalog/products.md` — нынешний сценарный калькулятор и сохранения. Будущий слой факта уже описан как чтение данных их владельцев, без второй CRM.
- `backend/app/static/eda-finance.html`: `calculate()`, `values()` — весь расчёт сейчас в браузере; факт не запрашивается. Шесть закреплённых карточек, открытая сетка параметров, календаря и переключателя режимов пока нет.
- `backend/app/finance_plans.py`: `PlanIn.validate_parameters`, `list_plans`, `save_plan`, `delete_plan` — `/admin/api/finance/plans`; строгий полный набор параметров, admin session, no-store и write guard. Хранилище — `ManagedDocumentVersion` (`document_type=finance-plan`, schema_version=1), удаление деактивирует снимок.
- `backend/app/marketing_routes.py`: `marketing_overview(..., date_from, date_to, source, campaign, creative, user)` — защищённый read API. Ограничивает период датой 01.12.2025 и двумя годами; это ограничение API, не доказательство начала наблюдения каждого события.
- `backend/app/crm_service.py`: `list_users`, `list_payments`, `user_detail(db, user_id)` — единая карточка и платежный журнал. `docs/ADMIN_ARCHITECTURE.md` требует существующую административную оболочку и единую авторизацию.

## 2. Данные людей и событий

`backend/app/models.py`:

| Таблица / модель | Существующие поля и смысл |
|---|---|
| `users` / `User` | `id`, `first_seen_at`, `created_at`, `data_origin`, `merged_into_user_id`. Первое появление CRM само по себе не доказывает подписку или Start. |
| `messenger_accounts` / `MessengerAccount` | `user_id`, `platform`, `platform_user_id`, `username`, `first_name`, `first_seen_at`, `linked_at`, `subscription_status`, `subscription_checked_at`, `is_deliverable`, `is_preferred`; unique `(platform, platform_user_id)`. |
| `tg_tracking_events` / `TelegramTrackingEvent` | `user_id` nullable, `telegram_user_id` nullable, `event_type`, `metadata_json`, `deduplication_key` unique, `occurred_at`. MAX тоже пишет сюда, мессенджер отмечается в metadata. |
| `attribution_events` / `AttributionEvent` | `user_id`, `event_type`, UTM source/medium/campaign/content/term, `ref_code`, `occurred_at`, raw source. Существуют исторические MAX starts. |
| `tg_tracking_links`, `tg_tracking_link_aliases`, `tg_tracking_sessions` | Каталог platform/placement/campaign и snapshot query/journey; одноразовые session-token и наблюдаемые клики не являются людьми/подписками. |
| `user_merge_events` / `UserMergeEvent` | Журнал `from_user_id`, `to_user_id`, основания и времени. Существование модели не означает наличие UI очереди финансовых дублей. |

### Telegram подписчик без бота

- `telegram-bot/service/app/main.py`, обработчик webhook: отдельная ветка `chat_member` сверяет настроенный основной канал; вызывает `server_observation(... kind="channel_membership", details={subscribed, joined})`. `chat_join_request` — отдельное событие заявки, не подтверждённая подписка.
- `telegram-bot/service/app/channel_entry.py`: `server_observation(session, *, telegram_id, kind, key, contact=None, details=None)` записывает событие даже без CRM account; `user_id` тогда пустой, platform ID остаётся. При наличии account обновляет текущий subscription_status. Сам channel-only callback новую CRM-карточку не создаёт.
- `backend/app/channel_entry_service.py`: `record_observation(...)` сохраняет подписанное открытие Mini App и результат разрешения; открытие/разрешение не приравнивается к запуску бота. `channel_entry_analytics.enrich_visits(...)` различает channel-only/bot-only и порядок наблюдений.
- `telegram-bot/service/app/tracking.py`: `ensure_crm_identity(session, contact, telegram)` связывает Telegram identity с одним CRM user; обработка tracking пишет first/repeat. Одинаковый человек в канале и боте объединяется по platform ID, а не суммированием двух счётчиков.

### MAX и межмессенджерное объединение

- `telegram-bot/service/app/max.py`: `_ensure_identity(session, user)` создаёт/находит CRM account `(max, user_id)`; `_consume_account_link(...)` использует подтверждённый link-account flow; `_assign_first_touch(...)` пишет tracking. MAX client `subscription_status` явно возвращает `None`: полного наблюдения фактических подписок MAX-канала этим путём нет.
- `docs/CRM_CORE_DESIGN.md` запрещает автоматическое объединение по имени/username; это кандидаты ручной проверки. Подтверждённая привязка TG и MAX к одному `user_id` уже поддерживается. Одинаковый числовой ID в разных платформах не является совпадением человека.
- `backend/app/marketing_service.py`: `_canonical_user_map(users)` проходит merge-цепочку; `_identity(event, telegram_user_map, canonical_user_map)` объединяет связанные события. Для сирот Telegram используется platform ID. Новая финансовая очередь кандидатов/исключений и явное хранение приобретённых искусственных подписчиков в исследованных моделях/сервисах отсутствуют.

## 3. Оплаты, тарифы, подписки

- `backend/app/models.py`: `Payment` / `payments` хранит одну операцию: user/product, source и внешние ID (уникальные пары source/order и source/payment), amount/currency, payment_status, paid_at/source_event_at, `amount_is_estimated`, `paid_at_is_estimated`, immutable `pricing_version_id`/`price_entry_code`, raw_payload. Отдельной нормализованной таблицы товарных строк с распределением суммы заказа нет; `OfferCheckout.items` — состав ресурсов, не сумма каждой позиции.
- `backend/app/robokassa_service.py`: checkout сохраняет тариф и snapshot суммы, подтверждение переводит в `paid`, тест — в `test_paid`. В raw_payload сохраняются `trusted_source_snapshot`, `personal_source_snapshot`, `observed_browser` при наличии подтверждённого контекста. Индивидуальная свободная оплата не даёт однозначной продуктовой категории автоматически.
- `backend/app/tilda_service.py`, `backend/app/importers/manual_payments.py`, `backend/app/importers/legacy.py`, `backend/app/importers/leadteh.py` — альтернативные источники истории. `docs/CRM_DATA_MODEL.md` отделяет подтверждённые суммы от реконструированных; накопленная сумма LeadTeh — сверка, не дополнительная оплата. Наличие импортированной операции не доказывает точную дату/тариф/сумму.
- `backend/app/crm_service.py`: `CONFIRMED_PAYMENT_STATUSES=(paid, confirmed)`. `user_detail` считает `ltv_rub` по известным RUB amount без estimated, отдельно estimated_ltv_rub и total_ltv_rub. Это накопленная выручка человека, не чистый LTV после налогов/рекламы/труда и не прогноз на 12 месяцев.
- `backend/app/robokassa_subscription_service.py`: `create_subscription_payment`, `apply_confirmed_subscription_payment`, `cancel_subscription`, `add_calendar_month`. Есть серверное сопровождение `subscription.coaching.monthly`, отдельные дочерние платежи и текущий оплаченный период.
- `RecurringSubscription` хранит status/current_period_start/current_period_end, successful_payments, next_charge_at, cancelled_at; при продлении текущие границы меняются. `UserAccess` хранит granted/expires/revoked/paused и source_payment_id. Ни текущий доступ, ни отмена будущих списаний не равны полной истории реально оказанного сопровождения и отработанных консультаций. Отдельного журнала сессий/фактических трудозатрат нет.
- Отдельной модели refund/partial-refund с amount/date/payment FK в `backend/app/models.py` и обработчиков возврата в исследованном платёжном коде не обнаружено. `refund` tags — исторические признаки, не денежные операции. Для net revenue и net LTV текущего журнала недостаточно.
- Клуб есть в сценарной формуле, но общего фактического club lifecycle/периодов членства в исследованных моделях нет. Нулевую активность клуба нельзя автоматически вывести из отсутствия подключённого источника.

## 4. Источник, органика, рекламный расход

- `backend/app/marketing_service.py`: `_attribution_values` берёт UTM либо каталог ссылки. `_normalize_source` узнаёт Пикабу, Яндекс, TG/MAX; само название площадки не кодирует платный/органический тип размещения. Отдельного универсального признака acquisition paid/organic у tracking link нет; нужен контракт по источнику/размещению, неизвестный источник уже существует как «Не определён».
- `backend/app/browser_journey_service.py`: уже существует first-party `edabalans_visitor`, `RETENTION=365 days`, подписанный/зашифрованный контекст, `state_row`, `_backfill`, `snapshot_for_context`, `observed_accounts`. Идентифицированные browser events могут связываться с тем же user_id. Это частичный реализованный контур, не доказательство всех исторических переходов и оплат. Карточка `marketing.analytics.md` ещё описывает browser→purchase как отложенную задачу; это расхождение документа с runtime, которое нельзя переносить в новое ТЗ как отсутствие всей интеграции.
- `backend/app/marketing_daily_report.py`: `_direct_report(settings, campaign_ids, start, end)` уже читает Direct `Date/CampaignId/AdGroupId/AdId/Device/Impressions/Clicks/Sessions/Cost`, с VAT и скидками; `_summarize_direct` считает cost_rub. `build_daily_report` работает с настроенными campaign IDs, сохраняет daily/comparison/cumulative в `MarketingDailyReport.payload_json` (schema_version3). Накопительный итог ограничен baseline/365 днями; складывание cumulative разных суток дублирует расход.
- `MarketingDailyReport` имеет report_date unique, period_start/end, generated_at, payload_json, статус доставки. Это snapshot отчёта, не универсальный расходный ledger. Общего ручного журнала advertising/opex с датой, категорией, суммой, source, корректировками и защитой от дубля API расхода в коде нет.
- Наличие Direct-клиента не подтверждает настроенный токен, полноту выбранных кампаний, доступность каждого исторического дня или расходы Пикабу и остальных площадок. Секреты/production в исследовании не проверялись.

## 5. Календарь и когортные расчёты

- `_period_bounds(date_from, date_to)` в `marketing_service.py` уже переводит полуинтервал московских календарных суток в UTC: `[начало дня, начало дня после to)`. Этот контракт исключает ошибки 23:59:59 и подходит месяцу `[1-е 00:00, 1-е следующего месяца 00:00)`.
- Существующий marketing_dashboard выбирает события в периоде и строит когорту от Start в периоде; повторный Start наследует первый известный источник начиная с 01.12.2025. Он не считает общий приток channel+bot людей и полное окно оплат за 12 месяцев после каждого first entry. Запрос платежей только в месяце старта занизит позднюю конверсию.
- Календарная выручка по paid_at и cohort conversion по дате первого появления — разные выборки. Деление покупателей месяца на новых лидов этого же месяца не даёт когортную конверсию. Для октября 2026 ещё нельзя наблюдать итог следующих 11 месяцев; неполное окно не нулевая конверсия.
- После исследования пользователь отменил верхнюю границу12месяцев: первые30дней и все последующие покупки без верхней границы срока. Первое появление — минимум входа в канал/бот независимо от порядка. В коде этих окон нет. Для суммы двух процентов общая база должна совпадать и один первый покупатель не должен попадать в оба окна. Поздняя конверсия наблюдаемая на дату, не законченный годовой результат.
- Текущий калькулятор вводит `paid` и `organic` как спрос покупателей; `paidLeads=paid/(conversion/100)`, `ads=paidLeads*cpl`. Ввод притока лидов вместо покупателей — изменение направления модели, а не только новый output. `digitalRate`, `consultRate`, `supportRate`, `clubRate` тоже отдельные конверсии со своими знаменателями; фраза «везде два окна» требует определить охватываемые переходы.
- Строгий `finance_plans.PARAMETERS` не принимает новые ключи; при разделении conversion понадобятся версия/совместимость ранее сохранённых планов. Старую единую величину нельзя без основания объявить значением первого30-дневного окна.

## 6. Тесты и переиспользуемые шаблоны

- `backend/tests/test_eda_finance.py`: pytest + FastAPI TestClient; admin gate, roundtrip/soft-delete, legacy idempotence, origin и полный набор параметров. `test_plan_api_rejects_anonymous_cross_origin_and_incomplete_data(plans_client)` — существующий boundary contract.
- `backend/tests/test_marketing_analytics.py`: SQLite fixtures, синтетические события; cross-MAX/TG first-source, merge, Moscow boundary, неизвестный источник, неприсоединённый stage vs0, limit warning. Пример: `test_merged_crm_users_share_one_row_and_canonical_name()`.
- `backend/tests/test_channel_entry.py`: signed initData, subscriber-only observation, order, заявки vs подписка, identity namespaces. `test_max_and_telegram_entries_with_same_numeric_id_remain_distinct(entry)` защищает от ложной дедупликации.
- `backend/tests/test_browser_journey.py`, `backend/tests/browser/browser-journey.e2e.mjs` — существующий контур browser/source; `test_robokassa_payments.py`, `test_tilda_payments.py`, `test_manual_payments.py` — платёжные подтверждения/дедупликация/история; `test_crm_auth.py` — CRM права и исторический неопределённый тариф. Исследование не запускало тесты и не утверждает их нынешний результат.
- Переиспользуемые функции: `require_admin`, `get_db`, `write_guard`, `document_hash`, canonical user resolution, московские границы, immutable checkout snapshot. Финансовой aggregation функции/когортных tests30/365 пока нет.

## 7. Ограничения, инфраструктура и пробелы историчности

- `backend/requirements.txt`: FastAPI0.141.1, SQLAlchemy2.0.52, Alembic1.19.1, psycopg3.3.4; PostgreSQL общий у backend и bot read models. Новые persisted accounting/exception сущности затронут миграции и ownership, не только HTML.
- Новых внешних библиотек исследование не выбирает; Context7 для новой API-интеграции не требуется. Указаны существующие вызовы Direct; внешняя реализуемость полного MAX subscriber feed здесь не проверена.
- Размеры выборок marketing защищены EVENT_LIMIT и раскрывают усечение. Финансовый all-time не должен молча наследовать лимит видимой таблицы или двухлетний предел UI/API.
- Точная полнота с сентября/октября не устанавливается наличием полей в схеме. Нужна отдельная агрегатная проверка: диапазоны/количество событий каждого типа, missing user_id/product/price/amount/paid_at, estimated/test операции, пробелы Direct, возможность восстановить first membership. Импортированные даты создания не заменяют даты реального входа.
- Ненаблюдавшиеся прошлые подписчики и отписавшиеся люди не восстанавливаются из текущего subscription_status. У MAX каналов пока нельзя обещать точный полный union. Текущие Telegram callback зависят от внешних разрешений/доставки update; код обработчика не доказывает historical completeness.
- Имена/username подходят для очереди подозрений, не идентификации; автоматическое вычитание совпадений исказит denominator. Купленные подписчики требуют отдельного аудируемого исключения/корректировки; число «купил N» само по себе не идентифицирует N конкретных аккаунтов и может дать лишь агрегатную корректировку с иной точностью. Покупки/контакты при этом не удаляются.
- Недоступно без новых данных: net revenue после возвратов, фактическая сумма налогов/эквайринга, ручные расходы, полный журнал оказанного сопровождения/консультаций, полный MAX channel-only приток. Их нельзя выдавать как0 или подсчитывать из сценарных ставок под подписью «факт».
