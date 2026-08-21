# CRM/Core: схема и миграция legacy-данных

Статус: проектирование до создания PostgreSQL-миграции и до импорта персональных
данных.

Дата анализа: 22.08.2026.

## 1. Границы текущего этапа

Сейчас проектируется единый CRM/Core для покупателей и известных пользователей.
Он станет источником истины для Tilda, существующих приложений и позднее для
LeadTeh/Telegram.

На этом этапе не выполняются:

- импорт реальных строк в PostgreSQL;
- переключение production-webhook Tilda;
- перенос DQS и тренировок;
- полноценный Telegram/MAX messaging engine;
- удаление или изменение legacy-таблиц Google.

Google Sheets прочитаны только как источники. Реальные строки, email, телефоны,
Telegram ID, дампы и экспортированные файлы не сохраняются в Git.

## 2. Свойства legacy-источников

### 2.1. Лента оплат

Источник — историческая Google-таблица оплат.

- каждая строка является отдельным финансовым событием;
- внешние `orderid` и `paymentid` используются для идемпотентности;
- в первых строках используются английские поля статуса/валюты/формы, далее —
  русские дубли тех же полей;
- `sent` заполнен во всех строках, но означает время получения/отправки legacy-
  события и не должен безусловно считаться точным временем расчёта платёжной
  системы;
- дополнительные поля Members Area сохраняются с provenance, когда присутствуют.

Эта таблица является главным legacy-источником финансовых фактов. Повторные
покупки одного email сохраняются отдельными платежами и не считаются дублями.

### 2.2. Каталог клиентов после бота

Источник — историческая Google-таблица пользователей после бота.

- большинство строк идентифицируются Telegram ID, email заполнен не всегда;
- один Telegram ID может встречаться повторно с изменёнными атрибутами;
- username может повторяться или меняться и не является надёжным идентификатором;
- используются разные форматы дат;
- колонка `L` полностью пуста;
- значения `К_оплате` и `Тариф_Мастер_класса` смешивают предложения, маршруты
  бота и продуктовые названия. Они не доказывают факт оплаты.

Эта таблица является источником профилей messenger-пользователей, legacy-
состояний и атрибуции, но не самостоятельной финансовой лентой.

### 2.3. Пересечение источников

Часть строк надёжно связывается точным email. Telegram-профили без email нельзя
автоматически связывать с оплатами.

Автоматическое связывание разрешено только по точному нормализованному email или
точному `(platform, platform_user_id)`. Имя и username отдельно для merge не
используются.

## 3. Минимальная PostgreSQL-схема CRM/Core

### `users`

Один человек — один стабильный внутренний `user_id` (UUID).

Поля: `id`, `display_name`, `status`, `first_seen_at`, `created_at`, `updated_at`,
`merged_into_user_id` nullable.

### `user_emails`

Email не является первичным ключом пользователя.

Поля: `id`, `user_id`, `email_original`, `email_normalized`, `is_primary`,
`verification_status`, `source`, `first_seen_at`, `created_at`.

Активный нормализованный email должен быть уникален. Конфликт не приводит к
автоматическому merge, а попадает в очередь ручной проверки.

### `messenger_accounts`

Поля: `id`, `user_id`, `platform`, `platform_user_id`, `username`, `first_name`,
`first_seen_at`, `last_seen_at`, `linked_at`, `source`.

Пара `(platform, platform_user_id)` уникальна. Username хранится как изменяемый
атрибут и не используется как единственное основание для объединения.

### `products`

Стабильный внутренний каталог: `id`, `code`, `name`, `status`, `created_at`.

Начальный набор кодов:

- `MASTERCLASS_BASIC`;
- `MASTERCLASS_RECIPES`;
- `MASTERCLASS_CONSULT`;
- `RECIPES_ADDON`;
- `CONSULTATION`;
- `COACHING`;
- `CALORIES_COURSE` (зарезервирован, пока нет подтверждённых строк оплаты);
- `TRAINING_COURSE` (зарезервирован на будущее).

### `product_aliases`

Связывает изменяемые названия из Tilda с продуктом: `id`, `source`,
`raw_name_exact`, `product_id`, `active_from`, `active_to`, `created_at`.

На старте используются только точные alias, а не нечёткое распознавание текста.
Нераспознанное название блокирует выдачу доступа и попадает на ручную проверку.

### `resources` и `product_access_rules`

