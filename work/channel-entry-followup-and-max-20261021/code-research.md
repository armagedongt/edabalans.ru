# Исследование входной группы и отложенной выдачи

Проверено: 21.10.2026. Основа: `73bfc22` (свежий main). Исследование без изменения runtime. MAX Mini App и cookies исследуются отдельными потоками.

## Согласованные границы

- Одна существующая входная группа: навигация → закрепление в Telegram → старый настоящий кружок → текст статьи. В MAX то же исходное видео обычным видео, без обязательного закрепления.
- Ручной Start/запрос статьи выдаёт группу сразу. Подтверждённое Telegram разрешение запускает ожидание 600 секунд; если человек уже запросил/получил вход сам, автоматическая выдача не нужна.
- После входной группы дальнейшая рассылка выключена. Новые 14 дней и прежние продающие цепочки не включать.
- MAX пока ведёт в канал, не на отсутствующий конкретный пост.

## 1. Entry Points

- `telegram-bot/service/app/main.py:process_update`: сообщение `write_access_allowed` сейчас вызывает `_upsert_contact(..., update_status=False)`, записывает `channel_write_allowed`, `server_granted=True`, `automatic_message_sent=False`, commit и выход. Никакого таймера пока нет.
- `main.py:process_update`: `/guide` переводится в `/start`; `/start`, обычные сообщения, запросы приложений и старые callback при временном режиме вызывают `temporary_response`. Это важно: только проверка события `/start` пропустит уже выданный по другому запросу материал.
- `main.py:scheduler_iteration()`: существующий постоянный планировщик; создаёт Telegram/MAX sender, выполняет due runs, broadcast и уведомления. Отдельного `scheduler.py` нет.
- `telegram-bot/service/app/temporary_entry.py:temporary_response(session, contact, sender, receipt_id, platform, public_url) -> dict | None`: общая точка текущей группы для обоих адаптеров. `entry_decision` возвращает `silent`, `normal` либо `article`; `normal` означает покупателя и возврат в обычный покупательский маршрут, не выдачу статьи.
- `temporary_entry.py:send_temporary_entry(...) -> dict`: существующая отправка и журнал группы; содержит персональную ссылку, авторские слоты и промежуточные commit.
- `telegram-bot/service/app/max.py:_temporary_max_update(...)`: bot_started, message_created и callback в личном диалоге; создаёт общую CRM identity и контакт, принимает receipt, разбирает источник на bot_started, затем вызывает ту же `temporary_response`. M-link выдачи/привязки кабинета пропускается в свой маршрут.

## 2. Data Layer

- `telegram-bot/service/app/models.py:SequenceRun`: уже есть `next_action_at`, `status`, JSON `context`, `started_at`, `finished_at`, индекс `(status,next_action_at)`. Подходит для перезапускоустойчивого ожидания без новой таблицы.
- `models.py:SequenceStep` / `SequenceEdge`: kind, delay_seconds, configuration и ветви уже хранят исполняемый порядок. `SequenceVersion` фиксирует опубликованную версию для run.
- `models.py:StepDelivery`: unique `idempotency_key`, статусы pending/sent/error, attempts, payload_snapshot, message_id и sent_at. Это существующая квитанция доставки шага.
- `models.py:TrackingEvent`: unique nullable `deduplication_key`, `processed_at`, metadata JSON, contact/user/messenger IDs и время. Уже содержит реальные входы и разрешения; отдельный runtime-таймер в памяти не нужен.
- `models.py:CrmUserTag`: общий user-level факт навигации/временной группы. Семейство кружка также user-level, не отдельный телефон/мессенджер.

## 3. Similar Features / Shared Utilities

