from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://api.edabalans.ru"


def credentials(args: argparse.Namespace) -> tuple[str, str]:
    username = args.username or os.getenv("EDABALANS_ADMIN_USERNAME") or os.getenv("ADMIN_USERNAME")
    password = os.getenv("EDABALANS_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        raise SystemExit(
            "Нужны EDABALANS_ADMIN_USERNAME и EDABALANS_ADMIN_PASSWORD "
            "(либо ADMIN_USERNAME и ADMIN_PASSWORD) в окружении"
        )
    return username, password


def api_request(args: argparse.Namespace, method: str, path: str, payload: dict | None = None) -> dict:
    username, password = credentials(args)
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        args.api_url.rstrip("/") + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=args.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API вернул {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"Не удалось обратиться к API: {exc.reason}") from exc


def authoring_path(code: str, suffix: str = "authoring") -> str:
    return f"/bot-api/content/{quote(code, safe='')}/{suffix}"


def render_working_file(item: dict) -> str:
    context = "\n".join(
        f"- {usage.get('module', 'модуль')} · {usage.get('previous', '—')} → {usage.get('step', 'сообщение')} → {usage.get('next', '—')}"
        for usage in item.get("usages", [])
    ) or "- Место использования не найдено"
    return (
        "---\n"
        f"code: {item['code']}\n"
        f"version: {item['content_version']}\n"
        f"title: {item.get('title', '')}\n"
        f"editorial_status: {item['editorial_status']}\n"
        f"media_kind: {item.get('media_kind') or ''}\n"
        "---\n\n"
        "<!-- ЦЕЛЬ СООБЩЕНИЯ\n"
        f"{item['purpose'].strip()}\n"
        "-->\n\n"
        "<!-- ТЗ ПИСАТЕЛЮ\n"
        f"{item['writer_brief'].strip()}\n"
        "-->\n\n"
        "<!-- КОНТЕКСТ В ГРАФЕ\n"
        f"{context}\n"
        "-->\n\n"
        f"{item.get('html_source', item['body_source']).rstrip()}\n"
    )


def parse_working_file(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    code = re.search(r"(?m)^code:\s*(\S+)\s*$", source)
    version = re.search(r"(?m)^version:\s*(\d+)\s*$", source)
    media_kind = re.search(r"(?m)^media_kind:\s*(\S*)\s*$", source)
    purpose = re.search(r"<!-- ЦЕЛЬ СООБЩЕНИЯ\s*\n(.*?)\n-->", source, re.S)
    brief = re.search(r"<!-- ТЗ ПИСАТЕЛЮ\s*\n(.*?)\n-->", source, re.S)
    context = re.search(r"<!-- КОНТЕКСТ В ГРАФЕ\s*\n.*?\n-->", source, re.S)
    body_start = context.end() if context else (brief.end() if brief else -1)
    body = source[body_start:].lstrip("\r\n") if body_start >= 0 else ""
    if not all((code, version, purpose, brief, media_kind)) or (not body.strip() and media_kind.group(1) != "video_note"):
        raise SystemExit("Файл повреждён: нужны code, version, цель, ТЗ и текст (кроме видеокружка)")
    return {
        "code": code.group(1),
        "expected_version": int(version.group(1)),
        "purpose": purpose.group(1).strip(),
        "writer_brief": brief.group(1).strip(),
        "body_source": body.rstrip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Редактирование Telegram-сообщений в Telegram HTML без deploy")
    parser.add_argument("--api-url", default=os.getenv("EDABALANS_API_URL", DEFAULT_API_URL))
    parser.add_argument("--username", default="")
    parser.add_argument("--timeout", type=int, default=30)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Показать аудит рабочих сообщений")
    get_parser = commands.add_parser("get", help="Выгрузить сообщение в Telegram HTML")
    get_parser.add_argument("code")
    get_parser.add_argument("--output", type=Path)
    check_parser = commands.add_parser("check", help="Проверить рабочий Telegram HTML без записи")
    check_parser.add_argument("file", type=Path)
    publish_parser = commands.add_parser("publish", help="Опубликовать и подтвердить рабочий Telegram HTML")
    publish_parser.add_argument("file", type=Path)
    args = parser.parse_args()

    if args.command == "list":
        result = api_request(args, "GET", "/bot-api/content-audit")
        print(json.dumps({"total": result["total"], "counts": result["counts"], "approved_skipped": result["approved_skipped"], "writer_queue": [
            {"code": item["code"], "title": item.get("title"), "editorial_status": item["editorial_status"], "issues": item["issues"]}
            for item in result["writer_queue"]
        ]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "get":
        item = api_request(args, "GET", authoring_path(args.code))
        output = args.output or Path(f"{args.code}.telegram-html.txt")
        output.write_text(render_working_file(item), encoding="utf-8")
        print(str(output.resolve()))
        return 0

    if not args.file.is_file():
        raise SystemExit(f"Файл не найден: {args.file}")
    parsed = parse_working_file(args.file)
    if args.command == "check":
        result = api_request(
            args,
            "POST",
            authoring_path(parsed["code"], "validate"),
            {key: value for key, value in parsed.items() if key != "code"},
        )
    else:
        result = api_request(
            args,
            "PUT",
            authoring_path(parsed["code"], "publish"),
            {**{key: value for key, value in parsed.items() if key != "code"}, "confirm": True},
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
