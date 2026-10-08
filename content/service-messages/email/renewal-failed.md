# Неудачное продление подписки

Оригинал письма. ${variable} — переменная; её имя сохраняется.

Переменные по разделам (имена сохраняются):

- `subject`: без переменных
- `text`: `${amount}`, `${page}`
- `html`: `${amount}`, `${page}`

## subject

```text
Не удалось продлить сопровождение
```

## text

```text
Не получилось списать ${amount} ₽ за следующий месяц сопровождения.

Новых автоматических попыток по этой карте не будет. Пополните карту и оформите подписку заново либо при новой оплате выберите другую банковскую карту:
${page}

Если деньги всё-таки списались, не оплачивайте повторно и напишите мне:
Telegram: https://t.me/FitnessSergey
```

## html

```html
<!doctype html><html><body style="font:16px/1.55 Arial,sans-serif;color:#172c3d">
        <div style="max-width:620px;margin:auto;padding:28px 20px">
        <h1 style="font-size:24px">Не удалось продлить сопровождение</h1>
        <p>Не получилось списать <strong>${amount} ₽</strong> за следующий месяц сопровождения.</p>
        <p>Новых автоматических попыток по этой карте не будет. Пополните карту и оформите подписку заново либо при новой оплате выберите другую банковскую карту.</p>
        <p><a href="${page}" style="display:inline-block;padding:12px 20px;border-radius:10px;background:#fb6b2b;color:#fff;text-decoration:none;font-weight:700">Открыть страницу подписки</a></p>
        <p style="color:#657984;font-size:14px">Если деньги всё-таки списались, не оплачивайте повторно и <a href="https://t.me/FitnessSergey">напишите мне</a>.</p>
        </div></body></html>
```
