# Фактическая логика Telegram-бота

Статус: каноническое описание текущей реализации  
Дата фиксации: 22.08.2026  
Проверенная версия: commit `845acd0`, миграция `20260822_0012`.
Статус выпуска: развёрнуто 22.08.2026 на тестовом боте `@TetrisgfgfgfBot`.
Проверены HTTPS API и `go.похудение-это-есть.рф`, защищённый admin API, три legacy
alias, закрытый порт PostgreSQL, Telegram `getMe` через proxy и восстановление
последнего backup в изолированные базы. Основной `@Fitness_Talks_bot` и Tilda не
переключались.

Этот файл описывает **как Telegram-бот работает сейчас по факту**. Он не описывает
интерфейс админки и не является описанием желаемой будущей логики.

Модуль 1 «Первичный вход и атрибуция лида» подробно описан в
`knowledge-base/modules/telegram/LEAD_ENTRY_OWNER_REQUIREMENTS.md` и
`knowledge-base/modules/telegram/LEAD_ENTRY_TECHNICAL_SPEC.md`. Остальная часть
welcome, покупки, закрепа, подписки и интенсива остаётся в
`plans/TELEGRAM_START_LINKS_SPEC.md` и реализуется следующим самостоятельным
модулем.

## 1. Где находится источник истины

- Исполнение входящих событий и `/start`: `telegram-bot/service/app/main.py`,
  функции `polling_loop()`, `process_update()`, `_upsert_contact()` и
  `_repeat_start_text()`.
- Исполнение шагов цепочки: `telegram-bot/service/app/engine.py`, функции
  `start_run()`, `advance_run()`, `resume_callback()` и `due_runs()`.
- Начальный шаблон двух цепочек: `telegram-bot/service/app/seed.py`.
- Фактическая опубликованная структура после инициализации хранится в PostgreSQL,
  в таблицах `tg_sequences`, `tg_sequence_versions`, `tg_sequence_steps` и
  `tg_sequence_edges`. Поэтому работающий бот исполняет данные БД, а не повторно
  читает шаблон `seed.py` при каждом сообщении.
- Тексты и медиа хранятся в `tg_content_items`; отправляет их Telegram-клиент из
  `telegram-bot/service/app/telegram.py`.
- Описание таблиц Telegram-модуля находится в
  `telegram-bot/service/app/models.py`, схема создаётся миграциями из
  `backend/migrations/versions/`.

## 2. Как бот получает события Telegram

Сейчас используется long polling, а не webhook:

```text
Telegram Bot API
  -> getUpdates через исходящий proxy
  -> polling_loop()
  -> process_update()
```

- `polling_loop()` находится в `telegram-bot/service/app/main.py`.
- HTTP-запросы `deleteWebhook` и `getUpdates` выполняет
  `TelegramClient` из `telegram-bot/service/app/telegram.py`.
- `allowed_updates` включает `message`, `callback_query`, `chat_member` и
  `chat_join_request`.
- Адрес proxy берётся из настройки `telegram_proxy_url`, описанной в
  `telegram-bot/service/app/config.py`.
- Полученный `update_id` записывается в `tg_update_receipts`. Повторный update с
  тем же ID не исполняется второй раз.
- При сетевой ошибке polling ждёт две секунды и повторяет запрос, не подтверждая
  необработанный update.

## 3. Как создаётся ссылка и определяется источник

Одна запись `tg_tracking_links` теперь является правилом: она хранит название,
тип назначения `bot_start/channel_invite`, корневой маршрут либо разрешённое
исключение, состояние и старые совместимые поля `platform/placement/campaign`.

Публичные адреса правила находятся отдельно в `tg_tracking_link_aliases`. Поэтому
новый код и несколько старых LeadTeh UUID могут означать один и тот же источник,
а статистика показывается и суммарно по правилу, и отдельно по каждому адресу.
Код не удаляется и не используется повторно; его можно архивировать или отключить.

Новые короткие коды имеют вид `B` или `C` плюс четыре символа. `B` означает ссылку
на бот, `C` — invite-ссылку канала. Пятый после кода символ `V` распознаётся только
на домене `go.` и выводит предупреждение о VPN. В прямом Telegram payload `V` не
имеет специального значения.

Для bot rule админка выдаёт:

```text
https://t.me/TetrisgfgfgfBot?start=B7K4P
https://go.похудение-это-есть.рф/B7K4P
https://go.похудение-это-есть.рф/B7K4PV
```

