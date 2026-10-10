"""Codex edits course structure by stable ID without copying article originals."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from tools.editorial_vault import Vault, VaultError, DEFAULT_ROOT, digest, atomic_json
from tools.editorial_media import local_images, rendered_source, unchanged


def object_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def register_article(vault, pending):
    item = pending.get("new_item")
    if item is None:
        return
    remote = vault.read(item)
    if remote["format"] != "markdown" or digest(remote["text"]) != pending["source_hash"]:
        raise VaultError("Серверный текст новой статьи не совпал с отправленной основой")
    state = vault.load()
    if item["id"] in state["items"]:
        existing = state["items"][item["id"]]
        if existing["path"] != item["path"]:
            raise VaultError("Статья уже зарегистрирована под другим рабочим файлом")
    item.update(base_version=remote["version"], base_hash=pending["source_hash"], unsupported=False)
    state["items"][item["id"]] = item
    atomic_json(vault.state_path, state)


def run(vault, config, *, apply=False, owner_edited=False):
    course = config["course_code"]
    if course not in {"masterclass-21", "calories"}:
        raise VaultError("Этот курс не входит в подключённый редактор")
    base = f"/admin/api/courses/{course}/structure"
    pending_path = vault.state_path.parent / "structure-pending.json"
    refresh_ids = ["names:" + course]
    with vault.lock():
        if pending_path.exists():
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            if pending["config_hash"] != object_hash(config):
                raise VaultError("Сначала проверьте незавершённую прежнюю структурную операцию")
            active = vault.api.request("GET", base)["active"]
            if (active["version"] == pending["expected_version"] + 1
                    and object_hash(active["manifest"]) == pending["manifest_hash"]):
                if not apply:
                    return {"status": "pending", "message": "Операция принята; --apply завершит локальную регистрацию"}
                register_article(vault, pending)
                refresh_ids.extend(pending.get("refresh_ids", []))
                pending_path.unlink()
                result = {"status": "recovered", "version": active["version"]}
            elif active["version"] == pending["expected_version"] and object_hash(active["manifest"]) == pending["before_hash"]:
                # The previous request did not commit; a fresh explicit --apply may retry.
                if not apply:
                    return {"status": "pending", "message": "Операция не принята; сначала повторите --apply"}
                pending_path.unlink()
                result = None
            else:
                raise VaultError("Версия структуры изменилась после потерянного ответа; сравните оригинал через Codex")
        else:
            result = None
        if result is None:
            operation = dict(config["operation"])
            images = []
            file = None
            original = None
            new_item = None
            if operation["type"] == "add_article":
                ident = f"course:{course}:{operation['id']}"
                relative = f"Курсы/{course}/{operation['id']}.md"
                if operation.pop("content_file") != relative:
                    raise VaultError("Новая статья должна лежать в своём постоянном файле: " + relative)
                new_item = {"id": ident, "kind": "course", "group": course, "title": operation["title"],
                            "path": relative, "format": "markdown",
                            "api_path": f"/admin/api/courses/{course}/materials/{operation['id']}"}
                file = vault.file(new_item)
                original = file.read_text(encoding="utf-8")
                if apply and not owner_edited:
                    from tools.publish_course_material import verify_publish_gate
                    gate = vault.state_path.parent / "reviews" / ident.replace(":", "_")
                    verify_publish_gate(file, gate.with_suffix(".pack.json"), gate.with_suffix(".report.json"))
                images = local_images(vault.root, file, original)
                operation["content"] = rendered_source(original, images, ident)
                unique = {image.sha256: image for image in images}
                operation["media"] = [{"name": f"{image.sha256}.{image.extension}", "alt": image.alt,
                    "content_base64": base64.b64encode(image.raw).decode(),
                    "provenance": "owner-upload; attachment: " + image.relative} for image in unique.values()]
                refresh_ids.append(ident)
            elif operation["type"] == "move":
                refresh_ids.append(f"course:{course}:{operation['id']}")
            payload = {"expected_version": config["expected_version"], "operation": operation}
            prepared = vault.api.request("POST", base + "/operations/preview", payload)
            if operation["type"] == "move":
                refresh_ids.extend(f"course:{course}:{ident}" for ident in prepared.get("moved_ids", []))
            if not apply:
                return {"status": "preview", **prepared}
            if not prepared["diff"]:
                return {"status": "clean", "version": config["expected_version"]}
            before = vault.api.request("GET", base)["active"]
            if before["version"] != config["expected_version"]:
                raise VaultError("Структура изменилась перед применением")
            if file is not None and (file.read_text(encoding="utf-8") != original or not unchanged(images)):
                raise VaultError("Текст или фотографии изменены во время preview; применение отменено")
            pending = {"config_hash": object_hash(config), "expected_version": config["expected_version"],
                       "manifest_hash": object_hash(prepared["manifest"]), "before_hash": object_hash(before["manifest"]),
                       "new_item": new_item, "source_hash": digest(operation.get("content", "")),
                       "refresh_ids": refresh_ids}
            atomic_json(pending_path, pending)
            result = vault.api.request("POST", base + "/operations/apply", payload)
            verified = vault.api.request("GET", base)["active"]
            if verified["version"] != result["version"] or object_hash(verified["manifest"]) != pending["manifest_hash"]:
                raise VaultError("Проверка принятой структуры не совпала с preview")
            register_article(vault, pending)
            pending_path.unlink()
    result["refresh"] = vault.refresh(list(dict.fromkeys(refresh_ids)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", type=Path)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--owner-edited", action="store_true")
    args = parser.parse_args()
    result = run(Vault(args.root), json.loads(args.operation.read_text(encoding="utf-8")),
                 apply=args.apply, owner_edited=args.owner_edited)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(any(row.get("status") == "error" for row in result.get("refresh", [])))


if __name__ == "__main__":
    raise SystemExit(main())