- `telegram-bot/service/app/engine.py:start_run(session, contact_id, sequence_code, time_scale=1.0)`: переиспользует любой active/waiting run той же CRM identity, даже другой sequence. Поэтому слепой вызов для нового follow-up может вернуть чужую активную цепочку; нужен точный selection/creation contract.
- `engine.py:advance_run(...)`: row-lock+refresh run; DELAY вычисляет срок от run.started_at либо успешного StepDelivery.sent_at; due run затем продолжает следующий узел. CONDITION поддерживает факты покупки, подписки и content tag. Действия «вызвать существующую входную группу» пока нет.
- `engine.py:due_runs(session, limit=50)`: active/waiting с `next_action_at <= utcnow()`, общий scheduler уже исполняет их.
- `telegram-bot/service/app/onepage_campaign.py:family_received/record_family`: кружок дедуплицируется ключом `onepage_20261010:family:<user_id>:entry_circle`.
- `onepage_campaign.py:before_direct/record_direct`: запись наблюдений перед текущей отправкой и факта отправленного семейства. Не включают старую рассылку сами по себе.
- `temporary_entry.py:navigation_content(session, platform)`: платформенный опубликованный оригинал navigation из ENTRY_CODES, если готов, иначе общий NAVIGATION_CODE; не копировать текст в новую ветку.

## 4. Точная доставка и идемпотентность

- Текущие слоты: `tpl_onepage_entry_navigation` (либо платформенный оригинал), `tpl_entry_circle`, `tpl_channel_article_entry`. Старое обычное видео `tpl_temporary_intensive_entry` остаётся отдельно.
- Навигация проверяется по общему content-tag `post_onepage_entry_navigation`; legacy успешная история восстанавливает tag. После send фиксируется message_id и tag, затем commit; Telegram pin выполняется сразу после этого. MAX sender не имеет pin_message, поэтому этап пропускается.
- Кружок отправляется только при первом входе и отсутствии family receipt. Под user row lock повторно проверяется family после commit навигации; успешная отправка записывается отдельно и не повторяется при сбое последующего текста.
- `temporary_intensive_entry` receipt имеет `pending`, `sent`, `uncertain`, message IDs частей. Intentional повторный ручной запрос отправляет анонс снова, без навигации/кружка и без кнопки, с repeat-offer. Автоматический таймер не должен превращаться в такой повторный запрос.
- Начальная проверка repeat и создание pending происходят до отправок с промежуточными commit. Навигация и кружок имеют дополнительные защиты; весь анонс не является единым строго exactly-once блоком при параллельном ручном/автоматическом входе. Нужен общий claim/receipt, чтобы timer и Start не стартовали одну группу одновременно.
- Потерянный API-ответ остаётся uncertain и не должен автоматически повторять группу: доставка могла состояться. Нужна видимость ошибки, не скрытый retry всего блока.

## 5. Stop / покупка / назначение доставки

- `temporary_entry.py:entry_decision`: blocked/stopped Contact или blocked CRM user → silent; подтверждённая покупка/доступ мастер-класса → normal; активный merged-safe stop-presale tag → silent. Иначе article.
- `_upsert_contact(update_status=False)` для разрешения сохраняет stopped; само разрешение не является resume. Временный режим также не реактивирует blocked/stopped обычным Start. `/resume` имеет отдельную явную ветку.
- `telegram-bot/service/app/customer_lifecycle.py:stop_runs_for_contact` завершает все active/waiting run указанного контакта и очищает срок. Покупательская сверка останавливает только перечисленные PRESALE_SEQUENCE_CODES: новый код follow-up туда автоматически не попадёт; проверка eligibility перед отправкой всё равно обязательна.
- `main.py:scheduler_iteration` разрешает `preferred_destination` по общему user_id перед proactive sequence delivery и может выбрать другой мессенджер либо завершиться ошибкой неоднозначности. Для reply после разрешения конкретному Telegram-боту требуется явно заданная точная identity, чтобы таймер не ушёл в MAX.
- `telegram-bot/service/app/delivery_registry.py:PROACTIVE_PRODUCERS` требует зарегистрированного producer; `explicit_exact` уже применён для dqs/metabolism app-link. Новая автоматическая входная группа должна иметь явный routing contract, а не обходить registry.
- `temporary_entry.py:pause_marketing` и engine temporary gate удерживают старые MARKETING_CODES. Отдельный entry-followup code не должен запускать welcome/prepurchase цепочки.

## 6. Фактическое MAX media-поведение

- `telegram-bot/service/app/max.py:MaxClient.send_content(user_id, content, configuration)`: media_kind `video_note` при наличии media_path уже загружается как MAX attachment типа `video`; использует тот же локальный исходник `/app/media/welcome-intro-circle.mp4`. Telegram file_id в MAX не используется.
- Такой контент может содержать текст и video attachment в одном API сообщении. Текущая общая группа уже отправляет пустой по телу кружок как отдельное видео, затем отдельный текст статьи — разрешённый владельцем вариант.
- Для реального MAX видео нужен существующий локальный media_path; одного Telegram cached file_id недостаточно. Поддержка local file проверена адаптером до upload.
- MAX временный вход принимает Start сразу и не требует Telegram write-access event. Детали MAX Mini App, подписания и разрешений принадлежат параллельному исследованию.

