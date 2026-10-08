from copy import deepcopy

import pytest
from sqlalchemy import func, select

from test_masterclass_journey import setup, teardown_function
from app.course_material_service import get_material, material_item, latest_version, publish_material
from app.course_structure_service import course_context, DOCUMENT_TYPE, DOCUMENT_KEY, MANAGED_SCHEMA_VERSION
from app.managed_documents import publish_document
from app.models import ContentItemVersion
from app.recipe_originals import METADATA_KEY, original_records
from app.recipe_material_authoring import publication_markdown, source_hash
from scripts.publish_recipe_originals import publish as publish_originals


STEP = "day-15-recipe-caesar"
ENDPOINT = f"/admin/api/courses/masterclass-21/materials/{STEP}"
CONTENT = """# Тестовый рецепт

Обычный авторский абзац.

recipe_card(
/course-assets/masterclass/media/15-recipes/caesar/recipe-card-caesar.webp
Тестовый рецепт
)

![Фото](media/caesar.webp)

<!-- recipe-card-data:start
schema_version: 1
recipe_id: caesar
title: Тестовый рецепт
yield_g: 100
portion_g: 50
nutrition_available: true

## Точный расчёт
| Продукт | Вес, г | Б, г | Ж, г | У, г | ккал |
| --- | --- | --- | --- | --- | --- |
| Продукт | 100 | 10 | 2 | 20 | 138 |
recipe-card-data:end -->
"""
CARDS = [{"id": "caesar", "title": "Тестовый рецепт", "active": True,
          "yield": "100", "portion": "50", "rows": [["Продукт", "100", "10", "2", "20", "138"]]}]


@pytest.fixture
def recipe_source():
    client, factory = setup()
    with factory() as db:
        context = course_context(db)
        payload = deepcopy(context.revision.payload)
        day = next(day for day in payload["days"] if day["number"] == 15)
        day["steps"].append({"id": STEP, "title": "Тестовый рецепт", "kind": "article",
                             "contentKind": "text", "nested": True, "required": False,
                             "parentStepId": "day-15-recipes-part-2"})
        publish_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
                         schema_version=MANAGED_SCHEMA_VERSION, payload=payload,
                         expected_version=context.revision.version_no, admin="test")
        publish_material(db, step_id=STEP, content=publication_markdown(STEP, CONTENT),
                         content_format="markdown", expected_version=0, admin="test")
        item = material_item(db, STEP)
        latest = latest_version(db, item)
        latest.blocks = [{"type": "article_html", "html": latest.text_content}]
        item.metadata_json = {"other_owner": {"preserved": True}}
        publish_originals(db, {"materials": [{"step_id": STEP, "expected_version": 1,
                           "source_hash": source_hash(CONTENT), "cards": CARDS}]}, apply=True)
        db.commit()
    yield client, factory
    teardown_function()


def adopt(client):
    response = client.post(ENDPOINT + "/recipe-source", json={"expected_version": 1, "content": CONTENT})
    assert response.status_code == 200, response.text
    return response.json()


def test_adoption_paragraph_publication_and_restore_keep_original_available(recipe_source):
    client, factory = recipe_source
    assert client.get(ENDPOINT).json()["recipe_authoring"]["status"] == "adoption_required"
    before = client.get(ENDPOINT).json()["html"]
    adopted = adopt(client)
    assert adopted["source_content"] == CONTENT
    assert adopted["html"] == before
    assert adopted["version"] == 2
    assert client.get(ENDPOINT).json()["recipe_authoring"]["status"] == "ready"
    changed = CONTENT.replace("Обычный авторский абзац.", "Исправленный авторский абзац.")
    published = client.put(ENDPOINT, json={"expected_version": 2, "content": changed})
    assert published.status_code == 200, published.text
    assert published.json()["source_content"] == changed
    assert 'src="/course-assets/masterclass/media/15-recipes/caesar/caesar.webp"' in published.json()["html"]
    assert 'class="recipe-card' in published.json()["html"]
    with factory() as db:
        records = original_records(db)
        assert len(records) == 1
        assert records[0]["version"] == 3
        assert records[0]["source_hash"] == source_hash(changed)
        assert records[0]["rows"] == CARDS[0]["rows"]
        assert material_item(db, STEP).metadata_json["other_owner"] == {"preserved": True}
    unchanged = client.put(ENDPOINT, json={"expected_version": 3, "content": changed})
    assert unchanged.status_code == 200
    assert unchanged.json()["version"] == 3
    restored = client.post(ENDPOINT + "/versions/2/restore", json={"expected_version": 3})
    assert restored.status_code == 200, restored.text
    assert restored.json()["source_content"] == CONTENT
    assert restored.json()["html"] == before
    with factory() as db:
        assert original_records(db)[0]["version"] == 4
        assert original_records(db)[0]["source_hash"] == source_hash(CONTENT)
    assert client.post(ENDPOINT + "/versions/1/restore", json={"expected_version": 4}).status_code == 409


