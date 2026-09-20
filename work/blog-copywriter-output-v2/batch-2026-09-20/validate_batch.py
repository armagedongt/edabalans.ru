from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
issues: list[dict[str, str]] = []


def issue(slug: str, check: str, detail: str) -> None:
    issues.append({"slug": slug, "check": check, "detail": detail})


for item in manifest["items"]:
    slug = item["slug"]
    path = ROOT / item["file"]
    text = path.read_text(encoding="utf-8")
    body = text.split("---", 2)[-1]
    if re.search(r"(?m)^# ", body):
        issue(slug, "no_h1_in_body", "H1 found in body")
    if re.search(r"<\s*(script|iframe|style|div|span)\b", body, re.I):
        issue(slug, "no_raw_html", "raw HTML/script found")
    if re.search(r"!\[[^]]*]\(https?://", body, re.I):
        issue(slug, "no_hotlinked_images", "external image reference found")
    for ref in re.findall(r"!\[[^]]*]\((/media/[^)]+)\)", body):
        local = ROOT / ref.removeprefix("/")
        if not local.exists():
            issue(slug, "media_exists", ref)
    for forbidden in (
        "пишите в комментар",
        "добро пожаловать в комментарии",
        "можете подписаться",
        "мой телеграм-канал",
        "erid",
    ):
        if forbidden in body.casefold():
            issue(slug, "platform_tail", forbidden)
    validation = json.loads((ROOT / "machine" / f"{slug}.validation.json").read_text(encoding="utf-8"))
    expected = "manual_review_required" if slug == "hochesh-hudet-esh-kartoshku" else "pass"
    if validation["status"] != expected:
        issue(slug, "writer_validation", f'{validation["status"]} != {expected}')
    related = item.get("related_candidates") or []
    if len(related) != 3 or slug in related:
        issue(slug, "related_candidates", "expected three distinct candidates excluding self")

report = {
    "schema_version": "blog-copy-batch-validation-v1",
    "status": "pass" if not issues else "fail",
    "article_count": len(manifest["items"]),
    "source_snapshot_count": len(list((ROOT / "sources").glob("*.txt"))),
    "local_media_count": len(list((ROOT / "media").glob("**/*.webp"))),
    "publish_ready_count": sum(bool(item.get("publish_ready")) for item in manifest["items"]),
    "issues": issues,
}
(ROOT / "batch-validation.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if not issues else 1)