## 7. Owner preview не должен менять рабочую историю

- `onepage_campaign.py:send_test`: фиксированный личный owner, отдельные `campaign_owner_test` receipts; не вызывает `record_family`, не ставит навигационные content tags, не создаёт sequence run.
- Уже отправленный owner preview (`owner_entry_preview20261021request1`) нужно учитывать только как тест. Нельзя отправлять preview через обычный `temporary_response`: он изменит pool, navigation tag, circle family, персональные ссылки/реальные квитанции, и последующий пользовательский Start станет повторным входом.
- Не стирать историю владельца/сообщения ради проверки. Обычная целевая проверка должна пользоваться отдельными тестовыми receipt и фиктивными тестовыми контактами.

## 8. Existing Tests

- `telegram-bot/service/tests/test_temporary_entry.py`: pytest + SQLite fixture + mocked Sender, seed_defaults. Репрезентативные случаи `test_mini_app_permission_records_contact_without_starting_welcome`, `test_permission_confirmed_by_server_keeps_bridge_source_without_automatic_welcome` — нынешний event-only договор должен быть заменён на no-immediate-send + durable scheduled follow-up.
- Там же `test_article_failure_does_not_repeat_successfully_delivered_circle`, `test_circle_delivered_by_overlapping_entry_is_rechecked_after_navigation`, stop/buyer/merged tags, generic replay и отключение старых chains. Эти защиты сохраняются.
- `telegram-bot/service/tests/test_engine.py`: runtime delay, delivery и retry; `test_max.py`: payload/media/identity; `test_tracking.py`: источник/first-touch. Новые проверки должны покрыть restart scheduler, 599/600s, repeated grant, late manualStart/request, stop/purchase до срока, race manual/timer, lost-response uncertain и owner-preview isolation.

## 9. Integration / boundaries для реализации

- Расписание: `main.py` (write-access hook и scheduler), `channel_entry.py` (тот же источник/metadata), существующие SequenceRun/StepDelivery модели и engine primitives; без migration и нового background engine.
- Общая выдача: `temporary_entry.py` остаётся единственным авторским/поведенческим источником; сделать общий claim и связь реальной группы с scheduled run. Не создавать вторую копию навигации, кружка и анонса.
- Для исполнения графом нужен узел-делегат текущей группы и eligibility-condition, либо перевод нынешней группы целиком в graph. Сейчас общий engine не умеет вызывать эту группу, а простые MESSAGE шаги потеряют pin/family/repeat semantics.
- `graph.py` сейчас строит отображение временной группы из ENTRY_RULES и слотов, но это не исполняемый SequenceRun. Новая задержка/ветки должны быть отражены в фактически исполняемом графе, а не существовать только скрытым if/нарисованной схемой.
- `graph_authoring.py:StepSource.kind` — закрытый Literal существующих типов; новый kind требует обновления валидатора и consumers. Использование config одного существующего action всё равно должно иметь явный задокументированный runtime semantics.
- Документация: `START_WELCOME_ROUTING.md`, `TELEGRAM_BOT_CURRENT_LOGIC.md`, attribution/engine cards, `LINKS_AND_ATTRIBUTION.md` сейчас прямо обещают отсутствие автоотправки после разрешения и требуют синхронного обновления.

## 10. Constraints / External Libraries

- Общие таблицы PostgreSQL/CRM, SQLAlchemy; миграция для 10 минут не нужна. В session factory autoflush отключён: engine уже делает flush перед вычислением delay anchor и lock.
- Telegram confirmation — серверное `write_access_allowed`, не клиентский boolean Mini App; только оно должно разрешать фактическую автоматическую отправку. Отрицательный/закрытый запрос сам таймер не создаёт.
- Внешней библиотеки не добавляется; исследование касается внутренних контрактов, поэтому Context7 не требуется.
- Реальных новых развилок владельца в этой части не выявлено: 10 минут, одна группа, future OFF и MAX channel-root уже подтверждены.