@pytest.mark.parametrize("mutation", [
    lambda text: text.replace("| 100 | 10 |", "| 100 | 11 |"),
    lambda text: text.replace("media/caesar.webp", "media/replacement.webp"),
    lambda text: text.replace("recipe-card-caesar.webp", "recipe-card-new.webp"),
    lambda text: text[:text.index("<!-- recipe-card-data:start")],
])
def test_protected_recipe_changes_are_rejected_without_changing_versions(recipe_source, mutation):
    client, factory = recipe_source
    adopt(client)
    response = client.put(ENDPOINT, json={"expected_version": 2, "content": mutation(CONTENT)})
    assert response.status_code == 409
    with factory() as db:
        assert latest_version(db, material_item(db, STEP)).version_no == 2
        assert original_records(db)[0]["version"] == 2
        assert original_records(db)[0]["source_hash"] == source_hash(CONTENT)


def test_adoption_requires_existing_source_hash_and_exact_render(recipe_source):
    client, factory = recipe_source
    forged = CONTENT.replace("Обычный", "Подменённый")
    assert client.post(ENDPOINT + "/recipe-source", json={"expected_version": 1, "content": forged}).status_code == 409
    assert client.put(ENDPOINT, json={"expected_version": 1, "content": CONTENT}).status_code == 409
    with factory() as db:
        item = material_item(db, STEP)
        metadata = deepcopy(item.metadata_json)
        metadata[METADATA_KEY]["source_hash"] = source_hash(forged)
        item.metadata_json = metadata
        db.commit()
    assert client.post(ENDPOINT + "/recipe-source", json={"expected_version": 1, "content": forged}).status_code == 409
    assert client.get(ENDPOINT).json()["version"] == 1


def test_failed_original_sync_rolls_back_material_and_metadata(recipe_source, monkeypatch):
    client, factory = recipe_source
    adopt(client)
    changed = CONTENT.replace("Обычный", "Исправленный")
    assert client.put(ENDPOINT, json={"expected_version": 1, "content": changed}).status_code == 409
    def reject(*args, **kwargs):
        publish_originals(*args, **kwargs)
        raise ValueError("Отказ синхронизации")
    monkeypatch.setattr("app.recipe_material_authoring.publish_originals", reject)
    response = client.put(ENDPOINT, json={"expected_version": 2, "content": changed})
    assert response.status_code == 422
    with factory() as db:
        item = material_item(db, STEP)
        assert get_material(db, STEP)["source_content"] == CONTENT
        assert item.metadata_json[METADATA_KEY]["version"] == 2
        assert item.metadata_json[METADATA_KEY]["source_hash"] == source_hash(CONTENT)
        assert db.scalar(select(func.count()).select_from(ContentItemVersion).where(ContentItemVersion.item_id == item.id)) == 2


def test_crlf_adoption_then_lf_paragraph_edit_preserves_exact_input_hash(recipe_source):
    client, factory = recipe_source
    original = CONTENT.replace("\n", "\r\n")
    with factory() as db:
        item = material_item(db, STEP)
        metadata = deepcopy(item.metadata_json)
        metadata[METADATA_KEY]["source_hash"] = source_hash(original)
        item.metadata_json = metadata
        db.commit()
    adopted = client.post(ENDPOINT + "/recipe-source", json={"expected_version": 1, "content": original})
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["source_content"] == original
    with factory() as db:
        assert original_records(db)[0]["source_hash"] == source_hash(original)
    edited = CONTENT.replace("Обычный авторский абзац.", "Исправленный авторский абзац.")
    published = client.put(ENDPOINT, json={"expected_version": 2, "content": edited})
    assert published.status_code == 200, published.text
    assert published.json()["source_content"] == edited
    with factory() as db:
        assert original_records(db)[0]["source_hash"] == source_hash(edited)
        assert original_records(db)[0]["version"] == 3
