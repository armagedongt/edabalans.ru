from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .database import ArchiveDB
from .export import _atomic_bytes, _atomic_json, flatten_tree
from .parser import normalize_scenario
from .reports import rebuild_indexes, write_content_files, write_scenario_report
from .settings import Settings, ensure_data_dirs


def _body(entry: dict[str, object]) -> bytes | None:
    content = entry.get("response", {}).get("content", {})
    text = content.get("text")
    if not isinstance(text, str):
        return None
    if content.get("encoding") == "base64":
        return base64.b64decode(text)
    return text.encode("utf-8")


def read_hars(paths: list[Path], bot_id: int) -> tuple[bytes | None, dict[int, bytes]]:
    tree: bytes | None = None
    scenarios: dict[int, bytes] = {}
    base_path = f"/api/bots/{bot_id}"
    for path in paths:
        har = json.loads(path.read_text(encoding="utf-8-sig"))
        for entry in har.get("log", {}).get("entries", []):
            request = entry.get("request", {})
            response = entry.get("response", {})
            if request.get("method") != "GET" or response.get("status") != 200:
                continue
            parsed = urlparse(request.get("url", ""))
            body = _body(entry)
            if body is None:
                continue
            if parsed.path == f"{base_path}/schemas":
                tree = body
            elif parsed.path == base_path:
                query = parse_qs(parsed.query)
                if query.get("scheme_id"):
                    scenarios[int(query["scheme_id"][0])] = body
    return tree, scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline import of recorded LeadTeh GET responses")
    parser.add_argument("har", nargs="+", type=Path)
    parser.add_argument("--scenario", type=int)
    args = parser.parse_args()
    settings = Settings.load(require_auth=False)
    ensure_data_dirs(settings)
    tree_body, scenario_bodies = read_hars(args.har, settings.bot_id)
    if tree_body is None:
        raise SystemExit("No GET /schemas response body found in supplied HAR files")
    if args.scenario is not None:
        scenario_bodies = {key: value for key, value in scenario_bodies.items() if key == args.scenario}
    if not scenario_bodies:
        raise SystemExit("No matching GET with scheme_id response body found")
    _atomic_bytes(settings.data_dir / "raw" / "schemas_tree.json", tree_body)
    tree_payload = json.loads(tree_body.decode("utf-8-sig"))
    items = flatten_tree(tree_payload)
    metadata = {item["id"]: item for item in items if item.get("type") != "dir" and isinstance(item.get("id"), int)}
    db = ArchiveDB(settings.data_dir / "leadteh_archive.sqlite")
    try:
        for item in items:
            db.upsert_tree_item(item)
        for scenario_id, body in scenario_bodies.items():
            meta = metadata.get(scenario_id, {"id": scenario_id})
            db.ensure_scenario(scenario_id, meta)
            raw_path = settings.data_dir / "raw" / "scenarios" / f"{scenario_id}.json"
            _atomic_bytes(raw_path, body)
            db.mark(scenario_id, "downloaded", "har", raw_file=str(raw_path.relative_to(settings.data_dir)))
            parsed = normalize_scenario(json.loads(body.decode("utf-8-sig")), meta)
            write_content_files(parsed, settings.data_dir)
            parsed_path = settings.data_dir / "parsed" / "scenarios" / f"{scenario_id}.json"
            _atomic_json(parsed_path, parsed)
            write_scenario_report(parsed, settings.data_dir)
            db.store_parsed(parsed, str(parsed_path.relative_to(settings.data_dir)))
            db.mark(scenario_id, "parsed", "har", parsed_file=str(parsed_path.relative_to(settings.data_dir)), block_count=len(parsed["blocks"]))
            print(f"HAR scenario {scenario_id}: {len(parsed['blocks'])} blocks, {len(parsed['edges'])} edges")
        rebuild_indexes(db, settings.data_dir)
    finally:
        db.close()


if __name__ == "__main__":
    main()
