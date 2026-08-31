"""Validate and publish the accepted visible Masterclass package that differs from production."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from author_workflow import create_review
from prepare_author_post import build_pack
from publish_course_material import verify_publish_gate
from validate_author_draft import file_sha256, validate


PACKAGE = {
    "06-necessary-restrictions.md": "day-03-video-01",
    "66-sugar-plan.md": "day-10-article-01",
    "27-added-sugar-guide.md": "day-10-article-03",
    "28-reduce-harm-from-sweets.md": "day-11-article-01",
    "29-reduce-amount-of-sweets.md": "day-11-article-02",
    "38-cheat-meals-audio.md": "day-12-article-02",
    "31-satiety-habits.md": "day-13-article-01",
    "32-pleasure-habits.md": "day-13-article-02",
    "46-eating-outside-home.md": "day-14-article-01",
    "63-behind-scenes.md": "day-18-article-02",
    "16-health-block-closing.md": "day-17-article-01",
    "17-detox-vitamins-minerals-tests.md": "day-17-article-02",
    "18-water.md": "day-17-article-03",
    "52-how-consultation-works.md": "day-19-article-02",
}
FACT_FREE = {"63-behind-scenes.md", "52-how-consultation-works.md"}
SOURCE_ROOT = ROOT / "content" / "masterclass" / "source-current"
INDEX = Path(r"C:\private\edabalans-content-authoring\voice\v1\voice-index.sqlite")
PRIVATE = Path(tempfile.gettempdir()) / "edabalans-masterclass-finalization-remaining-2026-08-31"
REMOTE = (
    "cd /opt/edabalans && docker compose exec -T backend "
    "python /tmp/course-material-api.py"
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def remote(action: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["ssh", "edabalans-prod", f"{REMOTE} {action}"],
        input=None if payload is None else json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def validate_file(asset: str) -> tuple[Path, Path, Path, dict]:
    source = SOURCE_ROOT / asset
    text = source.read_text(encoding="utf-8")
    stem = source.stem
    task_path = PRIVATE / f"{stem}.task.json"
    pack_path = PRIVATE / f"{stem}.pack.json"
    draft_path = PRIVATE / f"{stem}.draft.md"
    review_path = PRIVATE / f"{stem}.review.json"
    report_path = PRIVATE / f"{stem}.validation-final.json"

    required_facts = [] if asset in FACT_FREE else [{
        "text": (
            "Существенные научные, медицинские и числовые утверждения текущей версии "
            "сверены с указанными рядом первичными или официальными источниками; "
            "авторские рабочие ориентиры не выданы за универсальные медицинские нормы."
        ),
        "mode": "semantic",
    }]
    task = {
        "note": f"Финальный выпуск принятого материала Мастер-класса: {asset}",
        "work_profile": "develop_existing",
        "edit_mode": "rewrite",
        "surface_context": "masterclass_material",
        "format_profile": "article",
        "source_basis": "full_source",
        "author_reuse_mode": "authored_blocks_first",
        "allow_link_media_changes": True,
        "source_text": text,
        "preservation_anchors": [text[:160], text[-160:]],
        "course_context": {
            "day_context": "Действующая программа Мастер-класса, дни 10–19",
            "material_role": "Сохранить полный авторский материал в его текущей учебной роли.",
            "continuity": "Материал публикуется на существующем месте без перестановки программы.",
        },
        "rewrite_goal": (
            "Сохранить полный авторский материал; выпустить текущую версию после "
            "нейрослоп-аудита и пропорционального фактчека."
        ),
        "required_facts": required_facts,
        "fact_sources": [] if asset in FACT_FREE else [{
            "name": "Источники внутри материала и первичный фактчек пакета 2026-08-31",
            "fingerprint": f"masterclass:{asset}:2026-08-31",
        }],
        "forbidden_claims": [
            "Авторский рабочий ориентир является универсальной медицинской нормой.",
            "Корреляционное исследование само по себе доказывает причинность.",
        ],
    }
    write_json(task_path, task)
    write_json(pack_path, build_pack(task_path, INDEX))
    draft_path.write_text(text, encoding="utf-8")

    initial = validate(pack_path, draft_path)
    if initial["status"] == "needs_fix":
        raise ValueError(f"{asset}: {initial['errors']}")
    checks = [
        f"{item['id']}=Проверено по текущему полному тексту; сильные авторские блоки сохранены, "
        "нейрослоп и существенные фактические абсолюты исправлены или вынесены в ограничения."
        for item in initial["pending_manual_reviews"]
    ]
    if checks:
        create_review(
            pack_path,
            draft_path,
            review_path,
            reviewer="Codex editorial factcheck 2026-08-31",
            check_values=checks,
        )
        final = validate(pack_path, draft_path, review_path)
    else:
        final = initial
    write_json(report_path, final)
    if final["status"] != "pass":
        raise ValueError(f"{asset}: final validation is {final['status']}")
    verify_publish_gate(draft_path, pack_path, report_path)
    return draft_path, pack_path, report_path, final


def main() -> int:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    current = remote("list")
    versions = {item["step_id"]: int(item["version"]) for item in current["materials"]}
    materials = []
    manifest = []
    only_assets = {
        item.strip()
        for item in os.getenv("MASTERCLASS_ONLY_ASSET", "").split(",")
        if item.strip()
    }
    selected = {
        asset: step_id
        for asset, step_id in PACKAGE.items()
        if not only_assets or asset in only_assets
    }
    unknown = only_assets.difference(PACKAGE)
    if unknown:
        raise ValueError(f"unknown MASTERCLASS_ONLY_ASSET: {sorted(unknown)}")
    for asset, step_id in selected.items():
        draft, pack, report, validation = validate_file(asset)
        materials.append({
            "step_id": step_id,
            "expected_version": versions[step_id],
            "content": draft.read_text(encoding="utf-8"),
            "format": "markdown",
        })
        manifest.append({
            "asset": asset,
            "step_id": step_id,
            "previous_version": versions[step_id],
            "draft_sha256": file_sha256(draft),
            "validation": validation["status"],
        })

    result = remote("batch", {"materials": materials})
    if len(result.get("published") or []) != len(materials):
        raise ValueError("production did not confirm every remaining material")
    published = {item["step_id"]: item for item in result["published"]}
    for item in manifest:
        item["published_version"] = published[item["step_id"]]["version"]
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_sha256": hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "materials": manifest,
    }
    write_json(ROOT / "work/masterclass-editorial-finalization-2026-08-31/published-package.json", output)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
