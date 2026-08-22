from __future__ import annotations

import argparse
import json
import base64
from pathlib import Path
from urllib.parse import urlparse


SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key"}


def _shape(value: object, depth: int = 0) -> object:
    if depth > 5:
        return "..."
    if isinstance(value, dict):
        return {str(key): _shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return {"length": len(value), "samples": [_shape(item, depth + 1) for item in value[:2]]}
    if isinstance(value, str):
        return f"string({len(value)})"
    return value


def _response_shape(entry: dict[str, object]) -> object | None:
    content = entry.get("response", {}).get("content", {})
    text = content.get("text")
    if not isinstance(text, str) or not text:
        return None
    if content.get("encoding") == "base64":
        text = base64.b64decode(text).decode("utf-8")
    try:
        return _shape(json.loads(text))
    except (ValueError, UnicodeDecodeError):
        return {"non_json_body": f"string({len(text)})"}


def inspect_har(path: Path, bot_id: int = 245278) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    matches: list[dict[str, object]] = []
    prefix = f"/api/bots/{bot_id}"
    for entry in data.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        url = request.get("url", "")
        parsed = urlparse(url)
        if request.get("method") != "GET" or not parsed.path.startswith(prefix):
            continue
        headers = {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in request.get("headers", [])}
        mechanism = []
        if headers.get("cookie") or request.get("cookies"):
            mechanism.append("cookie")
        if headers.get("authorization", "").lower().startswith("bearer "):
            mechanism.append("bearer")
        if headers.get("x-csrf-token"):
            mechanism.append("csrf-header")
        matches.append(
            {
                "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                "query_names": [q.get("name") for q in request.get("queryString", [])],
                "auth": mechanism or ["not detected"],
                "safe_header_names": sorted(k for k in headers if k not in SENSITIVE_HEADERS),
                "response_status": entry.get("response", {}).get("status"),
                "response_mime": entry.get("response", {}).get("content", {}).get("mimeType"),
                "response_body": _response_shape(entry),
            }
        )
    return {"har": path.name, "matching_requests": matches}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect LeadTeh HAR without printing secrets")
    parser.add_argument("har", type=Path)
    parser.add_argument("--bot-id", type=int, default=245278)
    args = parser.parse_args()
    print(json.dumps(inspect_har(args.har, args.bot_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
