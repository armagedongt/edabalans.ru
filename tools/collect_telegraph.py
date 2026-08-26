"""Read-only local exporter for a Telegraph account.

The exporter calls only Telegraph's public API methods ``getPageList``,
``getPage`` and ``getViews``.  It never edits, creates or deletes an article.
The access token is read from a user-owned file outside the repository; neither
the token nor the collected texts belong in Git.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.telegra.ph/"
MEDIA_TAGS = {"audio", "embed", "figure", "iframe", "img", "source", "video"}


def ensure_private(path: Path) -> Path:
    """Reject a destination in the repository before writing private material."""
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("Telegraph export must be outside Git")
    return resolved


def read_token(token_file: Path) -> str:
    token = token_file.expanduser().read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{40,128}", token):
        raise ValueError("token file must contain one hexadecimal Telegraph access token")
    return token


def api_call(method: str, params: dict[str, Any], timeout: int) -> Any:
    """Call the API without logging sensitive request parameters."""
    encoded = urlencode({key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()})
    request = Request(
        API_ROOT + method + "?" + encoded,
        headers={"User-Agent": "edabalans-content-catalog/1.0 (read-only)"},
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310: owner-authorized API origin
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegraph {method}: {payload.get('error', 'unknown API error')}")
    return payload["result"]


def list_all_pages(token: str, timeout: int) -> list[dict[str, Any]]:
    """Get every page, including accounts with more than one 200-page slice."""
    pages: list[dict[str, Any]] = []
    offset = 0
    while True:
        result = api_call("getPageList", {"access_token": token, "offset": offset, "limit": 200}, timeout)
        batch = result.get("pages", [])
        pages.extend(batch)
        offset += len(batch)
        if not batch or offset >= int(result.get("total_count", 0)):
            return pages


def node_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    return " ".join(node_text(child) for child in node.get("children", [])).strip()


def media_references(node: Any, trail: tuple[str, ...] = ()) -> list[dict[str, str]]:
    if not isinstance(node, dict):
        return []
    tag = str(node.get("tag", ""))
    attrs = node.get("attrs") or {}
    found: list[dict[str, str]] = []
    if tag in MEDIA_TAGS:
        url = attrs.get("src") or attrs.get("href")
        if isinstance(url, str) and url:
            found.append({"tag": tag, "url": url, "text_context": node_text(node)})
    for child in node.get("children", []):
        found.extend(media_references(child, trail + (tag,)))
    return found


def export_page(token: str, page_ref: dict[str, Any], timeout: int) -> dict[str, Any]:
    path = page_ref["path"]
    article = api_call("getPage", {"path": path, "return_content": True}, timeout)
    try:
        views = api_call("getViews", {"path": path}, timeout).get("views")
    except Exception as error:
        views = None
        article["views_error"] = f"{type(error).__name__}: {error}"
    content = article.get("content", [])
    text = "\n".join(part for part in (node_text(item) for item in content) if part)
    return {
        "source": "telegraph",
        "url": "https://telegra.ph/" + path,
        "path": path,
        "title": article.get("title", ""),
        "author_name": article.get("author_name", ""),
        "author_url": article.get("author_url", ""),
        "description": article.get("description", ""),
        "views": views,
        "content_nodes": content,
        "text_plain": text,
        "media_links": media_references({"tag": "article", "children": content}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", required=True, type=Path, help="Private one-line token file outside Git")
    parser.add_argument("--output", required=True, type=Path, help="Private output folder outside Git")
    parser.add_argument("--pause-seconds", type=float, default=0.15)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--workers", type=int, default=4, help="Concurrent read-only article requests")
    args = parser.parse_args()
    if args.pause_seconds < 0:
        raise ValueError("--pause-seconds cannot be negative")
    if not 1 <= args.workers <= 8:
        raise ValueError("--workers must be between 1 and 8")

    output = ensure_private(args.output)
    token = read_token(args.token_file)
    output.mkdir(parents=True, exist_ok=True)
    page_refs = list_all_pages(token, args.timeout)
    pages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    partial_path = output / "pages.partial.jsonl"
    partial_path.write_text("", encoding="utf-8")
    with partial_path.open("a", encoding="utf-8") as partial:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(export_page, token, ref, args.timeout): ref for ref in page_refs}
            for index, future in enumerate(as_completed(futures), start=1):
                ref = futures[future]
                try:
                    page = future.result()
                    pages.append(page)
                    partial.write(json.dumps(page, ensure_ascii=False) + "\n")
                    partial.flush()
                except Exception as error:
                    errors.append({"path": str(ref.get("path", "")), "error": f"{type(error).__name__}: {error}"})
                if index < len(page_refs):
                    time.sleep(args.pause_seconds)

    pages_path = output / "pages.jsonl"
    pages.sort(key=lambda page: str(page["path"]))
    pages_path.write_text("\n".join(json.dumps(page, ensure_ascii=False) for page in pages) + "\n", encoding="utf-8")
    report = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": "telegraph",
        "listed_pages": len(page_refs),
        "exported_pages": len(pages),
        "errors": errors,
        "workers": args.workers,
        "partial_pages_file": str(partial_path),
        "pages_file": str(pages_path),
        "read_only_methods": ["getPageList", "getPage", "getViews"],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
