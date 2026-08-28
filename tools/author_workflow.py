"""Run the private authoring workflow with an explicit profile and review gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from prepare_author_post import build_pack
from search_author_voice import private
from validate_author_draft import file_sha256, validate


def write_json(path: Path, payload: dict) -> None:
    target = private(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(task_path: Path, index_path: Path, output_path: Path) -> dict:
    task = json.loads(private(task_path).read_text(encoding="utf-8"))
    if not str(task.get("work_profile") or "").strip():
        raise ValueError("new workflow tasks require an explicit work_profile")
    pack = build_pack(task_path, index_path)
    write_json(output_path, pack)
    return {"status": "prepared", "output": str(private(output_path)), "work_profile": pack["content_contract"]["work_profile"]}


def create_review(
    pack_path: Path,
    draft_path: Path,
    output_path: Path,
    *,
    reviewer: str,
    check_values: list[str],
) -> dict:
    initial = validate(pack_path, draft_path)
    if initial["status"] == "needs_fix":
        raise ValueError("fix machine validation errors before recording manual review")
    supplied: dict[str, str] = {}
    for value in check_values:
        check_id, separator, notes = value.partition("=")
        if not separator or not check_id.strip() or not notes.strip():
            raise ValueError("each --check must use check_id=meaningful notes")
        if check_id in supplied:
            raise ValueError(f"duplicate review check: {check_id}")
        supplied[check_id] = notes.strip()
    expected = {item["id"] for item in initial["pending_manual_reviews"]}
    if set(supplied) != expected:
        raise ValueError(f"review checks must exactly match: {', '.join(sorted(expected))}")
    pack = json.loads(private(pack_path).read_text(encoding="utf-8"))
    review = {
        "schema_version": "author-review-v1",
        "reviewer": reviewer.strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "pack_sha256": file_sha256(private(pack_path)),
        "draft_sha256": file_sha256(private(draft_path)),
        "fact_sources": pack["content_contract"].get("fact_sources") or [],
        "checks": [
            {"id": item["id"], "result": "pass", "notes": supplied[item["id"]]}
            for item in initial["pending_manual_reviews"]
        ],
    }
    if not review["reviewer"]:
        raise ValueError("reviewer is required")
    write_json(output_path, review)
    return {"status": "reviewed", "output": str(private(output_path)), "checks": sorted(expected)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--task", type=Path, required=True)
    prepare_parser.add_argument("--index", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)

    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--pack", type=Path, required=True)
    validate_parser.add_argument("--draft", type=Path, required=True)
    validate_parser.add_argument("--review", type=Path)
    validate_parser.add_argument("--output", type=Path, required=True)

    review_parser = commands.add_parser("review")
    review_parser.add_argument("--pack", type=Path, required=True)
    review_parser.add_argument("--draft", type=Path, required=True)
    review_parser.add_argument("--reviewer", required=True)
    review_parser.add_argument("--check", action="append", default=[])
    review_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "prepare":
            result = prepare(args.task, args.index, args.output)
            exit_code = 0
        elif args.command == "review":
            result = create_review(
                args.pack, args.draft, args.output,
                reviewer=args.reviewer, check_values=args.check,
            )
            exit_code = 0
        else:
            result = validate(args.pack, args.draft, args.review)
            write_json(args.output, result)
            exit_code = {"pass": 0, "needs_fix": 1, "manual_review_required": 2}[result["status"]]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"status": "error", "detail": str(exc)}
        exit_code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
