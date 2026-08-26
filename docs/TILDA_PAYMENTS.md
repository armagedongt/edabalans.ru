# Tilda / Robokassa → PostgreSQL

Статус: `current`

Production endpoint:

```text
POST https://api.edabalans.ru/integrations/tilda/payments
```

## Новый серверный checkout (подготовлен, но выключен)

После будущей перепубликации главной страницы три тарифа будут получать цену и
состав из единого каталога. Кнопка передаёт backend только стабильный код тарифа;
backend создаёт короткоживущий `offer_checkouts` и помещает его ID в заказ Tilda.
Webhook обязан вернуть этот ID и email покупателя. Затем сервер сверяет срок,
версию цены, точную сумму и состав ресурсов, сохраняет снимок в `payments` и
выдаёт права.

В корзине покупатель видит короткую подпись вида
`Система рецептов · №4F7B21D0`. Восемь символов номера разрешаются только среди
заказов пользователя с указанным в корзине email; затем сервер по-прежнему
проверяет точную сумму, срок и состав. Старый полный формат `EB-<UUID>` остаётся
доступен для уже созданных заказов.

Определять тариф только по сумме запрещено. Сумма является проверкой, но не
идентификатором: у разных акций и пакетов она может совпасть. Все три новых
тарифа ведут в одну общую группу Tilda; различие прав существует только в
PostgreSQL.

До команды Сергея используется `PRICING_CATALOG_ENABLED=false`. В таком состоянии
публичный API цен и создание нового checkout отвечают `503`, а действующая схема
оплаты продолжает работать без изменений.

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

## Tilda setup

1. Site settings → Forms → Webhook.
2. Set the endpoint URL above.
3. Send the API key in an HTTP header named `X-Tilda-Webhook-Token`.
4. In every used ST100 cart: Content → select this Webhook receiver.
5. Keep Google Sheets selected during parallel verification.
6. Site settings → Payment systems → Robokassa → enable sending to
   receivers only after successful payment.
7. Republish every page containing a changed ST100 cart.

Robokassa `Result URL` remains Tilda's URL and must not be replaced by this
endpoint.
