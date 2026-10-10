"""One persistent editorial working copy, using existing versioned APIs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

DEFAULT_ROOT = Path("D:/Codex/work/edabalans-materials")
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
POPUPS = ("program", "recipes", "consultation", "calories", "training")
COURSES = ("masterclass-21", "calories")


class VaultError(RuntimeError):
    pass


def digest(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def comparable(text: str, kind: str) -> str:
    if kind == "pricing":
        from tools.editorial_pricing_adapter import normalize
        return normalize(text)
    if kind == "graph":
        from tools.editorial_graph_adapter import normalize
        return normalize(text)
    if kind in ("catalog", "names"):
        from tools.editorial_catalog_adapter import normalize
        return normalize(text)
    if kind == "bot":
        from tools.editorial_bot_adapter import normalize
        return json.dumps(normalize(text), ensure_ascii=False)
    if kind == "public":
        text = re.sub(r"^<!-- public-site-version: \d+ -->\s*", "", text)
        text = text.replace("\r", "").strip()
    return text.replace("\r\n", "\n")


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def update_if_unchanged(path: Path, expected: str | None, replacement: str) -> bool:
    """Check and write under one Windows handle that denies other writers/deletes."""
    if expected is None:
        try:
            with path.open("x", encoding="utf-8", newline="") as file:
                file.write(replacement)
            return True
        except FileExistsError:
            return False
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(path), 0xC0000000, 1, None, 3, 0x80, None)
        if handle == wintypes.HANDLE(-1).value:
            return False
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        file = os.fdopen(descriptor, "r+b")
    else:
        # CLI on Unix uses the normal cooperative file lock; desktop target is Windows.
        import fcntl
        file = path.open("r+b")
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
    with file:
        current = file.read().decode("utf-8").replace("\r\n", "\n")
        if current != expected.replace("\r\n", "\n"):
            return False
        file.seek(0)
        file.write(replacement.encode("utf-8"))
        file.truncate()
        file.flush()
    return True


class API:
    """Basic over HTTPS, or the existing SSH alias without exporting secrets."""

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not path.startswith(("/admin/api/", "/bot-api/")) or "\n" in path:
            raise VaultError("Недопустимый путь API")
        username = os.getenv("EDABALANS_ADMIN_USERNAME") or os.getenv("EDABALANS_ADMIN_USER")
        password = os.getenv("EDABALANS_ADMIN_PASSWORD")
        if username and password:
            origin = os.getenv("EDABALANS_API_URL", "https://edabalans.ru")
            if not origin.startswith("https://"):
                raise VaultError("Для пароля администратора нужен HTTPS")
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            request = Request(origin.rstrip("/") + path, method=method,
                              data=None if payload is None else json.dumps(payload).encode(),
                              headers={"Authorization": "Basic " + token, "Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=45) as response:
                    return json.load(response)
            except HTTPError as exc:
                raise VaultError(f"API {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
        # Only the normal application API; no private-directory or database access.
        script = """import sys,json,base64,urllib.request,urllib.error
