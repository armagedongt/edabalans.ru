from types import SimpleNamespace
import hashlib
import pytest
from test_masterclass_journey import setup, teardown_function
from app import course_material_service as service
from app.article_markdown_conversion import rendered
from app.main import app
from app.blog_draft_routes import require_blog_mutation

ENDPOINT = "/admin/api/courses/masterclass-21/materials/ordinary/markdown"
SOURCE = "## Раздел\n\nАвторский **абзац**.\n\nslider(\nhttps://example.org/one.png\nhttps://example.org/two.png\n)\n"


@pytest.fixture
def material(monkeypatch):
    client, factory = setup()
    app.dependency_overrides[require_blog_mutation] = lambda: "test-admin"
    monkeypatch.setattr(service, "course_context", lambda db: SimpleNamespace(days={3: {"steps": [
        {"id": "ordinary", "kind": "article", "title": "Материал"},
        {"id": "empty", "kind": "article", "title": "Пустой"}]}}))
    # Keep a historical byte-level layout different from the current renderer.
    html = rendered(SOURCE).replace("</p>", "</p>\n")
    with factory() as db:
        service.publish_material(db, step_id="ordinary", content=html, content_format="trusted_component_html",
                                 expected_version=0, admin="test")
    yield client, factory
    teardown_function()


def test_preview_adopt_preserves_exact_html_history_and_subsequent_edits(material):
    client, factory = material
    path = ENDPOINT.removesuffix("/markdown")
    original = client.get(path).json()
    preview = client.get(ENDPOINT)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    assert not prepared["already_markdown"]
    assert "slider(" in prepared["markdown"]
    assert client.get(path).json()["version"] == original["version"]
    adopted = client.post(ENDPOINT, json={"expected_version": prepared["expected_version"],
                                          "expected_html_sha256": prepared["html_sha256"]})
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["html"] == original["html"]
    assert adopted.json()["source_format"] == "markdown"
    assert adopted.json()["source_content"] == prepared["markdown"]
    assert client.get(ENDPOINT).json()["already_markdown"]
    assert client.post(ENDPOINT, json={"expected_version": 1, "expected_html_sha256": prepared["html_sha256"]}).status_code == 409
    changed = prepared["markdown"].replace("Авторский", "Изменённый")
    assert client.put(path, json={"expected_version": 2, "content": changed}).status_code == 200
    assert "Изменённый" in client.get(path).json()["html"]
    restored = client.post(path + "/versions/1/restore", json={"expected_version": 3})
    assert restored.status_code == 200
    assert restored.json()["html"] == original["html"]
    assert restored.json()["source_format"] == "html"


def test_stale_preview_wrong_hash_empty_and_special_originals_do_not_write(material):
    client, factory = material
    prepared = client.get(ENDPOINT).json()
    for version, sha in [(0, prepared["html_sha256"]), (1, "0" * 64)]:
        assert client.post(ENDPOINT, json={"expected_version": version, "expected_html_sha256": sha}).status_code == 409
    assert client.get(ENDPOINT.replace("ordinary", "empty")).status_code == 422
    assert client.get(ENDPOINT.replace("ordinary", "day-15-recipe-caesar")).status_code == 422
    assert client.get(ENDPOINT.replace("ordinary", "day-01-article-02")).status_code == 422
    assert client.get(ENDPOINT.removesuffix("/markdown")).json()["version"] == 1


def test_original_full_markdown_is_recovered_when_its_actual_render_matches(material, monkeypatch, tmp_path):
    client, factory = material
    original = "# Название\nСтатус: утверждено\n\n" + SOURCE
    source = tmp_path / "source-current" / "known.md"
    source.parent.mkdir()
    source.write_text(original, encoding="utf-8")
    monkeypatch.setattr(service, "COURSE_CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "course_context", lambda db: SimpleNamespace(days={3: {"steps": [
        {"id": "ordinary", "kind": "article", "title": "Материал", "contentAsset": "known.md"}]}}))
    prepared = client.get(ENDPOINT).json()
    assert prepared["original_recovered"]
    assert prepared["markdown"] == original
    response = client.post(ENDPOINT, json={"expected_version": 1, "expected_html_sha256": prepared["html_sha256"]})
    assert response.status_code == 200, response.text
    assert response.json()["source_render_profile"] == service.SOURCE_CURRENT_PROFILE
    assert "Статус:" not in response.json()["html"]


def test_hash_check_inside_native_publisher_rejects_changed_html(material):
    _, factory = material
    with factory() as db:
        with pytest.raises(Exception) as error:
            service.publish_material(db, step_id="ordinary", content=SOURCE, content_format="markdown",
                expected_version=1, admin="test", _markdown_adoption={"html_hash": "0" * 64})
        assert error.value.status_code == 409
        assert service.get_material(db, "ordinary")["version"] == 1


def test_conversion_authentication_and_cookie_origin_boundary(material, monkeypatch):
    client, _ = material
    prepared = client.get(ENDPOINT).json()
    body = {"expected_version": 1, "expected_html_sha256": prepared["html_sha256"]}
    app.dependency_overrides.pop(require_blog_mutation)
    assert client.post(ENDPOINT, json=body).status_code == 401
    import app.blog_draft_routes as boundary
    monkeypatch.setattr(boundary, "admin_identity", lambda request, credentials: "test-admin")
    assert client.post(ENDPOINT, json=body).status_code == 403
    assert client.post(ENDPOINT, json=body, headers={"Origin": "https://elsewhere.example"}).status_code == 403
    accepted = client.post(ENDPOINT, json=body, headers={"Origin": "https://edabalans.ru"})
    assert accepted.status_code == 200, accepted.text
    assert "no-store" in accepted.headers["cache-control"]


def test_calorie_native_adoption_and_unknown_course_keep_existing_boundaries(monkeypatch):
    from test_calorie_course_journey import setup as calorie_setup, teardown_function as calorie_teardown
    from app import calorie_course_material_service as native
    client, factory = calorie_setup(course_ready=False)
    app.dependency_overrides[require_blog_mutation] = lambda: "test-admin"
    step = "calories-stage-01-app"
    path = "/admin/api/courses/calories/materials/" + step
    try:
        original = client.put(path, json={"expected_version": 0, "format": "html", "content": "<p>Авторский текст.</p>"})
        assert original.status_code == 200, original.text
        prepared = client.get(path + "/markdown").json()
        adopted = client.post(path + "/markdown", json={"expected_version": 1, "expected_html_sha256": prepared["html_sha256"]})
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()["html"] == original.json()["html"]
        assert adopted.json()["source_content"] == "Авторский текст.\n"
        assert adopted.json()["source_format"] == "markdown"
        assert client.get(path.replace("calories/", "training/") + "/markdown").status_code == 404
        with factory() as db:
            with pytest.raises(Exception) as error:
                native.publish_material(db, step_id=step, content="Другой текст.", content_format="markdown",
                    expected_version=2, admin="test", _markdown_adoption={"html_hash": prepared["html_sha256"]})
            assert error.value.status_code == 422
            assert native.get_material(db, step)["version"] == 2
    finally:
        calorie_teardown()
