import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import Base, get_db, make_engine
from app.main import app
from app.models import ContentItem, SequenceRun, Sequence
from app.content_formatting import content_body_for_telegram, content_is_runtime_ready


@pytest.fixture
def publication(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'publication.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(ContentItem(code="tpl_nurture_01_max_full", title="Исходник",
                    purpose="Цель", writer_brief="ТЗ", source_markdown="", body_source="",
                    status="draft", editorial_status="placeholder", origin_system="obsidian_nurture_60"))
        session.commit()
    def override():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def payload(source="**Текст**\n\n[Открыть]({{personal_intensive_url}})"):
    return {"expected_version": 1, "body_source": "", "source_markdown": source,
            "title": "Новое название", "purpose": "Цель", "writer_brief": "ТЗ", "confirm": True}


def test_publish_retains_original_compiles_html_and_does_not_create_queue(publication):
    client, engine = publication
    response = client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=payload())
    assert response.status_code == 200, response.text
    assert response.json()["source_markdown"] == payload()["source_markdown"]
    assert response.json()["body_source"].startswith("<b>Текст</b>")
    with Session(engine) as session:
        item = session.scalar(select(ContentItem))
        assert item.title == "Новое название" and item.content_version == 2
        assert content_is_runtime_ready(item)
        assert content_body_for_telegram(item) == response.json()["body_source"]
        assert session.scalar(select(func.count()).select_from(Sequence)) == 0
        assert session.scalar(select(func.count()).select_from(SequenceRun)) == 0
    stale = client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=payload())
    assert stale.status_code == 409
    audit = client.get("/bot-api/content-audit").json()
    assert "tpl_nurture_01_max_full" in {item["code"] for item in audit["items"]}


@pytest.mark.parametrize("source", ["", "[жми](javascript:alert)", "![Картинка](../asset.jpg)", "{{unknown_variable}}"])
def test_invalid_publication_preserves_original_and_version(publication, source):
    client, engine = publication
    response = client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=payload(source))
    assert response.status_code == 422, response.text
    with Session(engine) as session:
        item = session.scalar(select(ContentItem))
        assert item.content_version == 1 and item.source_markdown == "" and item.body_source == ""


def test_html_mismatch_rejected_before_persisting(publication):
    client, engine = publication
    body = payload(); body["body_source"] = "<b>Подмена</b>"
    assert client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=body).status_code == 422


@pytest.mark.parametrize("route", ["publish", "patch"])
def test_legacy_html_edit_clears_stale_markdown_without_changing_media(publication, route):
    client, engine = publication
    response = client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=payload())
    assert response.status_code == 200
    with Session(engine) as session:
        item = session.scalar(select(ContentItem))
        item.media_path = "original.jpg"
        item.media_kind = "photo"
        item_id = item.id
        session.commit()
    if route == "publish":
        data = {"expected_version": 2, "body_source": "<b>Новый HTML</b>",
                "purpose": "Цель", "writer_brief": "ТЗ", "confirm": True}
        response = client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=data)
    else:
        response = client.patch(f"/bot-api/content/{item_id}", json={"expected_version": 2, "body_source": "<b>Новый HTML</b>", "editorial_status": "approved"})
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        item = session.scalar(select(ContentItem))
        assert item.source_markdown is None and item.body_source == "<b>Новый HTML</b>"
        assert item.media_path == "original.jpg" and item.media_kind == "photo"
        assert item.content_version == 3


def test_title_edit_is_versioned_and_preserves_markdown_original(publication):
    client, engine = publication
    response = client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=payload())
    assert response.status_code == 200
    with Session(engine) as session:
        item_id = session.scalar(select(ContentItem)).id
    assert client.patch(f"/bot-api/content/{item_id}", json={"title": "Другое название"}).status_code == 409
    assert client.patch(f"/bot-api/content/{item_id}", json={"title": "Другое название", "expected_version": 1}).status_code == 409
    response = client.patch(f"/bot-api/content/{item_id}", json={"title": "Другое название", "expected_version": 2})
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        item = session.scalar(select(ContentItem))
        assert item.content_version == 3 and item.title == "Другое название"
        assert item.source_markdown == payload()["source_markdown"]


@pytest.mark.parametrize("media_kind,limit", [(None, 4096), ("photo", 1024), ("video", 1024), ("voice", 1024)])
def test_compiled_markdown_over_message_or_caption_limit_cannot_be_published(publication, media_kind, limit):
    client, engine = publication
    with Session(engine) as session:
        item = session.scalar(select(ContentItem))
        item.media_kind = media_kind
        session.commit()
    # The Markdown itself fits; its generated HTML exceeds the existing limit.
    source = "**" + "x" * (limit - 5) + "**"
    assert len(source) < limit
    response = client.put("/bot-api/content/tpl_nurture_01_max_full/publish", json=payload(source))
    assert response.status_code == 422, response.text
    with Session(engine) as session:
        item = session.scalar(select(ContentItem))
        assert item.content_version == 1 and item.status == "draft"
        assert item.source_markdown == item.body_source == ""
