"""Compare canonical Masterclass Markdown with production content versions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
COURSE = json.loads(
    (ROOT / "content/masterclass/course/course.json").read_text(encoding="utf-8")
)
REMOTE = (
    "cd /opt/edabalans && docker compose exec -T backend "
    "python /tmp/course-material-api.py"
)
STEP_ASSET_OVERRIDES = {
    "day-01-article-02": "01-food-diary.md",
    "day-01-article-03": "02-weighing.md",
    "day-02-article-01": "03-four-diet-categories.md",
    "day-02-article-02": "04-mediterranean-diet.md",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    items = []
    for day in COURSE["days"]:
        if not 1 <= int(day["number"]) <= 20:
            continue
        for step in day.get("steps", []):
            asset = step.get("contentAsset")
            if step.get("kind") != "article" or not asset:
                continue
            canonical_asset = STEP_ASSET_OVERRIDES.get(
                str(step["id"]), Path(str(asset)).with_suffix(".md").name
            )
            path = ROOT / "content/masterclass/source-current" / canonical_asset
            if not path.is_file():
                continue
            items.append((int(day["number"]), str(step["id"]), canonical_asset, path))

    command = [
        "ssh",
        "edabalans-prod",
        f"{REMOTE} get-many " + " ".join(step_id for _, step_id, _, _ in items),
    ]
    result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    remote = json.loads(result.stdout)["materials"]
    render_payload = {
        "materials": {
            step_id: path.read_text(encoding="utf-8")
            for _, step_id, _, path in items
        }
    }
    render_result = subprocess.run(
        [
            "ssh",
            "edabalans-prod",
            "cd /opt/edabalans && docker compose exec -T backend "
            "python /tmp/masterclass-remote-render-hash.py",
        ],
        input=json.dumps(render_payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if render_result.returncode:
        raise SystemExit(render_result.stderr.strip() or render_result.stdout.strip())
    rendered = json.loads(render_result.stdout)["materials"]
    report = []
    for day, step_id, asset, path in items:
        local_text = path.read_text(encoding="utf-8")
        local_html = str(rendered[step_id]["html"])
        remote_text = str(remote[step_id].get("html") or "")
        report.append(
            {
                "day": day,
                "step_id": step_id,
                "asset": asset,
                "version": remote[step_id].get("version"),
                "matches": local_html == remote_text,
                "local_sha": sha(local_html),
                "production_sha": sha(remote_text),
            }
        )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    (ROOT / "work/masterclass-editorial-finalization-2026-08-31/production-comparison.json").write_text(
        output, encoding="utf-8"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
