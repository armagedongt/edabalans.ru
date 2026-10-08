# Получение доступа через мессенджер

Оригинал письма. ${variable} — переменная; её имя сохраняется.

Переменные по разделам (имена сохраняются):

- `text`: `${expiry_notice}`, `${intro}`, `${messenger_links}`
- `html`: `${buttons}`, `${expiry_notice}`, `${intro}`
- `expiry`: `${deadline}`
- `telegram_link`: `${url}`
- `max_link`: `${url}`
- `telegram_button_html`: `${url}`
- `max_button_html`: `${url}`

## text

```text
${intro}

Чтобы получить логин и пароль от личного кабинета на моём сайте, откройте любой удобный для вас мессенджер:${messenger_links}

${expiry_notice}

Это техническое письмо, я не увижу ответ.
Если ссылка перестала действовать или что-то не получилось, напишите мне в личные сообщения:
Telegram: https://t.me/FitnessSergey
MAX: https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw
```

## html

```html
<!doctype html><html><body style="font:16px/1.55 Arial,sans-serif;color:#17172b">
        <div style="max-width:620px;margin:auto;padding:28px 20px">
        <p>${intro}</p>
        <p>Чтобы получить логин и пароль от личного кабинета на моём сайте, откройте любой удобный для вас мессенджер:</p>
        <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>${buttons}</tr></table>
        <p>${expiry_notice}</p>
        <p style="color:#5b6472;font-size:14px">Это техническое письмо, я не увижу ответ. Если ссылка перестала действовать или что-то не получилось, напишите мне в личные сообщения: <a href="https://t.me/FitnessSergey">Telegram</a> или <a href="https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw">MAX</a>.</p>
        </div></body></html>
```

## expiry

```text
Ссылки действуют до ${deadline} (мск).
```

## telegram_link

```text
Telegram: ${url}
```

## max_link

```text
MAX: ${url}
```

## telegram_button_html

```html
<td style="padding-right:12px"><a href="${url}" style="display:inline-block;padding:12px 20px;border-radius:10px;background:#229ED9;color:#fff;text-decoration:none;font-weight:700">Telegram</a></td>
```

## max_button_html

```html
<td style="padding-right:12px"><a href="${url}" style="display:inline-block;padding:12px 20px;border-radius:10px;background:#2563eb;color:#fff;text-decoration:none;font-weight:700">MAX</a></td>
```
