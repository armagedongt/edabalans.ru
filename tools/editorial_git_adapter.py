"""Publish the same local original through the existing Git editor, then verify runtime."""
from __future__ import annotations

import hashlib


def read(api, item: dict) -> dict:
    raw = api.request("GET", item["api_path"])
    main = raw["main"]
    return {"version": main["sha"], "text": main["content"],
            "title": item["title"], "draft": raw.get("draft"),
            "draft_base": raw.get("draft_base_main_sha"),
            "runtime_hash": raw["runtime_source"]["sha256"]}


def runtime_matches(remote: dict) -> bool:
    return remote["runtime_hash"] == hashlib.sha256(remote["text"].encode("utf-8")).hexdigest()


def publish(api, item: dict, text: str, remote: dict) -> None:
    draft = remote.get("draft")
    if draft and (draft["content"] != text or remote.get("draft_base") != remote["version"]):
        raise ValueError("В серверной ветке есть другой черновик; объедините правки через Codex")
    if draft:
        draft_sha = draft["sha"]
    else:
        saved = api.request("PUT", item["api_path"] + "/draft", {
            "content": text, "expected_main_sha": remote["version"], "expected_draft_sha": None,
        })
        draft_sha = saved["sha"]
    api.request("POST", item["api_path"] + "/publish", {
        "expected_main_sha": remote["version"], "expected_draft_sha": draft_sha,
    })
