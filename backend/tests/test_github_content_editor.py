from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.github_content_editor import GitHubContentEditor
from app.masterclass_editorial import editorial_body_text, validate_editorial_source


def settings(token: str = "token") -> Settings:
    return Settings(
        database_url="sqlite://",
        github_contents_token=token,
        github_repository="owner/repository",
        github_content_main_branch="main",
        github_content_draft_branch="content-drafts",
    )


def encoded(content: str, sha: str) -> dict:
    return {
        "sha": sha,
        "content": base64.b64encode(content.encode()).decode(),
    }


class FakeEditor(GitHubContentEditor):
    def __init__(self) -> None:
        super().__init__(settings())
        original = (
            "# Заголовок\n\n<!-- step_id: day-01-article-02 -->\n\n"
            "## Раздел\n\nОпубликовано\n"
        )
        self.files = {
            "main": {"sha": "a" * 40, "content": original},
            "content-drafts": {
                "sha": "a" * 40,
                "content": original,
            },
        }
        self.base = "a" * 40
        self.writes: list[dict] = []

    def _request(self, method, suffix, **kwargs):  # noqa: ANN001, ANN201
        query = kwargs.get("query") or {}
        payload = kwargs.get("payload") or {}
        if method == "GET" and suffix.startswith("git/ref/heads/"):
            return {"object": {"sha": "f" * 40}}
        if method == "GET" and suffix.startswith("contents/"):
            ref = query["ref"]
            item = self.files.get(ref)
            if item is None and kwargs.get("allow_missing"):
                return None
            return encoded(item["content"], item["sha"])
        if method == "GET" and suffix == "commits":
            return [{
                "sha": "c" * 40,
                "commit": {
                    "message": f"draft [base:{self.base}]",
                    "author": {"name": "Admin", "date": "2026-09-19T12:00:00Z"},
                },
            }]
        if method == "PUT" and suffix.startswith("contents/"):
            branch = payload["branch"]
            assert payload["sha"] == self.files[branch]["sha"]
            content = base64.b64decode(payload["content"]).decode()
            next_sha = ("b" if branch == "content-drafts" else "d") * 40
            self.files[branch] = {"sha": next_sha, "content": content}
            self.writes.append(payload)
            return {"content": {"sha": next_sha}, "commit": {"sha": "e" * 40}}
        raise AssertionError((method, suffix, kwargs))


def test_editorial_body_removes_only_service_wrapper() -> None:
    source = (
        "# Заголовок\n\n> Тип: **статья**\n\n"
        "<!-- step_id: day-01-article-02; day: 1 -->\n\n"
        "Вступление.\n\n## Раздел\n\nТекст.\n"
    )
    assert editorial_body_text(source) == "Вступление.\n\n## Раздел\n\nТекст.\n"
    assert validate_editorial_source("day-01-article-02", source) == []


def test_editorial_source_rejects_changed_identity_and_unsafe_link() -> None:
    with pytest.raises(ValueError, match="step_id"):
        validate_editorial_source(
            "day-01-article-02",
            "# Заголовок\n\n<!-- step_id: other -->\n\n## Раздел\n",
        )
    with pytest.raises(ValueError, match="javascript"):
        validate_editorial_source(
            "day-01-article-02",
            "# Заголовок\n\n<!-- step_id: day-01-article-02 -->\n\n"
            "## Раздел\n\n[Нельзя](javascript:alert(1))\n",
        )


def test_github_editor_saves_draft_then_publishes_same_content() -> None:
    editor = FakeEditor()
    changed = (
        "# Заголовок\n\n<!-- step_id: day-01-article-02 -->\n\n"
        "## Раздел\n\nНовый текст\n"
    )
    draft = editor.save_draft(
        "day-01-article-02",
        content=changed,
        expected_main_sha="a" * 40,
        expected_draft_sha=None,
        admin="owner@example.com",
    )
    assert draft["sha"] == "b" * 40
    assert draft["draft"] is True
    assert editor.files["main"]["content"].endswith("Опубликовано\n")
    assert editor.files["content-drafts"]["content"] == changed

    published = editor.publish(
        "day-01-article-02",
        expected_main_sha="a" * 40,
        expected_draft_sha="b" * 40,
        admin="owner@example.com",
    )
    assert published["deployment"] == "queued"
    assert editor.files["main"]["content"] == editor.files["content-drafts"]["content"]
    assert editor.writes[0]["branch"] == "content-drafts"
    assert editor.writes[1]["branch"] == "main"


def test_github_editor_does_not_create_empty_draft() -> None:
    editor = FakeEditor()
    result = editor.save_draft(
        "day-01-article-02",
        content=editor.files["main"]["content"],
        expected_main_sha="a" * 40,
        expected_draft_sha=None,
        admin="owner@example.com",
    )
    assert result["draft"] is False
    assert result["unchanged"] is True
    assert editor.writes == []


def test_github_editor_rejects_stale_main_before_draft_write() -> None:
    editor = FakeEditor()
    with pytest.raises(HTTPException) as exc:
        editor.save_draft(
            "day-01-article-02",
            content=(
                "# Заголовок\n\n<!-- step_id: day-01-article-02 -->\n\n"
                "## Раздел\n\nНовый текст\n"
            ),
            expected_main_sha="9" * 40,
            expected_draft_sha=None,
            admin="owner@example.com",
        )
    assert exc.value.status_code == 409
    assert editor.writes == []


def test_github_write_requires_token_before_network() -> None:
    editor = GitHubContentEditor(settings(token=""))
    with pytest.raises(HTTPException) as exc:
        editor._request("PUT", "contents/file.md", write=True)
    assert exc.value.status_code == 503
    assert "Contents: write" in exc.value.detail
