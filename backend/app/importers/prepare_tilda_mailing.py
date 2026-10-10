"""Prepare encrypted paused letters and a private export; never launch delivery."""
import argparse
import csv
import io
import json
from pathlib import Path
import zipfile

from app.config import get_settings
from app.database import SessionLocal
from app.account_onboarding_service import _decrypt_bundle
from app.tilda_mailing_service import prepare_drafts, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.export.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("Letters with passwords must be exported outside the repository")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    settings = get_settings()
    with SessionLocal() as db:
        created = prepare_drafts(db, manifest, settings, "tilda_transfer_prepare")
        args.export.parent.mkdir(parents=True, exist_ok=True)
        index = io.StringIO(newline="")
        writer = csv.writer(index)
        writer.writerow(["name", "email", "file", "status"])
        with zipfile.ZipFile(args.export, "w", zipfile.ZIP_DEFLATED) as archive:
            for row in rows(db):
                bundle = _decrypt_bundle(row.claim_bundle_encrypted, settings)
                name = str(row.id) + ".txt"
                archive.writestr(name, bundle["subject"] + "\n\n" + bundle["message_text"])
                writer.writerow([bundle["name"], bundle["email"], name, row.email_status])
            archive.writestr("recipients.csv", "\ufeff" + index.getvalue())
        args.export.chmod(0o600)
        db.commit() if args.apply else db.rollback()
    print(json.dumps({"drafts_created": created, "messages_queued": 0, "applied": args.apply}))


if __name__ == "__main__":
    main()
