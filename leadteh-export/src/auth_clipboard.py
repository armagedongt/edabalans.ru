from __future__ import annotations

import json
import re
import subprocess

from .settings import PROJECT_DIR


def _header(command: str, name: str) -> str | None:
    pattern = rf'''(?ix)["']?{re.escape(name)}["']?\s*=\s*["']([^"'\r\n]+)["']'''
    match = re.search(pattern, command)
    return match.group(1) if match else None


def main() -> None:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    command = result.stdout
    if "app.leadteh.ru/api/bots/245278/schemas" not in command:
        raise SystemExit("Clipboard is not the expected LeadTeh schemas request")
    cookie = _header(command, "cookie")
    if not cookie:
        cookie_pairs = re.findall(
            r'''System\.Net\.Cookie\(["']([^"']+)["']\s*,\s*["']([^"']*)["']''',
            command,
            flags=re.IGNORECASE,
        )
        if cookie_pairs:
            cookie = "; ".join(f"{name}={value}" for name, value in cookie_pairs)
    csrf = _header(command, "x-csrf-token")
    if not cookie or not csrf:
        missing = ", ".join(name for name, value in (("Cookie", cookie), ("X-CSRF-TOKEN", csrf)) if not value)
        raise SystemExit(f"The copied request has no {missing} header")
    body = "\n".join(
        (
            "LEADTEH_BOT_ID=245278",
            f"LEADTEH_COOKIE={json.dumps(cookie)}",
            "LEADTEH_TOKEN=",
            f"LEADTEH_CSRF_TOKEN={json.dumps(csrf)}",
            "LEADTEH_BASE_URL=https://app.leadteh.ru",
            "LEADTEH_DELAY_SECONDS=1",
            "LEADTEH_JITTER_MIN=0.2",
            "LEADTEH_JITTER_MAX=0.8",
            "LEADTEH_TIMEOUT_SECONDS=60",
            "",
        )
    )
    (PROJECT_DIR / ".env").write_text(body, encoding="utf-8", newline="\n")
    print("LeadTeh Cookie and CSRF were stored in local ignored .env (values redacted).")


if __name__ == "__main__":
    main()