`resources` хранит стабильные коды прав, например `ACCESS_MASTERCLASS`,
`ACCESS_RECIPES`, `ACCESS_CONSULTATION`, `ACCESS_COACHING`, позднее `ACCESS_DQS`
и `ACCESS_STRENGTH`.

`product_access_rules` задаёт, какие права выдаёт оплаченный продукт. Приложения
проверяют access, а не разбирают название покупки.

### `payments`

Неизменяемая хронологическая лента финансовых событий.

Поля: `id`, `user_id` nullable, `source`, `external_order_id`,
`external_payment_id`, `external_request_id`, `email_at_purchase`, `product_id`
nullable, `product_name_raw`, `amount`, `currency`, `payment_status`,
`payment_system`, `source_event_at`, `paid_at` nullable, `external_form_id`,
`form_name_raw`, `referer_raw`, `landing_url`, `raw_payload` JSONB,
`import_batch_id`, `created_at`.

Идемпотентность обеспечивается уникальными ключами источника вместе с внешним
payment/order/request ID. Строка со статусом `В процессе` импортируется, но не
выдаёт access.

### `user_accesses`

Поля: `id`, `user_id`, `resource_id`, `granted_at`, `expires_at`, `source`,
`source_payment_id` nullable, `revoked_at`, `created_at`.

Выданный доступ не подменяет историю покупок. Отзыв сохраняется отдельным
состоянием, а исходная покупка не переписывается.

### `attribution_events`

Поля: `id`, `user_id`, `event_type`, `source_raw`, `utm_source`, `utm_medium`,
`utm_campaign`, `utm_content`, `utm_term`, `ref_code`, `landing_url`,
`occurred_at`, `import_batch_id`, `created_at`.

Хранится история, а первый источник вычисляется представлением/запросом.

### `tags`, `user_tags`, `client_notes`

Теги используются для крупных сегментов и ручных операций. Заметки владельца
хранятся отдельно от `users` и имеют автора/время изменения.

### `import_batches`, `legacy_import_records`, `user_merge_events`

Служебные таблицы обеспечивают повторяемый импорт и аудит:

- источник, версия и время импорта;
- номер исходной строки и безопасный хеш строки;
- результат: imported, skipped, duplicate, needs_review, error;
- созданные ID и причина решения;
- журнал merge с `from_user_id`, `to_user_id`, основанием и временем.

Полный сырой legacy payload может храниться только в защищённой PostgreSQL, но
никогда не в Git или логах CI.

## 4. Начальные правила product -> access

| Product code | Выдаваемые права после подтверждённой оплаты |
| --- | --- |
| `MASTERCLASS_BASIC` | `ACCESS_MASTERCLASS` |
| `MASTERCLASS_RECIPES` | `ACCESS_MASTERCLASS`, `ACCESS_RECIPES` |
| `MASTERCLASS_CONSULT` | `ACCESS_MASTERCLASS`, `ACCESS_RECIPES`, `ACCESS_CONSULTATION` |
| `RECIPES_ADDON` | `ACCESS_RECIPES` |
| `CONSULTATION` | `ACCESS_CONSULTATION` |
| `COACHING` | `ACCESS_COACHING` |

Эта техническая трактовка подтверждена владельцем проекта.

Историческое правило подтверждено владельцем: покупки `MASTERCLASS_RECIPES` до
20.08.2026 дополнительно дают `ACCESS_CALORIES`. Начиная с 20.08.2026 этот
доступ новым покупателям по данному продукту не выдаётся.

## 5. Mapping legacy-полей

### 5.1. Лента оплат

| Legacy | Новое поле / действие |
| --- | --- |
| `Name` | кандидат в `users.display_name`, не основание для merge |
| `Email` | `payments.email_at_purchase` и кандидат в `user_emails` |
| `paymentsystem` | `payments.payment_system` |
| `orderid` | `payments.external_order_id` |
| `paymentid` | `payments.external_payment_id` |
| `products` | `payments.product_name_raw`, затем точный `product_aliases` lookup |
| `price` | `payments.amount` |
| `Currency` / `Валюта` | единое `payments.currency` |
| `Payment status` / `Статус оплаты` | единое нормализованное `payment_status` |
| `referer` | `referer_raw`, разбор `landing_url` и UTM в attribution event |
| `formid` | `payments.external_form_id` |
| `Form name` / `Название формы` | `payments.form_name_raw` |
| `sent` | `payments.source_event_at`; не объявлять точным `paid_at` без правила |
| `requestid` | `payments.external_request_id` |
| `ma_name`, `ma_email`, `ma_phone` | кандидаты контактных данных + raw payload; не merge автоматически по телефону/имени |

