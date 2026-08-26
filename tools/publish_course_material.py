from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://api.edabalans.ru"
DEFAULT_COURSE = "masterclass-21"


def credentials(args: argparse.Namespace) -> tuple[str, str]:
    username = args.username or os.getenv("EDABALANS_ADMIN_USERNAME") or os.getenv("ADMIN_USERNAME")
    password = os.getenv("EDABALANS_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        raise SystemExit(
            "Нужны EDABALANS_ADMIN_USERNAME и EDABALANS_ADMIN_PASSWORD "
            "(либо ADMIN_USERNAME и ADMIN_PASSWORD) в окружении"
        )
    return username, password


def api_request(
    args: argparse.Namespace,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
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


def material_path(args: argparse.Namespace, suffix: str = "") -> str:
    step_id = quote(args.step_id, safe="")
    return f"/admin/api/courses/{quote(args.course, safe='')}/materials/{step_id}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Публикация обычных текстовых материалов курса без Git и deploy"
    )
    parser.add_argument("--api-url", default=os.getenv("EDABALANS_API_URL", DEFAULT_API_URL))
    parser.add_argument("--course", default=DEFAULT_COURSE)
    parser.add_argument("--username", default="")
    parser.add_argument("--timeout", type=int, default=30)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="Показать обычные материалы и их версии")
    get_parser = commands.add_parser("get", help="Получить текущий или исходный текст")
    get_parser.add_argument("step_id")
    versions_parser = commands.add_parser("versions", help="Показать историю материала")
    versions_parser.add_argument("step_id")
    publish_parser = commands.add_parser("publish", help="Сразу опубликовать новую версию")
    publish_parser.add_argument("step_id")
    publish_parser.add_argument("file", type=Path)
    publish_parser.add_argument("--format", choices=("markdown", "html"), default="markdown")
    publish_parser.add_argument("--expected-version", type=int)
    restore_parser = commands.add_parser("restore", help="Вернуть старую редакцию новой версией")
    restore_parser.add_argument("step_id")
    restore_parser.add_argument("version", type=int)
    restore_parser.add_argument("--expected-version", type=int)

    args = parser.parse_args()
    course = quote(args.course, safe="")
    if args.command == "list":
        result = api_request(args, "GET", f"/admin/api/courses/{course}/materials")
    elif args.command == "get":
        result = api_request(args, "GET", material_path(args))
    elif args.command == "versions":
        result = api_request(args, "GET", material_path(args, "/versions"))
    elif args.command == "publish":
        if not args.file.is_file():
            raise SystemExit(f"Файл не найден: {args.file}")
        expected = args.expected_version
        if expected is None:
            expected = int(api_request(args, "GET", material_path(args))["version"])
        result = api_request(
            args,
            "PUT",
            material_path(args),
            {
                "expected_version": expected,
                "content": args.file.read_text(encoding="utf-8"),
                "format": args.format,
            },
        )
    else:
        expected = args.expected_version
        if expected is None:
            expected = int(api_request(args, "GET", material_path(args))["version"])
        result = api_request(
            args,
            "POST",
            material_path(args, f"/versions/{args.version}/restore"),
            {"expected_version": expected},
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
