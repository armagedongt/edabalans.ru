# Доступ с готовым логином и паролем

Оригинал письма. ${variable} — переменная; её имя сохраняется.

Переменные по разделам (имена сохраняются):

- `text`: `${account_url}`, `${email}`, `${intro}`, `${password}`
- `html`: `${account_url_html}`, `${email_html}`, `${intro_html}`, `${password_html}`

## text

```text
${intro}

Доступ в личный кабинет готов.
Логин: ${email}
Пароль: ${password}
Личный кабинет: ${account_url}

Сохраните это письмо: логин и пароль понадобятся на другом устройстве.
Если что-то не получилось, напишите мне в личные сообщения:
Telegram: https://t.me/FitnessSergey
MAX: https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw
```

## html

```html
<!doctype html><html><body style="font:16px/1.55 Arial,sans-serif;color:#17172b">
            <div style="max-width:620px;margin:auto;padding:28px 20px">
            <p>${intro_html}</p><h2>Доступ в личный кабинет готов</h2>
            <p>Логин: <strong>${email_html}</strong><br>Пароль: <strong>${password_html}</strong></p>
            <p><a href="${account_url_html}" style="display:inline-block;padding:12px 20px;border-radius:10px;background:#159ee4;color:#fff;text-decoration:none;font-weight:700">Открыть личный кабинет</a></p>
            <p>Сохраните это письмо: логин и пароль понадобятся на другом устройстве.</p>
            <p style="color:#5b6472;font-size:14px">Если что-то не получилось, напишите мне: <a href="https://t.me/FitnessSergey">Telegram</a> или <a href="https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw">MAX</a>.</p>
            </div></body></html>
```

