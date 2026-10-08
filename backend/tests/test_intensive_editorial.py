import hashlib
import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import require_admin  # noqa: E402
from app import intensive_editorial_routes as routes  # noqa: E402
from app.intensive_editorial_routes import IntensiveContentEditor, SOURCE_ID, SOURCE_PATH  # noqa: E402
from app.intensive_onepage import SOURCE, render_article  # noqa: E402
from app.main import app  # noqa: E402
from app.masterclass_editorial import EDITABLE_MATERIALS  # noqa: E402
from app.github_content_editor import GitHubContentEditor  # noqa: E402
from test_github_content_editor import FakeEditor, settings  # noqa: E402


class FakeIntensiveEditor(IntensiveContentEditor, FakeEditor):
    def __init__(self):
        FakeEditor.__init__(self)
        original = SOURCE.read_text(encoding="utf-8")
        self.files["main"]["content"] = original
        self.files["content-drafts"]["content"] = original
        self.content_paths = []

    def _request(self, method, suffix, **kwargs):
        if suffix.startswith("contents/"):
            self.content_paths.append(suffix.removeprefix("contents/"))
        return FakeEditor._request(self, method, suffix, **kwargs)


@pytest.fixture
def client(monkeypatch):
    editor = FakeIntensiveEditor()
    monkeypatch.setattr(routes, "editor", lambda: editor)
    previous = app.dependency_overrides.get(require_admin)
    app.dependency_overrides[require_admin] = lambda: "intensive-editor-test"
    yield TestClient(app), editor
    if previous is None:
        app.dependency_overrides.pop(require_admin, None)
    else:
        app.dependency_overrides[require_admin] = previous


def test_api_edits_the_fixed_original_and_reports_queued_before_runtime_matches(client):
    client, editor = client
    before = client.get("/admin/api/editorial/intensive")
    assert before.status_code == 200
    assert before.headers["cache-control"] == "private, no-store"
    source = before.json()
    assert source["path"] == SOURCE_PATH
    assert source["connected"] is True
    assert source["draft"] is None
    assert source["runtime_source"]["sha256"] == hashlib.sha256(
        SOURCE.read_text(encoding="utf-8").encode()).hexdigest()
    original = source["main"]["content"]
    changed = original.replace("кажется, пора менять подход!", "пора по-новому менять подход!", 1)
    assert changed != original
    draft = client.put("/admin/api/editorial/intensive/draft", json={
        "content": changed, "expected_main_sha": source["main"]["sha"],
        "expected_draft_sha": None,
    })
    assert draft.status_code == 200
    assert editor.files["main"]["content"] == original
    saved = client.get("/admin/api/editorial/intensive").json()
    assert saved["draft"]["content"] == changed
    published = client.post("/admin/api/editorial/intensive/publish", json={
        "expected_main_sha": source["main"]["sha"], "expected_draft_sha": saved["draft"]["sha"],
    })
    assert published.status_code == 200
    assert published.json()["deployment"] == "queued"
    assert editor.files["main"]["content"] == changed
    runtime = client.get("/admin/api/editorial/intensive").json()["runtime_source"]
    assert runtime["sha256"] != hashlib.sha256(changed.encode()).hexdigest()
    assert set(editor.content_paths) == {SOURCE_PATH}
    assert editor.writes[0]["message"].startswith("draft(intensive):")
    assert editor.writes[1]["message"].startswith("content(intensive):")
    _, body, _ = render_article(changed)
    assert 'class="comparison comparison-unbalanced"' in body
    assert 'class="comparison comparison-balanced"' in body
    assert 'aria-disabled="true"' in body


@pytest.mark.parametrize("bad_source", [
    "missing_heading", "missing_marker", "invalid_channel_pair", "oversized_bytes", "reordered_markers",
])
def test_invalid_intensive_source_does_not_write_to_github(client, bad_source):
    client, editor = client
    content = editor.files["main"]["content"]
    if bad_source == "missing_heading":
        content = content.partition("\n")[2]
    elif bad_source == "missing_marker":
        content = content.replace("<!-- intensive:reading:end -->", "", 1)
    elif bad_source == "invalid_channel_pair":
        content = content.replace("> [Открыть MAX]()", "> [Telegram]()", 1)
    elif bad_source == "reordered_markers":
        content = content.replace("intensive:comparison-balanced:start", "TEMP", 1).replace(
            "intensive:comparison-balanced:end", "intensive:comparison-balanced:start", 1).replace(
            "TEMP", "intensive:comparison-balanced:end", 1)
    else:
        content = "# Заголовок\n" + "я" * 250_000
    response = client.put("/admin/api/editorial/intensive/draft", json={
        "content": content, "expected_main_sha": "a" * 40,
    })
    assert response.status_code == 422
    assert editor.writes == []


def test_publish_rejects_concurrent_main_change_and_invalid_saved_draft(client):
    client, editor = client
    changed = editor.files["main"]["content"] + "\nДополнительная строка.\n"
    assert client.put("/admin/api/editorial/intensive/draft", json={
        "content": changed, "expected_main_sha": "a" * 40,
    }).status_code == 200
    stale = client.post("/admin/api/editorial/intensive/publish", json={
        "expected_main_sha": "9" * 40, "expected_draft_sha": "b" * 40,
    })
    assert stale.status_code == 409
    assert len(editor.writes) == 1
    editor.files["content-drafts"]["content"] = "# Невалидный черновик\n"
    invalid = client.post("/admin/api/editorial/intensive/publish", json={
        "expected_main_sha": "a" * 40, "expected_draft_sha": "b" * 40,
    })
    assert invalid.status_code == 422
    assert len(editor.writes) == 1


def test_arbitrary_paths_and_ids_are_not_an_editor_profile():
    editor = IntensiveContentEditor(settings())
    for source_id in ("other", "../../.env", "day-01-article-02"):
        with pytest.raises(KeyError):
            editor.load(source_id)


def test_original_masterclass_profile_still_uses_all_nine_allowlisted_paths():
    editor = GitHubContentEditor(settings())
    assert len(EDITABLE_MATERIALS) == 9
    for step_id, path in EDITABLE_MATERIALS.items():
        assert editor.source_path(step_id) == path
    assert editor.profile_name == "masterclass"


def test_intensive_mutation_keeps_existing_admin_and_github_token_requirements(client):
    client, _ = client
    app.dependency_overrides.pop(require_admin)
    assert client.get("/admin/api/editorial/intensive").status_code == 401
    assert client.post("/admin/api/editorial/intensive/publish", json={
        "expected_main_sha": "a" * 40, "expected_draft_sha": "b" * 40,
    }).status_code == 401
    editor = IntensiveContentEditor(settings(token=""))
    with pytest.raises(HTTPException) as caught:
        editor._request("PUT", "contents/" + SOURCE_PATH, write=True)
    assert caught.value.status_code == 503
