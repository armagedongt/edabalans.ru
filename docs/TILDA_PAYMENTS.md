# Tilda / Robokassa → PostgreSQL

Статус: `current`

Production endpoint:

```text
POST https://api.edabalans.ru/integrations/tilda/payments
```

## Новый серверный checkout

После будущей перепубликации главной страницы три тарифа будут получать цену и
состав из единого каталога. Кнопка передаёт backend только стабильный код тарифа;
backend создаёт короткоживущий `offer_checkouts` и помещает в заказ Tilda короткую
ссылку на его ID. Webhook обязан вернуть эту ссылку и email покупателя. Затем сервер сверяет срок,
версию цены, точную сумму и состав ресурсов, сохраняет снимок в `payments` и
выдаёт права.

В корзине покупатель видит единую короткую подпись вида
`Стандартный · №4F7B21D0`. Название берётся из общего каталога продуктов, а не из
страницы или строки цены. Восемь символов номера разрешаются только при одном
точном совпадении среди заказов пользователя и ещё не привязанных публичных
checkout. При нуле или нескольких совпадениях доступ автоматически не выдаётся;
затем сервер по-прежнему проверяет email, точную сумму, срок и состав. Старый
полный формат `EB-<UUID>` навсегда остаётся доступен для уже созданных заказов.

Определять тариф только по сумме запрещено. Сумма является проверкой, но не
идентификатором: у разных акций и пакетов она может совпасть. Все три новых
тарифа ведут в одну общую группу Tilda; различие прав существует только в
PostgreSQL.

До команды Сергея используется `PRICING_CATALOG_ENABLED=false`. В таком состоянии
публичный API цен и создание нового checkout отвечают `503`, а действующая схема
оплаты продолжает работать без изменений.

Исключение для явно согласованного `noindex`-предпросмотра главной —
`POST /api/pricing/site/preview-checkout`. Он создаёт проверочный настоящий заказ
только по активной опубликованной версии цен и только для same-origin запроса,
ограничивает частоту до 10 запросов в минуту с одного сетевого адреса и выдаёт
двухчасовую команду корзины, но не включает каталог для других публичных
потребителей. Маршрут не публикуется в OpenAPI; просроченные неоплаченные checkout
удаляются при следующем создании. `noindex` не является авторизацией, поэтому
endpoint остаётся временной границей preview. После трёх контрольных оплат
preview-исключение заменяется обычным `/api/pricing/site/checkout` и включением
флага.

Короткая вставка будущего серверного блока продаж:

```html
<div data-edabalans-app="masterclass-sales"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

На той же странице остаётся один штатный блок корзины Tilda `ST100`. Стабильные
коды трёх вариантов: `site.masterclass.basic`, `site.masterclass.recipes` и
`site.masterclass.consult`. HTML не хранит суммы и не создаёт заказ самостоятельно.

Tilda sends `application/x-www-form-urlencoded` and authenticates with the
`X-Tilda-Webhook-Token` header. The secret exists only in the production `.env`
and in the Tilda receiver settings.

## Data mapping

The webhook preserves the payment fields previously written to Google Sheets.

| Tilda / legacy Google field | PostgreSQL |
| --- | --- |
| `Name`, `ma_name` | `users.display_name` |
| `Email`, `ma_email` | `user_emails` and `payments.email_at_purchase` |
| `Phone`, `ma_phone` | `user_phones` |
| `paymentsystem` | `payments.payment_system` |
| `orderid` | `payments.external_order_id` |
| `paymentid` | `payments.external_payment_id` |
| `products` | `payments.product_name_raw`, then exact `product_aliases` lookup |
| `price` | `payments.amount` |
| `Currency` / `Валюта` | `payments.currency` |
| `Payment status` / `Статус оплаты` | `payments.payment_status` |
| `referer` | payment landing/referrer and attribution |
| `formid` | `payments.external_form_id` |
| `Form name` / `Название формы` | `payments.form_name_raw` |
| `sent` | `payments.source_event_at` |
| `requestid`, `tranid` | `payments.external_request_id` |
| full request | `payments.raw_payload` |

An exact order or payment ID is idempotent. A paid mapped product grants its
configured `user_accesses`. An unknown product is saved without access for manual
review.

## Действия после подтверждённой оплаты

Источник подтверждения не меняет дальнейший сценарий. После оплаченного webhook
Tilda или подписанного `ResultUrl2` Robokassa backend:

1. сопоставляет покупку с единым `user_id` по нормализованному email;
2. выдаёт права по каталогу продукта;
3. один раз создаёт `account_onboardings` для конкретного `payment_id`;
4. ставит в PostgreSQL-очередь письмо с 24-часовыми ссылками Telegram и MAX;
5. выбранный мессенджер выдаёт логин и восьмизначный буквенно-цифровой пароль.

Страница успешной оплаты не участвует в выдаче доступа. Она сообщает проверить
почту и может открыться раньше, чем будет обработан webhook. Повтор одного webhook
не создаёт второго пользователя, второго права или второго onboarding.

Новый сценарий отделён от действующей продажи флагом
`ACCOUNT_ONBOARDING_ENABLED=false`. Пока он выключен, старые Tilda-оплаты
продолжают работать без писем и новых паролей. Флаг включается только после
настройки SMTP, проверки Telegram/MAX-ссылок и полной контрольной оплаты на новой
странице. Для ссылок выдачи используются отдельные переменные
`ACCOUNT_TELEGRAM_BOT_USERNAME` и `ACCOUNT_MAX_BOT_USERNAME`: тестовый username
бота не должен случайно попасть в письмо покупателю.

Для выбранного SMTP Mailganer/SaM oTPravil используется
`api.samotpravil.ru:1127` с шифрованием сразу при подключении
(`SMTP_USE_SSL=true`, `SMTP_STARTTLS=false`). Домен отправителя должен быть
добавлен к SMTP-ключу и пройти его DNS-проверки до включения onboarding.

## Tilda setup

1. Site settings → Forms → Webhook.
2. Set the endpoint URL above.
3. Send the API key in an HTTP header named `X-Tilda-Webhook-Token`.
4. In every used ST100 cart: Content → select this Webhook receiver.
5. Keep Google Sheets selected during parallel verification.
6. Site settings → Payment systems → Robokassa → enable sending to
   receivers only after successful payment.
7. Republish every page containing a changed ST100 cart.
8. Set the existing Tilda success page in the connected payment system. Its text
   is informational only; it must not contain email, password or claim tokens.
9. On the future replacement landing, do not enable the Tilda Members Area data
   receiver: new buyers use the server account flow after the end-to-end payment
   test passes.

Robokassa `Result URL` remains Tilda's URL and must not be replaced by this
endpoint.
