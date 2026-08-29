import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")

from app.content_authoring_service import (
    RevisionConflict,
    authoring_summary,
    decide_candidate_group,
    list_authoring_groups,
    list_candidate_groups,
    save_authoring_item,
)
from app.content_service import import_pikabu_items
from app.database import Base
from app.main import app
from app.models import ContentFamilyCandidate, ContentFamilyMembership, ContentItem, ContentItemVersion, ContentMedia, ContentSource
from scripts.import_content_authoring_catalog import _local_decision_key, import_snapshot, validate_snapshot


def test_import_script_bootstraps_backend_path(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    script = Path(__file__).resolve().parents[1] / "scripts" / "import_content_authoring_catalog.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--catalog" in result.stdout


def snapshot(tmp_path: Path) -> Path:
    sources = ["telegram_main", "bot", "telegraph", "pikabu", "pikabu_reply"]
    rows = []
    for index, source in enumerate(sources):
        family_id = "family-one" if index < 2 else None
        rows.append({
            "id": f"{source}-item-{index}", "source": source, "external_id": f"external-{index}",
            "source_url": f"https://example.test/{index}" if source != "bot" else None,
            "title": f"Материал {index}", "text": f"Полный содержательный текст {index}",
            "published_at": "2026-08-01T12:00:00+00:00", "family_id": family_id,
            "control": {"status": "active", "family_id": family_id, "variant_label": ""},
            "purpose": "ordinary_content", "sales_level": "none", "meanings": ["education"],
            "topics": ["Питание"], "primary_function": "education", "roles": ["education"],
            "media": {"present": False}, "provenance": {"outbound_urls": []},
        })
    (tmp_path / "catalog.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    pair = {"left": rows[2]["id"], "right": rows[3]["id"], "method": "same_normalized_title", "shared_tokens": 20}
    (tmp_path / "family-review-candidates.jsonl").write_text(json.dumps(pair) + "\n", encoding="utf-8")
    (tmp_path / "family-review-decisions.json").write_text(json.dumps({"format": "family-review-decisions-v1", "rejected_pair_keys": []}), encoding="utf-8")
    (tmp_path / "report.json").write_text(json.dumps({"active_manifestations": 5, "families": 1, "singletons": 3, "family_review_candidates": 1, "with_media": 0, "working_by_source": {source: 1 for source in sources}}), encoding="utf-8")
    return tmp_path


def sqlite_session_factory():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_snapshot_validation_is_source_complete(tmp_path: Path) -> None:
    result = validate_snapshot(snapshot(tmp_path))
    assert {key: result[key] for key in ("manifestations", "families", "singletons", "candidate_pairs", "candidate_groups", "with_media")} == {
        "manifestations": 5, "families": 1, "singletons": 3, "candidate_pairs": 1, "candidate_groups": 1, "with_media": 0,
    }
    assert len(result["snapshot_digest"]) == 64
    with pytest.raises(ValueError, match="digest"):
        import_snapshot(tmp_path, apply=True, backup_confirmed=True, expected_digest="0" * 64)


def test_import_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory = sqlite_session_factory()
    monkeypatch.setattr("app.database.SessionLocal", factory)
    root = snapshot(tmp_path)
    digest = validate_snapshot(root)["snapshot_digest"]
    first = import_snapshot(root, apply=True, backup_confirmed=True, expected_digest=digest)
    second = import_snapshot(root, apply=True, backup_confirmed=True, expected_digest=digest)
    assert (first["created"], first["versions_created"], first["memberships_created"], first["candidates_created"]) == (5, 5, 2, 1)
    assert (second["created"], second["matched"], second["versions_created"], second["memberships_created"], second["candidates_created"]) == (0, 5, 0, 0, 0)
    with factory() as db:
        assert authoring_summary(db)["manifestations"] == 5
        assert authoring_summary(db)["families"] == 1
        assert authoring_summary(db)["candidate_groups"] == 1


def test_import_matches_existing_production_item_and_preserves_owner_revision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory = sqlite_session_factory()
    monkeypatch.setattr("app.database.SessionLocal", factory)
    root = snapshot(tmp_path)
    digest = validate_snapshot(root)["snapshot_digest"]
    with factory() as db:
        source = ContentSource(platform="telegram", account_key="1878297271", display_name="Старый источник", canonical_url="https://t.me/Fitness_Talks")
        db.add(source); db.flush()
        existing = ContentItem(source_id=source.id, external_id="external-0", canonical_url="https://t.me/Fitness_Talks/1", title="До импорта")
        db.add(existing); db.flush()
        old_version = ContentItemVersion(item_id=existing.id, version_no=1, content_hash="e" * 64, text_content="Старый production-текст", blocks=[], parser_version="production-import-v1", editorial_metadata={})
        db.add(old_version); db.flush(); existing.latest_version_id = old_version.id
        db.commit(); existing_id = existing.id
    first = import_snapshot(root, apply=True, backup_confirmed=True, expected_digest=digest)
    assert first["created"] == 4 and first["matched"] == 1
    with factory() as db:
        item = db.get(ContentItem, existing_id)
        assert item.catalog_key == "telegram_main-item-0"
        saved = save_authoring_item(db, item.id, expected_revision=2, title="Ручной заголовок", text="Ручная редакция", variant_label="сильный", editorial_status="removed")
        assert saved["revision"] == 3
    second = import_snapshot(root, apply=True, backup_confirmed=True, expected_digest=digest)
    assert second["created"] == 0 and second["versions_created"] == 0
    with factory() as db:
        item = db.get(ContentItem, existing_id)
        assert (item.title, item.variant_label, item.editorial_status) == ("Ручной заголовок", "сильный", "removed")
        assert db.get(ContentItemVersion, item.latest_version_id).text_content == "Ручная редакция"


def test_local_rejected_candidate_is_imported_as_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory = sqlite_session_factory()
    monkeypatch.setattr("app.database.SessionLocal", factory)
    root = snapshot(tmp_path)
    pair = json.loads((root / "family-review-candidates.jsonl").read_text(encoding="utf-8"))
    (root / "family-review-decisions.json").write_text(json.dumps({"format": "family-review-decisions-v1", "rejected_pair_keys": [_local_decision_key(pair)]}), encoding="utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    report["family_review_candidates"] = 0
    (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
    digest = validate_snapshot(root)["snapshot_digest"]
    import_snapshot(root, apply=True, backup_confirmed=True, expected_digest=digest)
    with factory() as db:
        candidate = db.query(ContentFamilyCandidate).one()
        assert candidate.status == "rejected"
        assert authoring_summary(db)["candidate_groups"] == 0


def test_owner_save_creates_immutable_revision_and_detects_conflict() -> None:
    factory = sqlite_session_factory()
    with factory() as db:
        source = ContentSource(platform="telegram", account_key="1", display_name="Канал", canonical_url="https://t.me/test")
        db.add(source); db.flush()
        item = ContentItem(source_id=source.id, external_id="telegram:1:1", catalog_key="telegram-item", canonical_url="https://t.me/test/1", title="Старый", editorial_status="active")
        db.add(item); db.flush()
        version = ContentItemVersion(item_id=item.id, version_no=1, content_hash="a" * 64, text_content="Старый текст", blocks=[], parser_version="test", editorial_metadata={})
        db.add(version); db.flush(); item.latest_version_id = version.id
        db.add(ContentMedia(item_id=item.id, version_id=version.id, media_type="image", source_url="https://example.test/image.jpg", position=0, metadata_json={}))
        db.commit(); item_id = item.id
        updated = save_authoring_item(db, item_id, expected_revision=1, title="Новый", text="Новый текст", variant_label="нейтральный", editorial_status="active")
        assert updated["revision"] == 2
        assert updated["media"][0]["source_url"].endswith("image.jpg")
        assert db.query(ContentItemVersion).filter_by(item_id=item_id).count() == 2
        removed = save_authoring_item(db, item_id, expected_revision=2, title="Новый", text="Новый текст", variant_label="нейтральный", editorial_status="removed")
        restored = save_authoring_item(db, item_id, expected_revision=3, title="Новый", text="Новый текст", variant_label="нейтральный", editorial_status="active")
        changed_back = save_authoring_item(db, item_id, expected_revision=4, title="Старый снова", text="Старый текст", variant_label="", editorial_status="active")
        assert [removed["revision"], restored["revision"], changed_back["revision"]] == [3, 4, 5]
        assert db.query(ContentItemVersion).filter_by(item_id=item_id).count() == 5
        assert list_authoring_groups(db, editorial_status="active")["total"] == 1
        save_authoring_item(db, item_id, expected_revision=5, title="Старый снова", text="Старый текст", variant_label="", editorial_status="removed")
        assert list_authoring_groups(db, editorial_status="active")["total"] == 0
        assert list_authoring_groups(db, editorial_status="removed")["total"] == 1
        with pytest.raises(RevisionConflict):
            save_authoring_item(db, item_id, expected_revision=1, title="Конфликт", text="Другой текст", variant_label="", editorial_status="active")


def test_platform_reimport_preserves_owner_latest_and_revision_sequence() -> None:
    factory = sqlite_session_factory()
    original = {
        "external_id": "42",
        "canonical_url": "https://pikabu.ru/story/test_42",
        "title": "Заголовок источника",
        "text": "Исходный текст",
    }
    with factory() as db:
        assert import_pikabu_items(db, [original])["created"] == 1
        item = db.query(ContentItem).filter_by(external_id="42").one()
        item.catalog_key = "pikabu-42"; db.commit()
        owner = save_authoring_item(db, item.id, expected_revision=1, title="Ручной заголовок", text="Ручной текст", variant_label="нейтральный", editorial_status="active")
        assert owner["revision"] == 2
        changed_source = {**original, "title": "Новый заголовок источника", "text": "Новый текст источника"}
        assert import_pikabu_items(db, [changed_source])["updated"] == 1
        item = db.get(ContentItem, item.id)
        assert item.title == "Ручной заголовок"
        assert db.get(ContentItemVersion, item.latest_version_id).text_content == "Ручной текст"
        next_owner = save_authoring_item(db, item.id, expected_revision=2, title="Ручной заголовок 2", text="Ручной текст 2", variant_label="нейтральный", editorial_status="active")
        assert next_owner["revision"] == 4


def test_partial_candidate_merge_keeps_unselected_subgraph_pending() -> None:
    factory = sqlite_session_factory()
    with factory() as db:
        source = ContentSource(platform="telegram", account_key="candidate", display_name="Канал", canonical_url="https://t.me/test")
        db.add(source); db.flush()
        items = []
        for index in range(4):
            item = ContentItem(source_id=source.id, external_id=f"candidate-{index}", catalog_key=f"candidate-{index}", canonical_url=f"https://t.me/test/{index}", title=f"Кандидат {index}", editorial_status="active")
            db.add(item); db.flush()
            version = ContentItemVersion(item_id=item.id, version_no=1, content_hash=str(index) * 64, text_content=f"Текст {index}", blocks=[], parser_version="test", editorial_metadata={})
            db.add(version); db.flush(); item.latest_version_id = version.id; items.append(item)
        for left, right in zip(items, items[1:]):
            db.add(ContentFamilyCandidate(pair_key="|".join(sorted((left.catalog_key, right.catalog_key))), left_item_id=left.id, right_item_id=right.id, method="test", status="pending", metadata_json={}))
        db.commit()
        group = list_candidate_groups(db)["groups"][0]
        result = decide_candidate_group(db, candidate_id=group["id"], pair_keys=group["pair_keys"], action="merge", selected_ids=[items[0].id, items[1].id])
        assert result["members"] == 2
        statuses = {row.pair_key: row.status for row in db.query(ContentFamilyCandidate).all()}
        assert statuses["candidate-0|candidate-1"] == "merged"
        assert statuses["candidate-1|candidate-2"] == "rejected"
        assert statuses["candidate-2|candidate-3"] == "pending"
        memberships = db.query(ContentFamilyMembership).all()
        assert len(memberships) == 2
        assert len({row.family_id for row in memberships}) == 1
        remaining = list_candidate_groups(db)["groups"][0]
        assert decide_candidate_group(db, candidate_id=remaining["id"], pair_keys=remaining["pair_keys"], action="reject", selected_ids=[])["status"] == "rejected"
        with pytest.raises(RevisionConflict):
            decide_candidate_group(db, candidate_id=remaining["id"], pair_keys=remaining["pair_keys"], action="reject", selected_ids=[])


@pytest.mark.parametrize("path", [
    "/admin/api/content/authoring/summary",
    "/admin/api/content/authoring/groups",
    "/admin/api/content/authoring/candidates",
])
def test_authoring_api_requires_admin(path: str) -> None:
    assert TestClient(app, base_url="https://testserver").get(path).status_code == 401


@pytest.mark.parametrize(("method", "path", "payload"), [
    ("put", "/admin/api/content/authoring/items/00000000-0000-0000-0000-000000000001", {"expected_revision": 1, "title": "Заголовок", "text": "Текст", "variant_label": "", "editorial_status": "active"}),
    ("post", "/admin/api/content/authoring/candidates/decision", {"candidate_id": "candidate-x", "pair_keys": ["a|b"], "action": "reject", "selected_ids": []}),
])
def test_authoring_mutations_require_admin(method: str, path: str, payload: dict) -> None:
    response = getattr(TestClient(app, base_url="https://testserver"), method)(path, json=payload)
    assert response.status_code == 401


def test_server_editor_keeps_metadata_below_text_and_has_save_controls() -> None:
    static = Path(__file__).parents[1] / "app" / "static"
    html = (static / "content-catalog.html").read_text(encoding="utf-8")
    js = (static / "content-catalog.js").read_text(encoding="utf-8")
    assert html.index('id="text"') < html.index('class="metadata"')
    for marker in ("Сохранить изменения", "Возможные семьи", "Убрать эту версию"):
        assert marker in html
    assert "expected_revision" in js
    assert "state.candidateSelection" in js
    assert "Сначала сохраните изменения в тексте" in js
    assert 'aria-live="polite"' in html
    assert "position:fixed" not in (static / "content-catalog.css").read_text(encoding="utf-8").replace(" ", "")
