"""Attach approved exact card data to existing materials; never copy article bodies.

Input is a private JSON release bundle on stdin. Dry-run is the default.
Published material versions are checked under locks before a single transaction.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from app.database import SessionLocal
from app.course_material_service import latest_version, material_item
from app.recipe_originals import METADATA_KEY, STEP_PREFIX, validated_cards


def publish(db, bundle: dict, *, apply: bool = False) -> dict:
    entries = bundle.get("materials")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError("Ожидается список материалов")
    ids = set()
    updates = []
    active = inactive = 0
    card_ids = set()
    for entry in entries:
        step = entry.get("step_id", "")
        if not isinstance(step, str) or not step.startswith(STEP_PREFIX) or step in ids:
            raise ValueError("Некорректный или повторяющийся рецепт")
        ids.add(step)
        item = material_item(db, step, for_update=True)
        version = latest_version(db, item)
        if version is None or version.version_no != entry.get("expected_version"):
            raise ValueError(f"Материал {step} изменён; обновите bundle")
        fingerprint = entry.get("source_hash", "")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("Ожидается fingerprint утверждённого MD")
        cards = validated_cards(entry.get("cards"))
        for card in cards:
            if card["id"] in card_ids:
                raise ValueError("Повторяющийся id оригинального рецепта")
            card_ids.add(card["id"])
            active += card["active"]
            inactive += not card["active"]
        metadata = dict(item.metadata_json or {})
        metadata[METADATA_KEY] = {"version": version.version_no, "source_hash": fingerprint, "cards": cards}
        updates.append((item, metadata))
    if apply:
        for item, metadata in updates:
            item.metadata_json = metadata
        db.flush()
    return {"materials": len(updates), "active": active, "inactive": inactive, "applied": apply}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    bundle = json.load(sys.stdin)
    with SessionLocal() as db:
        report = publish(db, bundle, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