При конфликте английской и русской пары полей импорт останавливает строку для
проверки. Пустое английское поле можно безопасно дополнить русским и наоборот.

### 5.2. Клиентская таблица

| Legacy | Новое поле / действие |
| --- | --- |
| `Доступ_МК_Качество` | `legacy_import_records.external_record_id`; не выдавать access автоматически |
| `Email` | кандидат в `user_emails`; точный нормализованный email может связать с покупателем |
| `Имя` | `users.display_name` / `messenger_accounts.first_name` |
| `Username` | `messenger_accounts.username`; не основание для merge |
| `Telegram ID` | `messenger_accounts.platform_user_id`, сильный ключ вместе с platform |
| `Источник:` | `attribution_events.source_raw` |
| `К_оплате` | legacy metadata; не создавать payment |
| `Тариф_Мастер_класса` | legacy segment/offer metadata; не создавать payment/access без подтверждения |
| `Телега_или_Макс` | `messenger_accounts.platform`; пустое значение в этом Telegram-источнике трактуется как `telegram`, явное `Макс` — как `max` |
| `Первая активность` | `first_seen_at` / attribution occurrence после нормализации даты |
| `Дата оплаты` | подсказка для сопоставления; не создавать финансовое событие без надёжного ключа |
| пустая колонка `L` | игнорировать |
| `Дата создания` | время legacy-записи, сохранять с provenance |

## 6. Правила идентификации и merge

1. Нормализовать email: trim + lowercase. Не исправлять домены и опечатки
   автоматически.
2. Точное совпадение активного email связывает оплату с существующим пользователем,
   если нет конфликта владельцев email.
3. Точное совпадение `(platform, platform_user_id)` объединяет повторные строки
   messenger-профиля в одного пользователя, сохраняя каждую исходную строку в
   журнале импорта.
4. Username и имя используются только для показа кандидатов ручной проверки.
5. Если строка одновременно содержит email и Telegram ID, она может надёжно
   связать messenger account с покупателем по email.
6. Если ранее были созданы два `user_id`, merge выполняется транзакционно и
   записывается в `user_merge_events`; покупки, доступы, атрибуция, теги и заметки
   переносятся без удаления истории.
7. Строки без email, username и platform ID не создают пользователя и получают
   статус `needs_review`.
8. Никакой access не выдаётся по одному имени тарифа из клиентской таблицы.

## 7. Проверки импорта

До записи персональных данных:

1. заменить скомпрометированный S3-ключ;
2. выполнить новый backup и реальное тестовое восстановление;
3. повторно проверить `.gitignore`, `.env`, `.secrets`, дампы и логи;
4. создать миграцию схемы и применить её вручную после отдельного подтверждения;
5. загрузить seed каталога продуктов, aliases, resources и access rules;
6. выполнить dry-run импортёра без записи и получить отчёт по каждой строке;
7. отдельно подтвердить спорные product aliases и правила доступа;
8. сделать pre-import backup;
9. импортировать непосредственно в production PostgreSQL без промежуточного
   размещения файлов в GitHub;
10. сверить контрольные показатели.

Минимальные контрольные показатели вычисляются во время импорта и сохраняются в
защищённой базе, а не в GitHub: количество строк каждого источника, статусы и
сумма оплат, уникальность внешних ID, количество безопасных связей и записей на
ручную проверку. Обязательно: ноль access для статуса `В процессе`, ноль
нераспознанных оплаченных продуктов перед выдачей access и ноль новых платежей
при повторном запуске импортёра.

## 8. CRM views и первая собственная админка

Во всех административных интерфейсах логином служит email владельца. Короткие
имена пользователей для входа в админки не используются.

После проверенного импорта первая версия админки должна включать:

- список пользователей/лидов;
- список покупателей;
- неизменяемую ленту оплат;
- карточку человека: контакты, messenger accounts, первый источник/UTM,
  покупки, сумма/LTV, доступы, теги и заметки;
- редактирование только безопасных операционных полей: display name, заметки,
  теги и отдельно разрешённые access-операции с аудитом.

NocoDB остаётся техническим просмотрщиком таблиц. Собственная админка является
основным понятным интерфейсом владельца.

## 9. Следующий технический шаг после согласования

После подтверждения этой схемы создаются Alembic-миграция, модели, seed-каталог,
dry-run импортёр и автоматические тесты. Из-за изменения схемы БД production-
релиз выполняется через ручной защищённый этап с backup, а не обычным автодеплоем.
