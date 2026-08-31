"""Publish the validated Masterclass day 3-5 package through the production content API."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publish_course_material import verify_publish_gate


PACKAGE = {
    "06-necessary-restrictions": "day-03-video-01",
    "08-whole-processed": "day-03-article-02",
    "07-reading-labels": "day-03-article-03",
    "13-dqs-system": "day-04-article-01",
    "14-kbjuk": "day-05-article-01",
    "15-plate-rule": "day-05-article-03",
}

REMOTE = (
    "cd /opt/edabalans && docker compose exec -T backend "
    "python /tmp/course-material-api.py"
)


def remote(action: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["ssh", "edabalans-prod", f"{REMOTE} {action}"],
        input=None if payload is None else json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def main() -> int:
    private = Path(tempfile.gettempdir()) / "edabalans-masterclass-finalization-2026-08-31"
    current = remote("list")
    versions = {item["step_id"]: int(item["version"]) for item in current["materials"]}
    materials = []

    for key, step_id in PACKAGE.items():
        draft = private / f"{key}.draft.md"
        pack = private / f"{key}.pack.json"
        report = private / f"{key}.validation-final.json"
        verify_publish_gate(draft, pack, report)
        materials.append(
            {
                "step_id": step_id,
                "expected_version": versions[step_id],
                "content": draft.read_text(encoding="utf-8"),
                "format": "markdown",
            }
        )

    result = remote("batch", {"materials": materials})
    if len(result.get("published") or []) != len(materials):
        raise ValueError("production did not confirm every day 3-5 material")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
