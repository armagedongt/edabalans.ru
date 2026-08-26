"""Capture a correction chain from Codex session messages into private memory."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from record_author_correction import private, record_payload


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def parse_lines(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def extract_messages(session_path: Path, wanted: set[int]) -> dict[int, str]:
    found: dict[int, str] = {}
    with session_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line_number not in wanted:
                continue
            item = json.loads(line)
            payload = item.get("payload") or {}
            if item.get("type") != "response_item" or payload.get("type") != "message":
                raise ValueError(f"session line {line_number} is not a message")
            found[line_number] = "\n".join(
                str(block.get("text") or "")
                for block in payload.get("content") or []
                if block.get("text") is not None
            ).strip()
    missing = sorted(wanted - found.keys())
    if missing:
        raise ValueError(f"session messages not found: {missing}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--request-line", type=int, required=True)
    parser.add_argument("--assistant-lines", required=True)
    parser.add_argument("--feedback-lines", required=True)
    parser.add_argument("--owner-revision-line", type=int, required=True)
    parser.add_argument("--owner-final", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    args = parser.parse_args()

    assistant_lines = parse_lines(args.assistant_lines)
    feedback_lines = parse_lines(args.feedback_lines)
    wanted = {args.request_line, args.owner_revision_line, *assistant_lines, *feedback_lines}
    messages = extract_messages(private(args.session), wanted)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    payload = {
        **metadata,
        "request": messages[args.request_line],
        "assistant_draft": messages[assistant_lines[0]],
        "assistant_versions": [messages[line] for line in assistant_lines[1:]],
        "owner_feedback": messages[feedback_lines[0]],
        "owner_feedback_rounds": [messages[line] for line in feedback_lines[1:]],
        "owner_revision": messages[args.owner_revision_line],
        "owner_final": private(args.owner_final).read_text(encoding="utf-8"),
    }
    result = record_payload(payload, args.memory, args.index)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

