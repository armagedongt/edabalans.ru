from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException

from app.config import Settings, get_settings
from app.masterclass_editorial import editable_material_path, validate_editorial_source


API_ROOT = "https://api.github.com"
BASE_SHA_RE = re.compile(r"\[base:([0-9a-f]{40,64})\]")


def audit_actor(value: str) -> str:
    return " ".join(value.split())[:120] or "admin"


class GitHubContentEditor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def repository(self) -> str:
        return self.settings.github_repository.strip()

    @property
    def main_branch(self) -> str:
        return self.settings.github_content_main_branch.strip() or "main"

    @property
    def draft_branch(self) -> str:
        return self.settings.github_content_draft_branch.strip() or "content-drafts"

    @property
    def connected(self) -> bool:
        return bool(self.settings.github_contents_token.strip())

    def _url(self, suffix: str, query: dict[str, str] | None = None) -> str:
        url = f"{API_ROOT}/repos/{self.repository}/{suffix.lstrip('/')}"
        return f"{url}?{urlencode(query)}" if query else url

    def _request(
        self,
        method: str,
        suffix: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        allow_missing: bool = False,
        write: bool = False,
    ) -> Any:
        if not self.repository or "/" not in self.repository:
            raise HTTPException(503, "GitHub-репозиторий редактора не настроен")
        if write and not self.connected:
            raise HTTPException(
                503,
                "Редактор подключён только для чтения. Добавьте GitHub token с правом Contents: write",
            )
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "edabalans-admin-content-editor",
        }
        if self.connected:
            headers["Authorization"] = (
                f"Bearer {self.settings.github_contents_token.strip()}"
            )
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._url(suffix, query), data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed GitHub API
                raw = response.read()
        except HTTPError as exc:
            if allow_missing and exc.code == 404:
                return None
            if exc.code in {409, 422}:
                raise HTTPException(
                    409,
                    "Файл или ветка уже изменились в GitHub. Обновите редактор и повторите",
                ) from exc
            if exc.code in {401, 403}:
                raise HTTPException(
                    503,
                    "GitHub отклонил доступ редактора. Проверьте token и право Contents: write",
                ) from exc
            raise HTTPException(502, f"GitHub API вернул ошибку {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise HTTPException(502, "GitHub сейчас недоступен") from exc
        return json.loads(raw.decode("utf-8")) if raw else {}

    @staticmethod
    def _decoded(file_payload: dict[str, Any]) -> str:
        try:
            return base64.b64decode(file_payload["content"]).decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(502, "GitHub вернул повреждённый Markdown-файл") from exc

    def _file(
        self, path: str, ref: str, *, allow_missing: bool = False
    ) -> dict[str, Any] | None:
        payload = self._request(
            "GET",
            f"contents/{quote(path, safe='/')}",
            query={"ref": ref},
            allow_missing=allow_missing,
        )
        if payload is None:
            return None
        return {
            "path": path,
            "sha": str(payload["sha"]),
            "content": self._decoded(payload),
        }

    def _latest_path_commit(self, path: str, branch: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "commits",
            query={"sha": branch, "path": path, "per_page": "1"},
            allow_missing=True,
        )
        return rows[0] if rows else None

    def _ensure_draft_branch(self) -> None:
        existing = self._request(
            "GET",
            f"git/ref/heads/{quote(self.draft_branch, safe='')}",
            allow_missing=True,
        )
        if existing is not None:
            return
        main = self._request(
            "GET", f"git/ref/heads/{quote(self.main_branch, safe='')}"
        )
        self._request(
            "POST",
            "git/refs",
            payload={
                "ref": f"refs/heads/{self.draft_branch}",
                "sha": main["object"]["sha"],
            },
            write=True,
        )

    def load(self, step_id: str) -> dict[str, Any]:
        path = editable_material_path(step_id)
        main = self._file(path, self.main_branch)
        draft = self._file(path, self.draft_branch, allow_missing=True)
        base_sha = None
        if draft and draft["sha"] != main["sha"]:
            commit = self._latest_path_commit(path, self.draft_branch)
            message = ((commit or {}).get("commit") or {}).get("message", "")
            match = BASE_SHA_RE.search(message)
            base_sha = match.group(1) if match else None
        else:
            draft = None
        return {
            "ok": True,
            "step_id": step_id,
            "path": path,
            "connected": self.connected,
            "main": main,
            "draft": draft,
            "draft_base_main_sha": base_sha,
        }

    def _put(
        self,
        *,
        path: str,
        branch: str,
        content: str,
        current_sha: str,
        message: str,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"contents/{quote(path, safe='/')}",
            payload={
                "message": message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
                "sha": current_sha,
            },
            write=True,
        )

    def save_draft(
        self,
        step_id: str,
        *,
        content: str,
        expected_main_sha: str,
        expected_draft_sha: str | None,
        admin: str,
    ) -> dict[str, Any]:
        path = editable_material_path(step_id)
        validate_editorial_source(step_id, content)
        self._ensure_draft_branch()
        main = self._file(path, self.main_branch)
        draft = self._file(path, self.draft_branch)
        if main["sha"] != expected_main_sha:
            raise HTTPException(409, "Опубликованный файл изменился. Обновите редактор")
        if expected_draft_sha and draft["sha"] != expected_draft_sha:
            raise HTTPException(409, "Черновик уже изменился. Обновите редактор")
        if not expected_draft_sha and draft["sha"] != main["sha"]:
            raise HTTPException(409, "В GitHub уже есть другой черновик. Обновите редактор")
        if content == main["content"] and draft["sha"] == main["sha"]:
            return {
                "ok": True,
                "sha": None,
                "main_sha": main["sha"],
                "draft": False,
                "unchanged": True,
            }
        result = self._put(
            path=path,
            branch=self.draft_branch,
            content=content,
            current_sha=draft["sha"],
            message=(
                f"draft(masterclass): {step_id} by {audit_actor(admin)} "
                f"[base:{main['sha']}]"
            ),
        )
        return {
            "ok": True,
            "sha": result["content"]["sha"],
            "main_sha": main["sha"],
            "draft": content != main["content"],
        }

    def publish(
        self,
        step_id: str,
        *,
        expected_main_sha: str,
        expected_draft_sha: str,
        admin: str,
    ) -> dict[str, Any]:
        path = editable_material_path(step_id)
        main = self._file(path, self.main_branch)
        draft = self._file(path, self.draft_branch, allow_missing=True)
        if main["sha"] != expected_main_sha:
            raise HTTPException(409, "Опубликованный файл изменился. Обновите редактор")
        if draft is None or draft["sha"] != expected_draft_sha:
            raise HTTPException(409, "Черновик изменился или отсутствует. Обновите редактор")
        try:
            validate_editorial_source(step_id, draft["content"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        commit = self._latest_path_commit(path, self.draft_branch)
        message = ((commit or {}).get("commit") or {}).get("message", "")
        match = BASE_SHA_RE.search(message)
        if match and match.group(1) != main["sha"]:
            raise HTTPException(409, "Основа черновика устарела. Сначала сверите изменения")
        result = self._put(
            path=path,
            branch=self.main_branch,
            content=draft["content"],
            current_sha=main["sha"],
            message=f"content(masterclass): publish {step_id} by {audit_actor(admin)}",
        )
        return {
            "ok": True,
            "sha": result["content"]["sha"],
            "commit_sha": result["commit"]["sha"],
            "deployment": "queued",
        }

    def history(self, step_id: str, *, limit: int = 20) -> dict[str, Any]:
        path = editable_material_path(step_id)
        rows = self._request(
            "GET",
            "commits",
            query={
                "sha": self.main_branch,
                "path": path,
                "per_page": str(max(1, min(limit, 50))),
            },
        )
        return {
            "ok": True,
            "history": [
                {
                    "sha": row["sha"],
                    "message": row["commit"]["message"],
                    "author": row["commit"]["author"]["name"],
                    "date": row["commit"]["author"]["date"],
                    "active": index == 0,
                }
                for index, row in enumerate(rows)
            ],
        }

    def rollback(
        self,
        step_id: str,
        *,
        commit_sha: str,
        expected_main_sha: str,
        admin: str,
    ) -> dict[str, Any]:
        path = editable_material_path(step_id)
        main = self._file(path, self.main_branch)
        if main["sha"] != expected_main_sha:
            raise HTTPException(409, "Опубликованный файл изменился. Обновите редактор")
        old = self._file(path, commit_sha)
        try:
            validate_editorial_source(step_id, old["content"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        result = self._put(
            path=path,
            branch=self.main_branch,
            content=old["content"],
            current_sha=main["sha"],
            message=(
                f"content(masterclass): rollback {step_id} to {commit_sha[:12]} "
                f"by {audit_actor(admin)}"
            ),
        )
        return {
            "ok": True,
            "sha": result["content"]["sha"],
            "commit_sha": result["commit"]["sha"],
            "deployment": "queued",
        }
