"""Publish day-level editorial copy without changing course topology or step configuration."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
DESIRED_PATH = ROOT / "content" / "masterclass" / "course" / "course.json"
REMOTE = (
    "cd /opt/edabalans && docker compose exec -T backend "
    "python /tmp/course-structure-api.py"
)
COPY_FIELDS = (
    "title", "tocSummary", "lead", "intro", "afterTitle", "afterText", "afterLead"
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
    desired = json.loads(DESIRED_PATH.read_text(encoding="utf-8"))
    current = remote("get")
    version = int(current["active"]["version"])
    manifest = deepcopy(current["active"]["manifest"])
    desired_days = {int(day["number"]): day for day in desired["days"]}
    changed: list[int] = []

    for day in manifest["days"]:
        number = int(day["number"])
        if number < 3 or number > 20:
            continue
        source = desired_days[number]
        before = json.dumps(day, ensure_ascii=False, sort_keys=True)
        for field in COPY_FIELDS:
            day[field] = source.get(field, "")
        source_checks = {str(item["id"]): item for item in source.get("checks", [])}
        for check in day.get("checks", []):
            wanted = source_checks.get(str(check["id"]))
            if wanted is not None:
                check["text"] = wanted["text"]
        if json.dumps(day, ensure_ascii=False, sort_keys=True) != before:
            changed.append(number)

    result = remote("put", {"expected_version": version, "manifest": manifest})
    print(
        json.dumps(
            {
                "ok": True,
                "previous_version": version,
                "version": result["active"]["version"],
                "changed_days": changed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
