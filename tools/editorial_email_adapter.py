"""Discover the real service email originals for the shared Git vault adapter."""
from __future__ import annotations


TITLES = {
    "tilda-transfer": "Перенос личного кабинета",
    "account-onboarding": "Темы и вступления писем с доступом",
    "account-direct": "Доступ с логином и паролем",
    "account-messenger": "Получение доступа через мессенджер",
    "login-code": "Код входа в приложение",
    "renewal-failed": "Неудачное продление подписки",
}


def discover(api):
    rows = api.request("GET", "/admin/api/editorial/service-emails")["templates"]
    result = {}
    for row in rows:
        code = row["code"]
        if code not in TITLES or row["path"] != f"content/service-messages/email/{code}.md":
            raise ValueError("API вернул неизвестный оригинал письма")
        result["email:" + code] = {
            "kind": "git", "group": "Письма", "title": TITLES[code],
            "path": f"Письма/{code}.md", "source_path": row["path"],
            "api_path": f"/admin/api/editorial/service-emails/{code}",
            "sections": row["sections"],
        }
    return result