from app.config import get_settings
settings=get_settings()
data=json.load(sys.stdin)
token=base64.b64encode((settings.admin_username+':'+settings.admin_password).encode()).decode()
origin='http://telegram-bot:8001' if data['path'].startswith('/bot-api/') else 'http://127.0.0.1:8000'
req=urllib.request.Request(origin+data['path'],method=data['method'],data=None if data['payload'] is None else json.dumps(data['payload']).encode(),headers={'Authorization':'Basic '+token,'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(req,timeout=45) as response: print(response.read().decode())
except urllib.error.HTTPError as error:
 print(json.dumps({'api_error':error.code,'detail':error.read().decode()}))
"""
        encoded = base64.b64encode(script.encode()).decode()
        command = "cd /opt/edabalans && docker compose exec -T backend python -c \"import base64;exec(base64.b64decode('" + encoded + "'))\""
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "edabalans-prod", command],
                                input=json.dumps({"method": method, "path": path, "payload": payload}),
                                capture_output=True, text=True, encoding="utf-8", timeout=65)
        if result.returncode:
            raise VaultError("Не удалось выполнить запрос через SSH: " + result.stderr[-1500:])
        response = json.loads(result.stdout)
        if "api_error" in response:
            raise VaultError(f"API {response['api_error']}: {response['detail']}")
        return response


class Vault:
    def __init__(self, root: Path | str = DEFAULT_ROOT, api=None):
        self.root = Path(root).resolve()
        self.api = api or API()
        self.state_path = self.root / ".publisher" / "state.json"

    def load(self) -> dict:
        if not self.state_path.exists():
            return {"schema": 1, "items": {}}
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("schema") != 1:
            raise VaultError("Неизвестная версия каталога")
        return state

    def file(self, item: dict) -> Path:
        path = (self.root / item["path"]).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise VaultError("Файл выходит за пределы редакционной папки")
        return path

    def read(self, item: dict) -> dict:
        if item["kind"] == "pricing":
            from tools.editorial_pricing_adapter import read
            return read(self.api, item)
        if item["kind"] == "graph":
            from tools.editorial_graph_adapter import read
            return read(self.api, item)
        if item["kind"] in ("catalog", "names"):
            from tools.editorial_catalog_adapter import read
            return read(self.api, item)
        if item["kind"] == "git":
            from tools.editorial_git_adapter import read
            return read(self.api, item)
        if item["kind"] == "bot":
            from tools.editorial_bot_adapter import read
            return read(self.api, item)
        raw = self.api.request("GET", item["api_path"])
        if item["kind"] in ("public", "homepage"):
            data = raw["active"]
            return {"version": data["version"], "text": data["markdown"], "title": data.get("title", "Главная")}
        if item["kind"] == "blog":
            data = raw["article"]
            return {"version": data["version"], "text": data["markdown"], "title": data["title"],
                    "published_version": data.get("published_version", 0), "editorial_status": data.get("editorial_status")}
        profile = raw.get("publication_profile", {})
        source_current = profile.get("type") == "api" and profile.get("render_profile") == "masterclass-source-current"
        return {"version": raw["version"], "text": raw.get("source_content", raw["html"]),
                "title": raw["title"], "format": raw.get("source_format", "html"),
                "source_hash": raw.get("source_hash") if source_current else None,
                "unsupported": ((raw.get("source_provenance") == "git_markdown" or raw.get("source") == "git_markdown") and not source_current) or (item["id"].startswith("course:masterclass-21:day-15-recipe-") and raw.get("recipe_authoring", {}).get("status") != "ready")}

    def media_source(self, item: dict, ident: str, text: str):
        from tools.editorial_media import local_images, rendered_source
        supported = item["kind"] in {"public", "homepage", "blog", "course", "git"}
        supported = supported and (item["kind"] != "course" or item.get("format") == "markdown")
        supported = supported and (item["kind"] != "git" or ident == "intensive" or ident.startswith("course:"))
        server_prefixes = ("assets/", "../assets/") if item["kind"] == "git" and ident.startswith("course:") else ()
        images = local_images(self.root, self.file(item), text, server_prefixes=server_prefixes) if supported else []
        return rendered_source(text, images, ident), images

    def status(self) -> list[dict]:
        rows = []
        for ident, item in self.load()["items"].items():
            path = self.file(item)
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            error = None
            try:
                wire, _ = self.media_source(item, ident, text)
                changed = digest(comparable(wire, item["kind"])) != item["base_hash"]
            except ValueError as exc:
                changed, error = True, str(exc)
            status = "conflict" if item.get("conflict") else "changed" if changed or item.get("pending_draft") or item.get("pending_runtime") or item.get("pending_conversion") else "clean"
            if error:
                status = "invalid"
            if item.get("unsupported"):
                status = "unsupported"
            rows.append({**item, "id": ident, "status": status, **({"message": error} if error else {})})
        return rows

    def discover(self) -> dict:
        items = {
            "homepage": {"kind": "homepage", "group": "Главная", "api_path": "/admin/api/public-site/homepage", "path": "Главная/Главная.md"},
            "intensive": {"kind": "git", "title": "Бесплатный интенсив", "group": "Интенсив", "api_path": "/admin/api/editorial/intensive", "path": "Интенсив/Интенсив.md"},
        }
        docs = self.api.request("GET", "/admin/api/public-site/content")["documents"]
        for document in docs:
            slug = document["slug"]
            if slug in POPUPS:
                ident = "public:" + slug
                items[ident] = {"kind": "public", "group": "Описания продуктов", "api_path": "/admin/api/public-site/content/" + slug,
                                "path": "Описания продуктов/" + slug + ".md"}
        articles = self.api.request("GET", "/admin/api/blog/articles")["articles"]
        for article in articles:
            slug = article["slug"]
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                raise VaultError("Недопустимый slug статьи")
            items["blog:" + slug] = {"kind": "blog", "group": "Блог", "api_path": "/admin/api/blog/articles/" + slug,
                                     "path": "Блог/" + slug + ".md"}
        for course in COURSES:
            materials = self.api.request("GET", f"/admin/api/courses/{course}/materials")["materials"]
            for material in materials:
                step = material["step_id"]
                if not re.fullmatch(r"[a-z0-9-]+", step):
                    raise VaultError("Недопустимый ID материала")
                item = {"kind": "course", "group": course, "title": material["title"],
                    "api_path": f"/admin/api/courses/{course}/materials/{step}",
                    "path": f"Курсы/{course}/{step}.md"}
                profile = material.get("publication_profile", {})
                if profile.get("type") == "git":
                    item.update(kind="git", api_path=profile["api_path"], source_path=profile["source_path"])
                items[f"course:{course}:{step}"] = item
        from tools.editorial_bot_adapter import discover
        items.update(discover(self.api))
        from tools.editorial_email_adapter import discover as discover_emails
        items.update(discover_emails(self.api))
        from tools.editorial_catalog_adapter import discover as discover_catalog
        items.update(discover_catalog(self.api))
        from tools.editorial_graph_adapter import discover as discover_graphs
        items.update(discover_graphs(self.api))
        return items

    def refresh(self, ids: list[str] | None = None) -> list[dict]:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock():
            state = self.load()
            discovered = self.discover()
            results = []
            for ident, seed in discovered.items():
                if ids is not None and ident not in ids:
                    continue
                item = state["items"].get(ident, seed)
                try:
                    if item.get("pending_conversion"):
                        raise VaultError("Сначала завершите convert-markdown --apply для этого материала")
                    if item["kind"] == "course" and seed["kind"] == "git":
                        if any(item.get(key) for key in ("pending_hash", "pending_draft", "pending_runtime")):
                            raise VaultError("Сначала разрешите незавершённую публикацию материала через Codex")
                        replacement = {**item, "kind": "git", "api_path": seed["api_path"],
                                       "source_path": seed["source_path"], "title": seed["title"]}
                        remote = self.read({**replacement, "id": ident})
                        path = self.file(item)
                        local = path.read_text(encoding="utf-8") if path.exists() else None
                        remote_hash = digest(comparable(remote["text"], "git"))
                        dirty = local is not None and digest(comparable(local, "course")) != item["base_hash"]
                        if dirty and remote_hash != item["base_hash"]:
                            item["conflict"] = True
                            state["items"][ident] = item
                            atomic_json(self.state_path, state)
                            raise VaultError("Оригинал материала изменился; локальный черновик сохранён для объединения через Codex")
                        if not dirty and not update_if_unchanged(path, local, remote["text"]):
                            raise VaultError("Материал изменён во время обновления; локальные правки сохранены")
                        from tools.editorial_git_adapter import runtime_matches
                        replacement.update(base_version=remote["version"], base_hash=remote_hash, conflict=False,
                                           format="markdown", unsupported=False, pending_runtime=not runtime_matches(remote))
                        state["items"][ident] = replacement
                        atomic_json(self.state_path, state)
                        results.append({"id": ident, "status": "draft" if dirty else "clean"})
                        continue
                    if item["kind"] == "git" and ident.startswith("course:"):
                        item = {**item, "title": seed["title"]}
                    remote = self.read({**item, "id": ident})
                    path = self.file(item)
                    local = path.read_text(encoding="utf-8") if path.exists() else None
                    remote_hash = digest(comparable(remote["text"], item["kind"]))
                    if item["kind"] == "pricing" and "base_hash" in item and item.get("format") != "pricing-json-v1":
                        from tools.editorial_catalog_adapter import normalize as legacy_normalize
                        if any(item.get(key) for key in ("pending_hash", "pending_draft", "pending_runtime")):
                            raise VaultError("Сначала разрешите незавершённую публикацию старого файла цен через Codex")
                        if local is not None and digest(legacy_normalize(local)) != item["base_hash"]:
                            raise VaultError("Правки старого файла цен сохранены; Codex поможет перенести их в действующий оригинал")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if not update_if_unchanged(path, local, remote["text"]):
                            raise VaultError("Файл цен изменён во время обновления; локальные правки сохранены")
                        item.update(base_version=remote["version"], base_hash=remote_hash, conflict=False,
                                    title=remote["title"], format=remote["format"], unsupported=False)
                        state["items"][ident] = item
                        atomic_json(self.state_path, state)
                        results.append({"id": ident, "status": "clean"})
                        continue
                    wire, images = self.media_source(item, ident, local) if local is not None else (None, [])
                    local_hash = digest(comparable(wire, item["kind"])) if wire is not None else None
                    if type(remote["version"]) is int and item.get("pending_hash") == remote_hash and remote["version"] == item.get("pending_base_version", -2) + 1:
                        item.update(base_version=remote["version"], base_hash=remote_hash)
                        if item["kind"] == "blog":
                            item["pending_draft"] = remote["version"]
                        item.pop("pending_hash", None)
                        item.pop("pending_base_version", None)
                    if "base_hash" not in item and local is not None:
                        raise VaultError("В папке уже есть незарегистрированный файл; сохранён без замены")
                    dirty = "base_hash" in item and local_hash != item["base_hash"]
                    if dirty and local_hash != remote_hash:
                        item["conflict"] = remote["version"] != item["base_version"] or remote_hash != item["base_hash"]
                        results.append({"id": ident, "status": "conflict" if item["conflict"] else "draft", "message": "Локальные правки сохранены"})
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        from tools.editorial_media import working_source
                        replacement = working_source(remote["text"], local or "", images, ident)
                        if not update_if_unchanged(path, local, replacement):
                            raise VaultError("Файл изменён или занят редактором; локальные правки сохранены, повторите обновление")
                        item.update(base_version=remote["version"], base_hash=remote_hash, conflict=False)
                        if item["kind"] == "blog" and remote.get("editorial_status") == "moderation":
                            item["pending_draft"] = remote["version"]
                        else:
                            item.pop("pending_draft", None)
                        results.append({"id": ident, "status": "clean"})
                    item.update(title=remote["title"], format=remote.get("format", "markdown"), unsupported=remote.get("unsupported", False))
                    if item["kind"] == "git":
                        from tools.editorial_git_adapter import runtime_matches
                        item["pending_runtime"] = not runtime_matches(remote)
                    if item["kind"] == "graph":
                        item["editorial_owned"] = remote["editorial_owned"]
                        if remote.get("pending_draft"):
                            item["pending_draft"] = remote["pending_draft"]
                    for key in ("usages", "allowed_variables"):
                        if key in remote:
                            item[key] = remote[key]
                    state["items"][ident] = item
                    atomic_json(self.state_path, state)
                except Exception as exc:
                    results.append({"id": ident, "status": "error", "message": str(exc)})
            self.catalog(state)
            return results

    def catalog(self, state: dict) -> None:
        lines = ["# Материалы сайта", "", "Оригиналы рабочих правок лежат в этой папке. Ссылки открывают сами файлы.", ""]
        for ident, item in state["items"].items():
            title = item["title"].replace("[", "\\[").replace("]", "\\]")
            lines.append(f"- [{title}](<{item['path']}>) — {item['group']} · `{ident}`")
        (self.root / "Каталог.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def lock(self):
        from contextlib import contextmanager

        @contextmanager
        def locked():
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            path = self.state_path.parent / "operation.lock"
            try:
                handle = path.open("x")
            except FileExistsError as exc:
                raise VaultError("Уже выполняется обновление или публикация этой папки") from exc
            try:
                with handle:
                    handle.write(str(os.getpid()))
                yield
            finally:
                path.unlink()
        return locked()

    def publish(self, ids: list[str], *, owner_edited: bool = False) -> list[dict]:
        results = []
        with self.lock():
            state = self.load()
            for ident in dict.fromkeys(ids):
                try:
                    item = state["items"][ident]
                    if item.get("pending_conversion"):
                        raise VaultError("Сначала завершите convert-markdown --apply для этого материала")
                    if item.get("unsupported"):
                        raise VaultError("Особый материал: требуется его действующий маршрут через Codex")
                    path = self.file(item)
                    text = path.read_text(encoding="utf-8")
                    wire, images = self.media_source(item, ident, text)
                    content_hash = digest(comparable(wire, item["kind"]))
                    remote = self.read({**item, "id": ident})
                    remote_hash = digest(comparable(remote["text"], item["kind"]))
                    if type(remote["version"]) is int and item.get("pending_hash") == remote_hash and remote["version"] == item.get("pending_base_version", -2) + 1:
                        item.update(base_version=remote["version"], base_hash=remote_hash)
                        if item["kind"] == "blog":
                            item["pending_draft"] = remote["version"]
                        item.pop("pending_hash", None)
                        item.pop("pending_base_version", None)
                    activate_graph = item["kind"] == "graph" and not remote["editorial_owned"]
                    if remote_hash == content_hash and item["kind"] != "blog" and not activate_graph:
                        item.update(base_version=remote["version"], base_hash=remote_hash, conflict=False)
                        if item["kind"] == "graph":
                            item["editorial_owned"] = remote["editorial_owned"]
                            if remote.get("pending_draft"):
                                item["pending_draft"] = remote["pending_draft"]
                            else:
                                item.pop("pending_draft", None)
                        if item["kind"] == "git":
                            from tools.editorial_git_adapter import runtime_matches
                            item["pending_runtime"] = not runtime_matches(remote)
                        queued = item.get("pending_runtime", False)
                        results.append({"id": ident, "status": "queued" if queued else "clean", "message": "Выпуск ожидает обновления сервера" if queued else "Уже опубликовано"})
                        atomic_json(self.state_path, state)
                        continue
                    if remote["version"] != item["base_version"] or remote_hash != item["base_hash"]:
                        if not (item["kind"] == "blog" and item.get("pending_draft") == remote["version"] and remote_hash == content_hash):
                            item["conflict"] = True
                            raise VaultError("Серверная редакция изменилась. Локальный файл сохранён; объедините правки через Codex")
                    if content_hash == item["base_hash"] and not item.get("pending_draft") and not activate_graph:
                        results.append({"id": ident, "status": "clean", "message": "Нет изменений"})
                        continue
                    if item["kind"] == "course" or (item["kind"] == "git" and ident.startswith("course:")):
                        # Codex-authored work uses its writer gate; the owner's manual edits
                        # are published by his explicit desktop action without an AI review.
                        if not owner_edited:
                            from tools.publish_course_material import verify_publish_gate
                            gate = self.state_path.parent / "reviews" / ident.replace(":", "_")
                            verify_publish_gate(path, gate.with_suffix(".pack.json"), gate.with_suffix(".report.json"))
                        if path.read_text(encoding="utf-8") != text:
                            raise VaultError("Материал изменён во время проверки; отправка отменена")
                    from tools.editorial_media import upload, unchanged, working_source
                    upload(self.api, ident, images, existing_source=remote["text"])
                    if path.read_text(encoding="utf-8") != text or not unchanged(images):
                        raise VaultError("Текст или картинка изменены во время загрузки; публикация отменена")
                    if item["kind"] == "course":
                        item.update(pending_hash=content_hash, pending_base_version=remote["version"])
                        atomic_json(self.state_path, state)
                        payload = {"expected_version": remote["version"], "content": wire, "format": item["format"]}
                        if remote["version"] == 0 and remote.get("source_hash"):
                            payload["expected_source_hash"] = remote["source_hash"]
                        self.api.request("PUT", item["api_path"], payload)
                    elif item["kind"] in ("public", "homepage"):
                        item.update(pending_hash=content_hash, pending_base_version=remote["version"])
                        atomic_json(self.state_path, state)
                        self.api.request("PUT", item["api_path"], {"expected_version": remote["version"], "markdown": wire})
                    elif item["kind"] == "bot":
                        from tools.editorial_bot_adapter import publish
                        item.update(pending_hash=content_hash, pending_base_version=remote["version"])
                        atomic_json(self.state_path, state)
                        publish(self.api, item, text, remote["version"])
                    elif item["kind"] == "git":
                        from tools.editorial_git_adapter import publish
                        publish(self.api, item, wire, remote)
                    elif item["kind"] == "graph":
                        from tools.editorial_graph_adapter import publish
                        publish(self.api, item, text, remote)
                    elif item["kind"] == "pricing":
                        from tools.editorial_pricing_adapter import publish
                        publish(self.api, item, text, remote)
                    elif item["kind"] in ("catalog", "names"):
                        from tools.editorial_catalog_adapter import publish
                        item.update(pending_hash=content_hash, pending_base_version=remote["version"])
                        atomic_json(self.state_path, state)
                        publish(self.api, {**item, "id": ident}, text, remote["version"])
                    else:
                        if remote_hash != content_hash:
                            item.update(pending_hash=content_hash, pending_base_version=remote["version"])
                            atomic_json(self.state_path, state)
                            saved = self.api.request("PATCH", item["api_path"] + "/text", {"expected_version": remote["version"], "markdown": wire})
                            item["pending_draft"] = saved["article"]["version"]
                            item.update(base_version=saved["article"]["version"], base_hash=content_hash)
                            atomic_json(self.state_path, state)
                        else:
                            item["pending_draft"] = remote["version"]
                        self.api.request("POST", item["api_path"] + "/publish", {"expected_version": item["pending_draft"], "confirm": True})
                    verified = self.read({**item, "id": ident})
                    if digest(comparable(verified["text"], item["kind"])) != content_hash:
                        raise VaultError("Проверка после публикации не совпала с отправленным текстом")
                    if item["kind"] == "blog" and verified.get("editorial_status") != "published":
                        raise VaultError("Черновик сохранён, но публичная версия ещё не подтверждена")
                    # A simultaneous Obsidian edit is left intact and remains changed.
                    update_if_unchanged(path, text, working_source(verified["text"], text, images, ident))
                    item.update(base_version=verified["version"], base_hash=content_hash, conflict=False)
                    item.pop("pending_draft", None)
                    item.pop("pending_hash", None)
                    item.pop("pending_base_version", None)
                    if item["kind"] == "graph":
                        item["editorial_owned"] = verified["editorial_owned"]
                    if item["kind"] == "git":
                        from tools.editorial_git_adapter import runtime_matches
                        item["pending_runtime"] = not runtime_matches(verified)
                    queued = item.get("pending_runtime", False)
                    results.append({"id": ident, "status": "queued" if queued else "published", "message": "Принято; выпуск ожидает обновления сервера" if queued else "Опубликовано и проверено"})
                except (Exception, SystemExit) as exc:
                    results.append({"id": ident, "status": "error", "message": str(exc) + ". При сетевой ошибке сначала обновите статус; не повторяйте вслепую"})
                atomic_json(self.state_path, state)
        return results


    def convert_markdown(self, ids: list[str], *, apply: bool = False) -> list[dict]:
        results = []
        with self.lock():
            state = self.load()
            for ident in ids:
                try:
                    item = state["items"].get(ident)
                    if not item or item["kind"] != "course" or item.get("unsupported"):
                        raise VaultError("Конверсия доступна обычному материалу курса")
                    path = self.file(item)
                    local = path.read_text(encoding="utf-8")
                    if digest(local) != item["base_hash"] or any(item.get(key) for key in (
                            "conflict", "pending_hash", "pending_draft", "pending_runtime")):
                        raise VaultError("Сначала разрешите локальный черновик или незавершённую публикацию")
                    pending = item.get("pending_conversion")
                    prepared = self.api.request("GET", item["api_path"] + "/markdown")
                    if prepared["already_markdown"]:
                        remote = self.read({**item, "id": ident})
                        if item.get("format") == "markdown" and digest(remote["text"]) == item["base_hash"]:
                            results.append({"id": ident, "status": "clean"})
                            continue
                        if not pending or digest(remote["text"]) != pending["markdown_hash"]:
                            raise VaultError("Серверный оригинал изменён; сначала обновите файл с сервера")
                    else:
                        remote = self.read({**item, "id": ident})
                        if remote["version"] != item["base_version"] or digest(remote["text"]) != item["base_hash"]:
                            raise VaultError("Серверный оригинал изменён; конверсия отменена")
                        if not apply:
                            results.append({"id": ident, "status": "preview", **prepared})
                            continue
                        item["pending_conversion"] = {"markdown_hash": digest(prepared["markdown"])}
                        atomic_json(self.state_path, state)
                        self.api.request("POST", item["api_path"] + "/markdown", {
                            "expected_version": prepared["expected_version"],
                            "expected_html_sha256": prepared["html_sha256"],
                        })
                        remote = self.read({**item, "id": ident})
                    if not apply:
                        results.append({"id": ident, "status": "pending", "message": "Повторите с --apply для восстановления локального файла"})
                        continue
                    if remote["format"] != "markdown" or digest(remote["text"]) != item["pending_conversion"]["markdown_hash"]:
                        raise VaultError("Серверный Markdown не совпал с проверенной конверсией")
                    if not update_if_unchanged(path, local, remote["text"]):
                        raise VaultError("Файл изменён во время конверсии; локальные правки сохранены")
                    item.update(base_version=remote["version"], base_hash=digest(remote["text"]), format="markdown")
                    item.pop("pending_conversion", None)
                    atomic_json(self.state_path, state)
                    results.append({"id": ident, "status": "converted"})
                except Exception as exc:
                    results.append({"id": ident, "status": "error", "message": str(exc)})
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Единая рабочая папка Obsidian и Codex")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("refresh")
    refresh.add_argument("ids", nargs="*")
    commands.add_parser("status")
    publish = commands.add_parser("publish")
    publish.add_argument("--owner-edited", action="store_true", help="Опубликовать готовые правки Сергея из Obsidian без ИИ-редактуры")
    publish.add_argument("ids", nargs="+")
    conversion = commands.add_parser("convert-markdown")
    conversion.add_argument("ids", nargs="+")
    conversion.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    vault = Vault(args.root)
    if args.command == "publish":
        result = vault.publish(args.ids, owner_edited=args.owner_edited)
    elif args.command == "convert-markdown":
        result = vault.convert_markdown(args.ids, apply=args.apply)
    elif args.command == "refresh":
        result = vault.refresh(args.ids or None)
    else:
        result = vault.status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(any(row.get("status") == "error" for row in result))


if __name__ == "__main__":
    sys.exit(main())