Маршруты `GET /go/{token}` и совместимый `GET /r/{token}` реализованы в
`telegram-bot/service/app/main.py`. Они разрешают alias, сохраняют `web_click` в
`tg_tracking_events` и переводят только на настроенный Telegram bot/invite URL.
Произвольный внешний redirect из query не допускается.

Если к `go.` пришли UTM, они сохраняются без догадок. Точные ручные правила
`parameter + normalized value -> existing tag_id` лежат в `tg_utm_tag_rules`.
Для передачи UTM через Telegram создаётся краткоживущая одноразовая запись
`tg_tracking_sessions`; наружу уходит непрозрачный start payload. Неразобранные UTM
вычисляются из сырых событий и не получают отдельную дублирующую таблицу.

Связь правила с существующими CRM-тегами хранится в `tg_tracking_link_tags`.
Новый тег не создаётся при переходе. Администратор отдельно выбирает существующий
тег либо явно подтверждает создание нового. При merged tag функция
`canonical_tag()` из `telegram-bot/service/app/tracking.py` следует к актуальному
`tags.id`.

При `/start` функции `resolve_start_payload()` и `assign_first_touch()`:

1. классифицируют payload как известный, неизвестный, пустой либо истёкшую session;
2. неизвестный код безопасно направляют в обычный корневой `/start`;
3. записывают `start_first`, `start_repeat`, `start_unknown` либо
   `start_expired_session` в `tg_tracking_events`;
4. атомарным признаком первого посещения используют
   `messenger_accounts.main_scenario_seen_at`;
5. только при первом посещении назначают выбранные существующие `user_tags` и
   создают CRM `attribution_events`;
6. повторный `/start` источник и теги не перезаписывает и welcome не перезапускает;
7. `tg_contacts.last_source_token` новой логикой больше не обновляется.

Для канала Telegram client принимает `chat_member` и `chat_join_request`. Событие
с известной уникальной invite-ссылкой сохраняется до будущего `/start` того же
Telegram user ID; первый старт забирает это событие и применяет теги правила.
Создание/revoke invite реализованы, но живой тест требует, чтобы конкретный бот был
администратором канала, и проводится последним.

Три предоставленных legacy UUID добавляются миграцией `0012`: главная ссылка
Пикабу получает существующий тег `Пикабу`; две ссылки конкретных постов получают
теги `Пост - Не с похудения` и `Пост - Скорость похудения`, если такие теги уже
есть. Источник двух последних не угадывается. Остальные UUID без mapping работают
как обычный корневой старт.

## 4. Как определяется пользователь

Функция `_upsert_contact()` в `telegram-bot/service/app/main.py` получает от
Telegram `user` и `chat` и создаёт либо обновляет `tg_contacts`:

- Telegram user ID;
- chat ID;
- username;
- имя и фамилию;
- язык;
- время последней активности;
- статус `active`.

Затем она ищет `messenger_accounts` с `platform='telegram'` и тем же
`platform_user_id`:

- если запись найдена, её общий `user_id` сохраняется в `tg_contacts.user_id`;
- если записи нет, создаются новый `users` и связанный `messenger_accounts`, а
  новый `user_id` сохраняется в `tg_contacts.user_id`.

Канонические CRM-модели описаны в `backend/app/models.py`; минимальные ORM mapping,
которыми Telegram service безопасно обращается к тем же таблицам, находятся в
`telegram-bot/service/app/models.py`. Создание/обновление выполняет
`ensure_crm_identity()` из `telegram-bot/service/app/tracking.py`.

Текущее ограничение: оплата из Tilda ищет человека преимущественно по email в
`backend/app/tilda_service.py`, а Telegram создаёт человека по Telegram ID.
Автоматическое безопасное объединение этих двух записей ещё не завершено. Если
они оказались разными `users.id`, бот может не увидеть покупку этого человека.

## 5. Первый `/start` и повторный `/start`

Маршрут первого запуска хранится в `tg_bot_routes`. Начальное значение создаёт
`_ensure_routes()` в `telegram-bot/service/app/seed.py`:

```text
/start -> prepurchase_masterclass
```

При первом `/start` функция `process_update()` создаёт `tg_sequence_runs` через
`start_run()` и сразу вызывает `advance_run()`.

При любом повторном `/start` новая цепочка не создаётся и текущая цепочка не
переходит на следующий шаг. `_repeat_start_text()` отвечает:

- пока ожидается кнопка — просит нажать старую кнопку «Начать интенсив»;
- во время задержки — сообщает примерное время до следующего сообщения;
- после отправки четвёртого дня (`m09`) — показывает оглавление интенсива;
- в остальных случаях — сообщает, что следующее сообщение придёт по расписанию.

