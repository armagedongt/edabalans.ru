"""Read-only export of author content from production into a private local corpus."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REMOTE = "edabalans-prod"


def ensure_private_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if resolved == repository or repository in resolved.parents:
        raise ValueError("author corpus output must remain outside the Git repository")
    return resolved


def run_query(sql: str) -> list[dict]:
    encoded = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    remote = (
        "cd /opt/edabalans && docker compose exec -T postgres sh -lc "
        f"'echo {encoded} | base64 -d | psql -v ON_ERROR_STOP=1 -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -At'"
    )
    result = subprocess.run(
        ["ssh", REMOTE, remote], text=True, encoding="utf-8", errors="strict",
        capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "production query failed")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> dict:
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")
    return {"file": path.name, "rows": len(rows), "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}


BOT_ROWS = """
SELECT jsonb_build_object(
  'id', id, 'code', code, 'title', title, 'body_source', body_source,
  'source_format', source_format, 'media_kind', media_kind, 'media_path', media_path,
  'labels', labels, 'status', status, 'origin_system', origin_system,
  'origin_scenario_id', origin_scenario_id, 'origin_scenario_name', origin_scenario_name,
  'origin_block_id', origin_block_id, 'created_at', created_at, 'updated_at', updated_at)
FROM tg_content_items
WHERE origin_system = 'leadteh' AND status = 'archive_copy'
ORDER BY origin_scenario_name NULLS LAST, code;
"""

TEMPLATES = BOT_ROWS.replace("origin_system = 'leadteh' AND status = 'archive_copy'", "origin_system = 'template'")

CHANNEL_ROWS = """
SELECT jsonb_build_object(
  'platform', s.platform, 'account_key', s.account_key, 'external_id', i.external_id,
  'canonical_url', i.canonical_url, 'title', i.title, 'author_name', i.author_name,
  'published_at', i.published_at, 'source_tags', i.source_tags, 'ending_text', i.ending_text,
  'ending_kind', i.ending_kind, 'cta_text', i.cta_text, 'cta_url', i.cta_url,
  'text_content', v.text_content, 'blocks', v.blocks)
FROM content_items i
JOIN content_sources s ON s.id = i.source_id
LEFT JOIN content_item_versions v ON v.id = i.latest_version_id
WHERE s.platform IN ('telegram', 'pikabu')
ORDER BY s.platform, i.published_at NULLS LAST, i.external_id;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Export author-only production content over read-only SSH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    output = ensure_private_path(args.output)
    if args.dry_run:
        print("Read-only tables: content_items/content_sources/content_item_versions/tg_content_items")
        print("Excluded: users, contacts, deliveries, broadcasts, sequence runs, telegram_file_id")
        return 0
    output.mkdir(parents=True, exist_ok=True)
    manifests = [
        write_jsonl(output / "bot-constructor.jsonl", run_query(BOT_ROWS)),
        write_jsonl(output / "bot-templates.jsonl", run_query(TEMPLATES)),
        write_jsonl(output / "published-content.jsonl", run_query(CHANNEL_ROWS)),
    ]
    manifest = {"captured_at": datetime.now(timezone.utc).isoformat(), "read_only": True, "files": manifests}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
