from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

from .client import LeadTehClient
from .database import ArchiveDB
from .parser import normalize_scenario
from .reports import rebuild_indexes, write_content_files, write_scenario_report
from .settings import PROJECT_DIR, Settings, ensure_data_dirs


LOG = logging.getLogger("leadteh_export")


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: object) -> None:
    _atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def flatten_tree(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        roots = payload["data"]
    elif isinstance(payload, list):
        roots = payload
    else:
        raise ValueError("Tree JSON has no data list")
    result: list[dict[str, Any]] = []

    def visit(items: Iterable[object], inherited_parent: int | None = None) -> None:
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            if item.get("parent_id") is None and inherited_parent is not None:
                item["parent_id"] = inherited_parent
            result.append(item)
            children = item.get("items")
            if isinstance(children, list) and children:
                visit(children, item.get("id") if isinstance(item.get("id"), int) else inherited_parent)

    visit(roots)
    return result


def _setup_logging(data_dir: Path, verbose: bool) -> None:
    data_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(data_dir / "logs" / "export.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=[file_handler, stream_handler],
        force=True,
    )


class Exporter:
    def __init__(self, settings: Settings, force: bool = False):
        ensure_data_dirs(settings)
        self.settings = settings
        self.force = force
        self.client = LeadTehClient(settings)
        self.db = ArchiveDB(settings.data_dir / "leadteh_archive.sqlite")

    def close(self) -> None:
        self.db.close()

    def fetch_tree(self) -> list[dict[str, Any]]:
        response = self.client.get_tree()
        _atomic_bytes(self.settings.data_dir / "raw" / "schemas_tree.json", response.content)
        items = flatten_tree(response.json_data)
        for item in items:
            self.db.upsert_tree_item(item)
        folders = sum(item.get("type") == "dir" for item in items)
        scenarios = sum(item.get("type") != "dir" for item in items)
        LOG.info("Tree saved: %s folders, %s scenarios", folders, scenarios)
        return items

    def run(self, mode: str, scenario_id: int | None = None) -> tuple[int, int, int]:
        run_id = self.db.start_run(mode)
        downloaded = parsed_count = errors = 0
        try:
            items = self.fetch_tree()
            scenario_meta = {
                int(item["id"]): item
                for item in items
                if item.get("type") != "dir" and isinstance(item.get("id"), int)
            }
            if scenario_id is not None:
                ids = [scenario_id]
            elif mode == "priority":
                config = json.loads((PROJECT_DIR / "config" / "priority_scenarios.json").read_text(encoding="utf-8"))
                ids = [int(value) for value in config]
            else:
                ids = list(scenario_meta)
            for current_id in ids:
                meta = scenario_meta.get(current_id, {"id": current_id})
                self.db.ensure_scenario(current_id, meta)
                if not self.force and self.db.status(current_id) == "parsed":
                    if mode == "priority":
                        self.db.mark(current_id, "parsed", "priority")
                    LOG.info("Skip %s: already parsed (use --force to download again)", current_id)
                    continue
                raw_path = self.settings.data_dir / "raw" / "scenarios" / f"{current_id}.json"
                try:
                    if self.force or not raw_path.exists() or self.db.status(current_id) != "downloaded":
                        response = self.client.get_scenario(current_id)
                        _atomic_bytes(raw_path, response.content)
                        downloaded += 1
                        self.db.mark(current_id, "downloaded", mode, raw_file=str(raw_path.relative_to(self.settings.data_dir)))
                        LOG.info("Downloaded scenario %s", current_id)
                        self.client.throttle()
                    payload = json.loads(raw_path.read_text(encoding="utf-8-sig"))
                    parsed = normalize_scenario(payload, meta)
                    if len(parsed["blocks"]) != len(payload.get("data", {}).get("steps", [])):
                        raise ValueError("Normalized block count does not match data.steps")
                    write_content_files(parsed, self.settings.data_dir)
                    parsed_path = self.settings.data_dir / "parsed" / "scenarios" / f"{current_id}.json"
                    _atomic_json(parsed_path, parsed)
                    write_scenario_report(parsed, self.settings.data_dir)
                    self.db.store_parsed(parsed, str(parsed_path.relative_to(self.settings.data_dir)))
                    self.db.mark(current_id, "parsed", mode, parsed_file=str(parsed_path.relative_to(self.settings.data_dir)), block_count=len(parsed["blocks"]))
                    parsed_count += 1
                    LOG.info("Parsed scenario %s: %s blocks, %s edges", current_id, len(parsed["blocks"]), len(parsed["edges"]))
                except Exception as exc:  # one bad scenario must not stop the archive
                    errors += 1
                    self.db.mark(current_id, "error", mode, error=str(exc)[:2000])
                    LOG.exception("Scenario %s failed: %s", current_id, exc)
            rebuild_indexes(self.db, self.settings.data_dir)
            return downloaded, parsed_count, errors
        finally:
            self.db.finish_run(run_id, downloaded, parsed_count, errors)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only LeadTeh scenario exporter")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--pass", dest="export_pass", choices=("priority", "archive"))
    selection.add_argument("--scenario", type=int)
    selection.add_argument("--all", action="store_true", help="Export every non-directory tree item")
    parser.add_argument("--force", action="store_true", help="Download even when a parsed archive exists")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.load(require_auth=True)
    _setup_logging(settings.data_dir, args.verbose)
    mode = args.export_pass or ("single" if args.scenario is not None else "archive")
    exporter = Exporter(settings, force=args.force)
    try:
        downloaded, parsed_count, errors = exporter.run(mode, scenario_id=args.scenario)
    finally:
        exporter.close()
    print(f"Done: downloaded={downloaded}, parsed={parsed_count}, errors={errors}")
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