Оглавление и хэштеги закреплены миграцией
`backend/migrations/versions/20260822_0010_intensive_restart_guard.py`.

## 6. Текущая цепочка до покупки

Опубликованная цепочка имеет код `prepurchase_masterclass`. Начальный шаблон
создаёт `seed_defaults()` в `telegram-bot/service/app/seed.py`; фактические шаги,
контент и переходы читаются из PostgreSQL.

Последовательность сейчас такая:

| № сообщения | Действие | Задержка перед ним |
|---:|---|---:|
| 1 | видеокружок-знакомство | сразу |
| 2 | приветствие, описание бота и кнопка «Начать интенсив» | сразу |
| — | ожидание нажатия кнопки | без автоматического продолжения |
| — | заглушка проверки подписки | отключена, всегда пропускает дальше |
| 3 | интенсив, день 1, `#интенсив_день_1` | сразу после кнопки |
| 4 | полезный промежуточный пост | 12 часов |
| 5 | интенсив, день 2, `#интенсив_день_2` | 11 часов, то есть через 23 часа после дня 1 |
| 6 | полезный промежуточный пост | 12 часов |
| 7 | интенсив, день 3, `#интенсив_день_3` | 12 часов, то есть через 24 часа после дня 2 |
| 8 | полезный промежуточный пост | 12 часов |
| 9 | интенсив, день 4, `#интенсив_день_4` | 12 часов, то есть через 24 часа после дня 3 |
| 10 | оглавление четырёх дней | без заданной задержки, на ближайшем проходе scheduler |
| 11 | первая жёсткая продажа | 12 часов |
| 12 | вторая жёсткая продажа | 24 часа |
| 13–20 | польза и мягкие продажи | каждые 24 часа |
| 21–30 | более редкий дожим | каждые 84 часа |

Для каждого сообщения с 3-го по 30-е в `tg_sequence_steps` перед отправкой стоят
отдельные блоки `DELAY` и `CONDITION has_product`. Переходы между блоками хранятся
в `tg_sequence_edges` и исполняются `_edge()`/`_set_next()` из `engine.py`.

Тексты сообщений хранятся в `tg_content_items`; шаг ссылается на текст полем
`tg_sequence_steps.content_item_id`. Начальные шаблоны текстов перечислены в
`_messages()` файла `seed.py`. Часть сообщений 13–16 заменена материалами
LeadTeh импортом из `telegram-bot/service/import_catalog.py`; остальные основные
дни и значительная часть дожима пока являются заготовками.

## 7. Нажатие кнопки «Начать интенсив»

Шаг `WAIT_BUTTON` переводит `tg_sequence_runs.status` в `waiting` и записывает
ожидаемый `callback_data` в `tg_sequence_runs.context`.

Нажатие кнопки приходит как `callback_query`. `process_update()` передаёт его в
`resume_callback()` из `telegram-bot/service/app/engine.py`. Если callback
совпадает, run снова становится `active`, переходит по следующей связи из
`tg_sequence_edges`, и `advance_run()` продолжает цепочку.

## 8. Проверка подписки на канал

В цепочке существует шаг `subscription_placeholder`, созданный в `seed.py` с
настройками:

```text
condition = subscription_check
enabled = false
fail_open_seconds = 600
```

В `advance_run()` файла `engine.py` отключённая проверка возвращает `true` и сразу
пропускает пользователя дальше. Сейчас бот:

- не вызывает Telegram `getChatMember`;
- не знает ID проверяемого канала;
- не делит подписанных и неподписанных;
- не отправляет отдельный пост-приманку;
- не реализует фактическое ожидание десяти минут.

Поля `messenger_accounts.subscription_status` и `subscription_checked_at`
существуют в общей модели `backend/app/models.py`, но эта версия бота их не
заполняет.

## 9. Проверка покупки и переход после покупки

Проверку выполняет `_has_paid_product()` в
`telegram-bot/service/app/engine.py`. Для `tg_contacts.user_id` она делает запрос
к общим таблицам `payments` и `products` и ищет:

```text
payments.payment_status = 'paid'
products.code IN (
  MASTERCLASS_BASIC,
  MASTERCLASS_RECIPES,
  MASTERCLASS_CONSULT
)
```

Модели этих таблиц — `Payment` и `Product` в `backend/app/models.py`. Приём и
нормализация оплат Tilda находятся в `backend/app/tilda_service.py`.

Если покупка не найдена, человек остаётся в цепочке до покупки. Если найдена,
переход из `tg_sequence_edges` направляет его в
`postpurchase_masterclass`.

