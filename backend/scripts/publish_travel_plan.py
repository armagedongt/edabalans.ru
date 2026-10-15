"""Validate local selected Markdown and upload it without rebuilding production."""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.travel_service import compile_files  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="Локальный выбранный план: plan.md и phases/*.md")
    parser.add_argument("--url", default="https://edabalans.ru")
    parser.add_argument("--check", action="store_true", help="Проверить без сетевой записи")
    parser.add_argument("--export", action="store_true", help="Скачать текущие Markdown в новый локальный каталог")
    args = parser.parse_args()
    if not args.export:
        files = {"plan.md": (args.root / "plan.md").read_text(encoding="utf-8")}
        files.update({"phases/" + p.name: p.read_text(encoding="utf-8") for p in (args.root / "phases").glob("*.md")})
        model = compile_files(files)
    if args.check:
        print(json.dumps({"valid": True, "phases": len(model["phases"])}, ensure_ascii=False))
        return
    if not args.url.startswith("https://"):
        parser.error("Для отправки нужен HTTPS")
    user, password = os.environ.get("TRAVEL_ADMIN_USERNAME"), os.environ.get("TRAVEL_ADMIN_PASSWORD")
    if not user or not password:
        parser.error("Задайте TRAVEL_ADMIN_USERNAME и TRAVEL_ADMIN_PASSWORD вне исходников")
    token = base64.b64encode((user + ":" + password).encode()).decode()
    headers = {"Authorization": "Basic " + token, "Content-Type": "application/json", "X-Travel-Write": "1"}
    base = args.url.rstrip("/") + "/admin/api/travel"
    try:
        if args.export:
            with urlopen(Request(base + "/export", headers=headers), timeout=30) as response:
                data = json.load(response)
            compile_files(data["files"])
            args.root.mkdir(parents=True, exist_ok=False)
            (args.root / "phases").mkdir()
            for name, content in data["files"].items():
                (args.root / name).write_text(content, encoding="utf-8")
            print("Exported revision " + data["revision"])
            return
        with urlopen(Request(base + "/plan", headers=headers), timeout=30) as response:
            revision = json.load(response)["revision"]
        data = json.dumps({"revision": revision, "files": files}, ensure_ascii=False).encode()
        with urlopen(Request(base + "/publish", data=data, headers=headers, method="POST"), timeout=30) as response:
            result = json.load(response)
        print("Published revision " + result["revision"])
    except HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:1000]}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
