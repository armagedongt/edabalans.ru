import os
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("KNOWLEDGE_MCP_TOKEN", "library-test-token")

from app.database import Base
from app.knowledge_library_service import (
    knowledge_read,
    knowledge_search,
    library_summary,
    list_reviews,
    queue_review,
    record_usage,
    save_relation,
    save_resource,
    task_context,
)
from app.main import app
from app.models import ContentItem, ContentItemVersion, ContentSource
from app.models import KnowledgeResourceVersion, KnowledgeUsageEvent
from app.models import KnowledgeRelation, KnowledgeReviewItem, KnowledgeResource
from scripts import sync_knowledge_library as sync_module


def test_sync_script_bootstraps_backend_path(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    result = subprocess.run(
        [sys.executable, str(Path(sync_module.__file__).resolve()), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "knowledge-library" in result.stdout


def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def resource_payload(key: str, text: str = "Полный текст о периодизации") -> dict:
    return {
        "resource_key": key,
        "title": "Периодизация похудения",
        "contour": "editorial",
        "resource_kind": "transcript",
        "role": "source",
        "state": "reference",
        "storage_kind": "database",
        "canonical_uri": f"knowledge://resource/{key}",
        "owner_module": "platform.knowledge",
        "access_level": "internal",
        "text": text,
        "provenance": {"origin": "stream"},
        "created_by": "test",
    }


def test_resource_versions_search_relations_and_usage() -> None:
    factory = session_factory()
    with factory() as db:
        first = save_resource(db, **resource_payload("stream.periodization"))
        assert first["version"] == 1
        same = save_resource(db, **resource_payload("stream.periodization"), expected_version=1)
        assert same["version"] == 1
        changed = save_resource(
            db,
            **resource_payload("stream.periodization", "Новая полная версия о периодизации"),
            expected_version=1,
        )
        assert changed["version"] == 2
        save_resource(db, **resource_payload("article.periodization", "Готовая статья"))
        relation = save_relation(
            db,
            source_key="article.periodization",
            target_key="stream.periodization",
            relation_type="derived_from",
        )
        assert relation["status"] == "active"
        result = knowledge_search(db, query="периодизации", limit=10)
        assert any(row["uri"] == "knowledge://resource/stream.periodization" for row in result["results"])
        article = knowledge_read(db, "knowledge://resource/article.periodization")
        assert article["relations"][0]["target_uri"] == "knowledge://resource/stream.periodization"
        record_usage(
            db, source_uri="knowledge://resource/stream.periodization",
            task_key="mk-day-21",
            destination="Мастер-класс",
            usage_kind="adapted",
        )
        assert db.query(KnowledgeUsageEvent).count() == 1
        assert db.query(KnowledgeUsageEvent).one().source_uri == "knowledge://resource/stream.periodization"
        assert db.query(KnowledgeResourceVersion).count() == 3


def test_restricted_personal_keeps_person_reference() -> None:
    factory = session_factory()
    with factory() as db:
        payload = resource_payload("consultation.case")
        payload["access_level"] = "restricted_personal"
        with pytest.raises(ValueError, match="person_reference"):
            save_resource(db, **payload)
        payload["person_reference"] = "crm-user:42"
        saved = save_resource(db, **payload)
        assert saved["person_reference"] == "crm-user:42"


def test_review_queue_and_task_disclosure_policy() -> None:
    factory = session_factory()
    with factory() as db:
        save_resource(db, **resource_payload("stream.periodization"))
        queued = queue_review(
            db,
            review_key="overlap.periodization",
            review_kind="semantic_overlap",
            title="Похожие блоки",
            resource_keys=["stream.periodization"],
            details={"reason": "Нельзя склеивать автоматически"},
        )
        assert queued["status"] == "pending"
        context = task_context(
            db,
            topic="периодизация",
            task_type="telegram_post",
            surface="open",
        )
        assert "нельзя выкладывать всю систему" in context["use_policy"]
        assert library_summary(db)["pending_reviews"] == 1
        reviews = list_reviews(db)
        assert reviews[0]["resources"][0]["resource_key"] == "stream.periodization"


def test_publication_taxonomy_is_searchable_and_returned() -> None:
    factory = session_factory()
    with factory() as db:
        source = ContentSource(
            platform="telegram", account_key="core", display_name="Канал",
            canonical_url="https://t.me/example",
        )
        db.add(source)
        db.flush()
        item = ContentItem(
            source_id=source.id, external_id="core-1",
            canonical_url="https://t.me/example/1", title="Программный пост",
            purpose="ordinary_content", topics=["Похудение"],
            meanings=["концептуальное ядро"], primary_function="methodology",
        )
        db.add(item)
        db.flush()
        version = ContentItemVersion(
            item_id=item.id, version_no=1, content_hash="b" * 64,
            text_content="Авторский программный текст", blocks=[],
            parser_version="test", editorial_metadata={},
        )
        db.add(version)
        db.flush()
        item.latest_version_id = version.id
        db.commit()

        found = knowledge_search(db, query="концептуальное ядро")
        assert found["results"][0]["meanings"] == ["концептуальное ядро"]
        opened = knowledge_read(db, found["results"][0]["uri"])
        assert opened["primary_function"] == "methodology"
        record_usage(
            db, source_uri=found["results"][0]["uri"], task_key="telegram-core",
            destination="Telegram", usage_kind="quoted",
        )
        event = db.query(KnowledgeUsageEvent).one()
        assert event.resource_id is None


def test_library_api_and_mcp_require_authentication() -> None:
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/admin/api/library/summary").status_code == 401
    assert client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    ).status_code == 401


def test_bundle_import_is_guarded_atomic_and_idempotent(tmp_path, monkeypatch) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    resources = [
        resource_payload("source.one", "Первый полный источник"),
        resource_payload("source.two", "Второй полный источник"),
    ]
    relation = {
        "source_key": "source.two",
        "target_key": "source.one",
        "relation_type": "derived_from",
        "metadata": {"coverage": "partial"},
    }
    review = {
        "review_key": "source.overlap",
        "review_kind": "semantic_overlap",
        "title": "Проверить смысловое совпадение",
        "resource_keys": ["source.one", "source.two"],
        "details": {"reason": "Не склеивать автоматически"},
    }
    for filename, rows in (
        ("resources.jsonl", resources),
        ("relations.jsonl", [relation]),
        ("reviews.jsonl", [review]),
    ):
        (bundle / filename).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    factory = session_factory()
    monkeypatch.setattr(sync_module, "SessionLocal", factory)
    dry_run = sync_module.sync_bundle(bundle)
    assert dry_run["applied"] is False
    with pytest.raises(ValueError, match="digest"):
        sync_module.sync_bundle(
            bundle, apply=True, backup_confirmed=True, expected_digest="wrong",
        )

    first = sync_module.sync_bundle(
        bundle, apply=True, backup_confirmed=True,
        expected_digest=dry_run["digest"],
    )
    second = sync_module.sync_bundle(
        bundle, apply=True, backup_confirmed=True,
        expected_digest=dry_run["digest"],
    )
    assert first["applied"] is True
    assert second["applied"] is True
    with factory() as db:
        assert db.query(KnowledgeResource).count() == 2
        assert db.query(KnowledgeResourceVersion).count() == 2
        assert db.query(KnowledgeRelation).count() == 1
        assert db.query(KnowledgeReviewItem).count() == 1