Сейчас `postpurchase_masterclass` существует только как отключённая draft-
заготовка без опубликованной версии. Поэтому фактический результат найденной
покупки — остановка текущего дожима со статусом `branch_pending`; цепочка после
покупки ещё не запускается.

Дополнительное расхождение: Telegram-движок признаёт только статус оплаты
`paid`, хотя в старых данных CRM могут встречаться подтверждённые покупки со
статусом `confirmed`.

## 10. Как исполняются задержки и шаги

`scheduler_loop()` в `telegram-bot/service/app/main.py` регулярно вызывает
`due_runs()` и `advance_run()` из `engine.py`.

- Текущее состояние человека: `tg_sequence_runs` (`current_step_key`, `status`,
  `next_action_at`, `context`, `time_scale`, ошибка).
- `DELAY` берёт `tg_sequence_steps.delay_seconds`, умножает на
  `tg_sequence_runs.time_scale` и записывает результат в `next_action_at`.
- Обычный режим использует `time_scale=1`.
- Ускоренный тест обычно использует `time_scale=1/720`: 24 часа превращаются
  примерно в 2 минуты, 12 часов — примерно в 1 минуту.
- Тихих часов и часового пояса пользователя сейчас нет: все задержки считаются
  буквально от предыдущего шага.
- `DB_READ` читает условие/переменную; `DB_WRITE` записывает значение в
  `tg_user_variables`; логика находится в `_variable()`, `_write_variable()` и
  `advance_run()` файла `engine.py`.

Движок понимает типы `MESSAGE`, `PHOTO`, `VIDEO`, `VIDEO_NOTE`, `VOICE`, `DELAY`,
`WAIT_BUTTON`, `CONDITION`, `DB_READ`, `DB_WRITE`, `GOTO` и `STOP`.

## 11. Отправка, защита от дублей и ошибки

Перед отправкой контента `advance_run()` создаёт запись в `tg_step_deliveries` с
идемпотентным ключом `<run_id>:<step_key>`.

- Если этот шаг уже имеет статус `sent`, повторная отправка пропускается.
- Telegram message ID сохраняется в `platform_message_id`.
- Ошибка сохраняется в `tg_step_deliveries.error_message`, а run получает статус
  `error` и текст в `tg_sequence_runs.last_error`.
- Для ошибок `blocked by the user` и `chat not found` контакт в `tg_contacts`
  получает статус `blocked`.

Формирование запросов `sendMessage`, `sendPhoto`, `sendVideo`,
`sendVideoNote` и `sendVoice` находится в
`telegram-bot/service/app/telegram.py`. Telegram-разметку из сохранённого текста
готовит `to_telegram_html()` из `telegram-bot/service/app/formatting.py`.

## 12. Разовые и личные сообщения

Разовая рассылка хранится в `tg_broadcasts`, список адресатов и результат каждого
— в `tg_broadcast_recipients`. Отправку выполняют `_deliver_broadcast()` и
`scheduler_loop()` в `telegram-bot/service/app/main.py`. Текущая сегментация
фактически выбирает контакты по статусу, обычно `active`; полноценные сегменты по
покупкам и тегам ещё не реализованы.

Личное исходящее сообщение оператором отправляется функциями
`manual_message()`/`manual_message_by_user()` в `main.py` и записывается в
`tg_manual_messages`. Оно не двигает автоматическую цепочку. Входящие обычные
сообщения пользователя сейчас не сохраняются как переписка и не формируют диалог
в CRM.

## 13. Что пока отсутствует, хотя предусмотрено архитектурой

- реальная проверка подписки на Telegram-канал;
- надёжная связка Telegram-пользователя с покупателем по email;
- опубликованная цепочка после покупки;
- единая атрибуция `ссылка -> пользователь -> покупка -> выручка` в CRM;
- полноценные сегменты рассылок по тегам и покупкам;
- хранение входящей переписки;
- отдельный MAX-адаптер.
- автоматическая синхронизация тегов `Подписан`, `Не подписан`, `Отписался`;
- централизованные стоп-теги до и после покупки;
- редактируемое и закрепляемое приветственное/навигационное сообщение.
- целевой welcome-блок из `plans/TELEGRAM_START_LINKS_SPEC.md`.
- живой тест создания invite-ссылки тестовым ботом в основном канале; механизм и
  mocked test реализованы, но тестовый бот пока не имеет прав администратора;
- интеграция Tilda/сайта с cookie и покупкой из
  `plans/WEBSITE_CLICK_PURCHASE_ATTRIBUTION.md`.

При изменении фактической логики бота этот файл должен обновляться в том же
коммите, что и код/миграция, изменившие поведение.
