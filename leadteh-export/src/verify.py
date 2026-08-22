from __future__ import annotations

import json

from .database import ArchiveDB
from .export import flatten_tree
from .settings import Settings


CLASSIFICATIONS = {"main_flow", "detached_component", "orphan", "unknown_external_entry"}


def main() -> None:
    settings = Settings.load(require_auth=False)
    data_dir = settings.data_dir
    issues: list[str] = []
    tree = json.loads((data_dir / "raw" / "schemas_tree.json").read_text(encoding="utf-8-sig"))
    scenario_ids = {
        int(item["id"])
        for item in flatten_tree(tree)
        if item.get("type") != "dir" and isinstance(item.get("id"), int)
    }
    raw_ids = {int(path.stem) for path in (data_dir / "raw" / "scenarios").glob("*.json")}
    parsed_ids = {int(path.stem) for path in (data_dir / "parsed" / "scenarios").glob("*.json")}
    if raw_ids != scenario_ids:
        issues.append(f"raw scenario set differs: missing={sorted(scenario_ids-raw_ids)}, extra={sorted(raw_ids-scenario_ids)}")
    if parsed_ids != scenario_ids:
        issues.append(f"parsed scenario set differs: missing={sorted(scenario_ids-parsed_ids)}, extra={sorted(parsed_ids-scenario_ids)}")
    total_blocks = total_edges = total_texts = total_delays = total_conditions = 0
    for scenario_id in sorted(scenario_ids & raw_ids & parsed_ids):
        raw = json.loads((data_dir / "raw" / "scenarios" / f"{scenario_id}.json").read_text(encoding="utf-8-sig"))
        parsed = json.loads((data_dir / "parsed" / "scenarios" / f"{scenario_id}.json").read_text(encoding="utf-8"))
        steps = raw.get("data", {}).get("steps", [])
        blocks = parsed.get("blocks", [])
        if len(steps) != len(blocks):
            issues.append(f"{scenario_id}: raw steps {len(steps)} != parsed blocks {len(blocks)}")
        block_ids = {block.get("block_id") for block in blocks}
        if len(block_ids) != len(blocks):
            issues.append(f"{scenario_id}: duplicate block ids")
        for block in blocks:
            if block.get("classification") not in CLASSIFICATIONS:
                issues.append(f"{scenario_id}/{block.get('block_id')}: invalid classification")
            if block.get("text_raw"):
                total_texts += 1
                relative = block.get("content_file")
                if not relative or not (data_dir / "parsed" / relative).is_file():
                    issues.append(f"{scenario_id}/{block.get('block_id')}: content file missing")
        for edge in parsed.get("edges", []):
            if edge.get("from_block") not in block_ids or edge.get("to_block") not in block_ids:
                issues.append(f"{scenario_id}: edge has missing endpoint")
            total_delays += edge.get("delay_seconds") is not None
            total_conditions += bool(edge.get("conditions"))
        total_blocks += len(blocks)
        total_edges += len(parsed.get("edges", []))
    db = ArchiveDB(data_dir / "leadteh_archive.sqlite")
    try:
        summary = db.summary()
    finally:
        db.close()
    non_parsed = [row["id"] for row in summary["scenario_rows"] if row["status"] != "parsed"]
    if non_parsed:
        issues.append(f"SQLite non-parsed scenarios: {non_parsed}")
    if summary["blocks"] != total_blocks:
        issues.append(f"SQLite blocks {summary['blocks']} != parsed blocks {total_blocks}")
    if summary["texts"] != total_texts:
        issues.append(f"SQLite texts {summary['texts']} != parsed texts {total_texts}")
    print(
        f"Verified: scenarios={len(scenario_ids)}, blocks={total_blocks}, edges={total_edges}, "
        f"texts={total_texts}, delays={total_delays}, conditional_edges={total_conditions}"
    )
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        raise SystemExit(1)
    print("Integrity check passed with 0 issues.")


if __name__ == "__main__":
    main()
