from types import SimpleNamespace
import hashlib

import pytest

from test_masterclass_journey import setup, teardown_function
import app.course_material_service as service


STEP = "day-03-source-current"
ENDPOINT = "/admin/api/courses/masterclass-21/materials/" + STEP
ORIGINAL = """# Служебное название
Статус: утверждено
Источник: первоначальная сборка

## Раздел

Первый авторский абзац.

![Фото](/course-assets/masterclass/media/known.webp)

slider(
/course-assets/masterclass/media/one.webp
/course-assets/masterclass/media/two.webp
)
"""


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def source_current(monkeypatch, tmp_path):
    client, factory = setup()
    path = tmp_path / "source-current" / "source.md"
    path.parent.mkdir()
    path.write_text(ORIGINAL, encoding="utf-8", newline="")
    steps = [{"id": STEP, "kind": "article", "title": "Материал", "contentAsset": "source.md"},
             {"id": "ordinary", "kind": "article", "title": "Обычная статья"},
             {"id": "day-01-article-02", "kind": "article", "contentAsset": "source.md"},
             {"id": "day-07-recipe-caesar", "kind": "article", "contentAsset": "source.md"},
             {"id": "day-15-recipe-caesar", "kind": "article", "contentAsset": "source.md"}]
    monkeypatch.setattr(service, "COURSE_CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "course_context", lambda db: SimpleNamespace(days={3: {"steps": steps}}))
    yield client, factory, path
    teardown_function()


def first_publish(client, content=ORIGINAL):
    before = client.get(ENDPOINT).json()
    response = client.put(ENDPOINT, json={"expected_version": 0, "expected_source_hash": before["source_hash"],
                                         "content": content, "format": "markdown"})
    assert response.status_code == 200, response.text
    return response.json()


def test_full_original_keeps_profile_through_put_restore_and_db_override(source_current):
    client, factory, path = source_current
    before = client.get(ENDPOINT).json()
    assert before["source_content"] == ORIGINAL
    assert before["source_hash"] == digest(ORIGINAL)
    assert before["publication_profile"] == {"type": "api", "render_profile": service.SOURCE_CURRENT_PROFILE}
    initial = first_publish(client)
    assert initial["source_content"] == ORIGINAL
    assert initial["html"] == before["html"]
    assert "Статус:" not in initial["html"]
    assert "Источник:" not in initial["html"]
    assert 'data-component="image-slider"' in initial["html"]
    assert 'src="/course-assets/masterclass/media/known.webp"' in initial["html"]
    path.write_text("## Старый Git уже не читательский оригинал\n", encoding="utf-8")
    changed = ORIGINAL.replace("Первый авторский абзац.", "Второй авторский абзац.")
    second = client.put(ENDPOINT, json={"expected_version": 1, "content": changed})
    assert second.status_code == 200, second.text
    assert second.json()["source_content"] == changed
    assert second.json()["source_render_profile"] == service.SOURCE_CURRENT_PROFILE
    assert "Источник:" not in second.json()["html"]
    restored = client.post(ENDPOINT + "/versions/1/restore", json={"expected_version": 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()["source_content"] == ORIGINAL
    assert restored.json()["html"] == before["html"]
    assert restored.json()["source_render_profile"] == service.SOURCE_CURRENT_PROFILE
    third = client.put(ENDPOINT, json={"expected_version": 3, "content": changed})
    assert third.status_code == 200
    assert "Источник:" not in third.json()["html"]
    assert client.get(ENDPOINT).json()["source_hash"] == digest(changed)
    listed = client.get("/admin/api/courses/masterclass-21/materials").json()["materials"]
    assert next(row for row in listed if row["step_id"] == STEP)["publication_profile"]["type"] == "api"
    with factory() as db:
        public = service.published_materials(db, allowed_days={3}, step_id=STEP)["materials"][STEP]
        assert public["html"] == third.json()["html"]
        assert not any(key.startswith("source_") for key in public)
        assert "publication_profile" not in public
    assert service.reader_material_payload(before).get("publication_profile") is None


def test_first_publication_requires_current_fallback_source_hash(source_current):
    client, factory, path = source_current
    before = client.get(ENDPOINT).json()
    assert client.put(ENDPOINT, json={"expected_version": 0, "content": ORIGINAL}).status_code == 409
    path.write_text(ORIGINAL.replace("Первый", "Заменённый"), encoding="utf-8", newline="")
    conflict = client.put(ENDPOINT, json={"expected_version": 0, "expected_source_hash": before["source_hash"],
                                         "content": ORIGINAL})
    assert conflict.status_code == 409
    with factory() as db:
        assert service.material_item(db, STEP) is None
    current = client.get(ENDPOINT).json()
    assert current["version"] == 0
    assert current["source_content"] != before["source_content"]
    accepted = client.put(ENDPOINT, json={"expected_version": 0, "expected_source_hash": current["source_hash"],
                                         "content": current["source_content"]})
    assert accepted.status_code == 200


def test_source_only_edit_retains_exact_crlf_original_and_creates_version(source_current):
    client, _, _ = source_current
    original = ORIGINAL.replace("\n", "\r\n")
    first = first_publish(client, original)
    changed = "<!-- Локальная редакторская пометка -->\r\n" + original
    second = client.put(ENDPOINT, json={"expected_version": 1, "content": changed})
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2
    assert second.json()["html"] == first["html"]
    current = client.get(ENDPOINT).json()
    assert current["source_content"] == changed
    assert current["source_hash"] == digest(changed)
    assert current["publication_profile"]["render_profile"] == service.SOURCE_CURRENT_PROFILE


def test_profile_does_not_strip_ordinary_author_source_text_or_allow_format_switch(source_current):
    client, _, _ = source_current
    ordinary = client.put("/admin/api/courses/masterclass-21/materials/ordinary", json={
        "expected_version": 0, "content": "Источник: авторский обзор.\n\nОбычный текст.",
    })
    assert ordinary.status_code == 200
    assert "Источник: авторский обзор." in ordinary.json()["html"]
    assert "source_render_profile" not in ordinary.json()
    first_publish(client)
    assert client.put(ENDPOINT, json={"expected_version": 1, "format": "html", "content": "<p>Подмена</p>"}).status_code == 422
    assert client.get(ENDPOINT).json()["version"] == 1


@pytest.mark.parametrize("step_id,profile", [("day-01-article-02", "git"), ("day-07-recipe-caesar", "archive")])
def test_git_original_and_recipe_archive_keep_existing_routes(source_current, step_id, profile):
    client, _, _ = source_current
    payload = client.get("/admin/api/courses/masterclass-21/materials/" + step_id).json()
    assert payload["publication_profile"]["type"] == profile
    response = client.put("/admin/api/courses/masterclass-21/materials/" + step_id,
                          json={"expected_version": 0, "content": ORIGINAL, "expected_source_hash": digest(ORIGINAL)})
    assert response.status_code == 409


def test_day15_recipe_does_not_enter_generic_fallback_profile(source_current):
    client, _, _ = source_current
    endpoint = "/admin/api/courses/masterclass-21/materials/day-15-recipe-caesar"
    payload = client.get(endpoint).json()
    assert "source_render_profile" not in payload
    assert payload["recipe_authoring"]["status"] == "original_sync_required"
    response = client.put(endpoint, json={"expected_version": 0, "content": ORIGINAL, "expected_source_hash": digest(ORIGINAL)})
    assert response.status_code == 409
