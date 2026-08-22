from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PARSER_VERSION = "telegram-desktop-json-v1"
KNOWN_TOP_LEVEL_FIELDS = {"name", "type", "id", "messages"}
KNOWN_MESSAGE_TYPES = {"message", "service"}
KNOWN_MESSAGE_FIELDS = {
    "action",
    "actor",
    "actor_id",
    "author",
    "date",
    "date_unixtime",
    "duration",
    "duration_seconds",
    "edited",
    "edited_unixtime",
    "file",
    "file_name",
    "file_size",
    "forwarded_from",
    "forwarded_from_id",
    "from",
    "from_id",
    "height",
    "id",
    "inline_bot_buttons",
    "media_spoiler",
    "media_type",
    "message_id",
    "mime_type",
    "performer",
    "photo",
    "photo_file_size",
    "poll",
    "reactions",
    "reply_to_message_id",
    "reply_to_peer_id",
    "saved_from",
    "sticker_emoji",
    "text",
    "text_entities",
    "thumbnail",
    "thumbnail_file_size",
    "title",
    "type",
    "width",
}
REFERENCE_HOSTS = (
    "pubmed.ncbi.nlm.nih.gov",
    "doi.org",
    "jamanetwork.com",
    "thelancet.com",
    "nature.com",
    "sciencedirect.com",
)


def load_export(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise ValueError("expected a Telegram Desktop JSON export with a messages array")
    if payload.get("type") != "public_channel":
        raise ValueError("T1 accepts a public_channel export; discussion groups belong to T2")
    if not payload.get("id") or not payload.get("name"):
        raise ValueError("channel id and name are required")
    return payload


def repository_root(module_path: Path | None = None) -> Path:
    module = (module_path or Path(__file__)).resolve()
    checkout = module.parents[3]
    # The production image copies backend/ contents directly into /app, so the
    # fourth parent is filesystem root rather than the Git checkout root.
    return module.parents[2] if checkout == Path(checkout.anchor) else checkout


def ensure_export_outside_repository(path: Path) -> None:
    repository = repository_root()
    try:
        path.resolve().relative_to(repository)
    except ValueError:
        return
    raise ValueError("real Telegram exports must remain outside the Git repository")


def flatten_text(message: dict[str, Any]) -> str:
    raw = message.get("text")
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(str(item.get("text") or ""))
    return "".join(parts)


def _parsed_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _is_media(message: dict[str, Any]) -> bool:
    return "photo" in message or "file" in message


def _omitted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("(File not included")


def _album_groups(messages: list[dict[str, Any]]) -> tuple[list[list[dict[str, Any]]], int]:
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for message in messages:
        if message.get("type") != "message":
            continue
        key = (str(message.get("date_unixtime") or ""), str(message.get("from_id") or ""))
        candidates.setdefault(key, []).append(message)

    grouped_ids: set[int] = set()
    albums: list[list[dict[str, Any]]] = []
    review_clusters = 0
    for group in candidates.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda item: int(item["id"]))
        sequential = all(
            int(ordered[index]["id"]) == int(ordered[index - 1]["id"]) + 1
            for index in range(1, len(ordered))
        )
        if not sequential:
            continue
        if all(_is_media(item) for item in ordered):
            albums.append(ordered)
            grouped_ids.update(int(item["id"]) for item in ordered)
        else:
            review_clusters += 1

    singles = [
        [message]
        for message in messages
        if message.get("type") == "message" and int(message["id"]) not in grouped_ids
    ]
    return sorted(albums + singles, key=lambda group: int(group[0]["id"])), review_clusters


def _media_payload(message: dict[str, Any], position: int) -> dict[str, Any] | None:
    field = "photo" if "photo" in message else "file" if "file" in message else None
    if not field:
        return None
    raw_path = message.get(field)
    media_type = "photo" if field == "photo" else str(message.get("media_type") or "file")
    metadata = {
        "telegram_message_id": int(message["id"]),
        "export_path": None if _omitted(raw_path) else raw_path,
        "omitted_from_export": _omitted(raw_path),
        "file_name": message.get("file_name"),
        "mime_type": message.get("mime_type"),
        "file_size": message.get("photo_file_size") or message.get("file_size"),
        "width": message.get("width"),
        "height": message.get("height"),
        "duration_seconds": message.get("duration_seconds"),
        "media_spoiler": bool(message.get("media_spoiler")),
    }
    return {
        "media_type": media_type,
        "source_url": None,
        "preview_url": None,
        "position": position,
        "metadata_json": {key: value for key, value in metadata.items() if value is not None},
    }


def _same_channel_link(url: str, username: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.strip("/").split("/")
    return (
        (parsed.hostname or "").lower() in {"t.me", "telegram.me"}
        and len(path) >= 2
        and path[0].lower() == username.lower()
        and path[1].isdigit()
    )


def _classify_link(url: str) -> tuple[str, bool]:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"t.me", "telegram.me"}:
        return "telegram", False
    if hostname.endswith("pikabu.ru") and "/story/" in parsed.path:
        return "internal_post", False
    if any(hostname == item or hostname.endswith(f".{item}") for item in REFERENCE_HOSTS):
        return "reference", True
    return "other", False


def _link_payloads(
    messages: list[dict[str, Any]], channel_username: str
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for message in messages:
        for entity in message.get("text_entities") or []:
            if entity.get("type") not in {"link", "text_link"}:
                continue
            visible = str(entity.get("text") or "").strip()
            target = str(entity.get("href") or visible).strip()
            if not target:
                continue
            generic_type, ignored = _classify_link(target)
            hostname = (urlparse(target).hostname or "").lower()
            if any(hostname == item or hostname.endswith(f".{item}") for item in REFERENCE_HOSTS):
                generic_type, ignored = "reference", True
            elif _same_channel_link(target, channel_username):
                generic_type, ignored = "internal_post", False
            links.append(
                {
                    "visible_text": visible or None,
                    "wrapped_url": target,
                    "target_url": target,
                    "domain": hostname or None,
                    "link_type": generic_type,
                    "is_cta": False,
                    "ignored_for_generation": ignored,
                    "position": len(links),
                }
            )
    return links


def _poll_block(poll: dict[str, Any] | None) -> dict[str, Any] | None:
    if not poll:
        return None
    return {
        "question": poll.get("question"),
        "closed": bool(poll.get("closed")),
        "answers": [str(answer.get("text") or "") for answer in poll.get("answers") or []],
    }


def _metrics(messages: list[dict[str, Any]]) -> dict[str, Any]:
    emotions: list[dict[str, Any]] = []
    polls: list[dict[str, Any]] = []
    for message in messages:
        for reaction in message.get("reactions") or []:
            emotions.append(
                {
                    key: reaction[key]
                    for key in ("type", "emoji", "document_id", "count")
                    if key in reaction
                }
            )
        poll = message.get("poll")
        if poll:
            polls.append(
                {
                    "message_id": int(message["id"]),
                    "total_voters": poll.get("total_voters"),
                    "answers": [
                        {"text": answer.get("text"), "voters": answer.get("voters")}
                        for answer in poll.get("answers") or []
                    ],
                }
            )
    if not emotions and not polls:
        return {}
    return {"emotions": emotions, "details_json": {"polls": polls} if polls else {}}


def _title(text: str, first_id: int, media: list[dict[str, Any]], has_poll: bool) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line:
        return re.sub(r"\s+", " ", first_line)[:180]
    if has_poll:
        return f"Опрос #{first_id}"
    if media:
        return f"Медиапубликация #{first_id}"
    return f"Публикация #{first_id}"


def normalize_publication(
    messages: list[dict[str, Any]], *, channel_id: str, channel_username: str
) -> dict[str, Any]:
    first_id = int(messages[0]["id"])
    text_parts = [flatten_text(message) for message in messages]
    text_content = "\n\n".join(part for part in text_parts if part).strip()
    links = _link_payloads(messages, channel_username)
    media = [
        payload
        for position, message in enumerate(messages)
        if (payload := _media_payload(message, position)) is not None
    ]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text_content) if part.strip()]
    ending_text = paragraphs[-1] if paragraphs else None
    cta = next(
        (
            link
            for link in reversed(links)
            if not link["ignored_for_generation"]
            and ending_text
            and (link["visible_text"] or link["target_url"]) in ending_text
        ),
        None,
    )
    if cta:
        cta["is_cta"] = True
    source_updated_at = max(
        (
            _parsed_time(message.get("edited_unixtime"))
            or _parsed_time(message.get("date_unixtime"))
            for message in messages
        ),
        default=None,
    )
    blocks = []
    for message in messages:
        blocks.append(
            {
                "type": "telegram_message",
                "message_id": int(message["id"]),
                "text": flatten_text(message),
                "entities": message.get("text_entities") or [],
                "poll": _poll_block(message.get("poll")),
                "forwarded_from": message.get("forwarded_from"),
                "author": message.get("author"),
            }
        )
    body = {
        "text": text_content,
        "blocks": blocks,
        "links": links,
        "media": media,
    }
    content_hash = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "external_id": f"telegram:{channel_id}:{first_id}",
        "canonical_url": f"https://t.me/{channel_username}/{first_id}",
        "app_deep_link": f"tg://resolve?domain={channel_username}&post={first_id}",
        "title": _title(
            text_content,
            first_id,
            media,
            any(message.get("poll") for message in messages),
        ),
        "author_name": messages[0].get("author") or messages[0].get("from"),
        "published_at": _parsed_time(messages[0].get("date_unixtime")),
        "source_updated_at": source_updated_at,
        "source_tags": [
            entity["text"].lstrip("#")
            for message in messages
            for entity in message.get("text_entities") or []
            if entity.get("type") == "hashtag" and entity.get("text")
        ],
        "text_content": text_content,
        "blocks": blocks,
        "ending_text": ending_text,
        "ending_kind": "telegram" if cta and cta["link_type"] in {"telegram", "internal_post"} else "other" if cta else None,
        "cta_text": cta["visible_text"] if cta else None,
        "cta_url": cta["target_url"] if cta else None,
        "recommendations_status": "present"
        if any(link["link_type"] == "internal_post" for link in links)
        else "absent",
        "links": links,
        "media": media,
        "metrics": _metrics(messages),
        "content_hash": content_hash,
        "message_ids": [int(message["id"]) for message in messages],
    }


def parse_export(payload: dict[str, Any], channel_username: str) -> tuple[list[dict], dict]:
    username = channel_username.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise ValueError("invalid public channel username")
    messages = payload["messages"]
    ids = [int(message["id"]) for message in messages]
    duplicate_ids = len(ids) - len(set(ids))
    grouped, review_clusters = _album_groups(messages)
    rows = [
        normalize_publication(
            group,
            channel_id=str(payload["id"]),
            channel_username=username,
        )
        for group in grouped
    ]
    unknown_fields = sorted(
        {
            key
            for message in messages
            for key in message
            if key not in KNOWN_MESSAGE_FIELDS
        }
    )
    message_types = Counter(str(message.get("type") or "missing") for message in messages)
    service_actions = Counter(
        str(message.get("action") or "missing")
        for message in messages
        if message.get("type") == "service"
    )
    entity_types = Counter(
        str(entity.get("type") or "missing")
        for message in messages
        for entity in message.get("text_entities") or []
    )
    media_types = Counter(
        "photo" if "photo" in message else str(message.get("media_type") or "file")
        for message in messages
        if _is_media(message)
    )
    epochs = [int(message["date_unixtime"]) for message in messages]
    summary = {
        "parser_version": PARSER_VERSION,
        "channel": {
            "id": str(payload["id"]),
            "name": payload["name"],
            "username": username,
            "type": payload["type"],
        },
        "discovered": len(messages),
        "message_records": message_types.get("message", 0),
        "service_records": message_types.get("service", 0),
        "publication_candidates": len(rows),
        "albums": sum(1 for row in rows if len(row["message_ids"]) > 1),
        "review_clusters": review_clusters,
        "duplicate_message_ids": duplicate_ids,
        "date_from": datetime.fromtimestamp(min(epochs), tz=timezone.utc).isoformat(),
        "date_to": datetime.fromtimestamp(max(epochs), tz=timezone.utc).isoformat(),
        "message_types": dict(sorted(message_types.items())),
        "service_actions": dict(sorted(service_actions.items())),
        "entity_types": dict(sorted(entity_types.items())),
        "media_types": dict(sorted(media_types.items())),
        "unknown_top_level_fields": sorted(set(payload) - KNOWN_TOP_LEVEL_FIELDS),
        "unknown_message_fields": unknown_fields,
        "unknown_message_types": sorted(set(message_types) - KNOWN_MESSAGE_TYPES),
        "items_with_text": sum(bool(row["text_content"]) for row in rows),
        "items_with_metrics": sum(bool(row["metrics"]) for row in rows),
        "items_with_links": sum(bool(row["links"]) for row in rows),
        "edited_message_records": sum("edited_unixtime" in message for message in messages),
        "forwarded_message_records": sum("forwarded_from" in message for message in messages),
        "poll_records": sum("poll" in message for message in messages),
        "reaction_records": sum(bool(message.get("reactions")) for message in messages),
        "media_metadata_records": sum(len(row["media"]) for row in rows),
        "omitted_media_records": sum(
            media["metadata_json"].get("omitted_from_export", False)
            for row in rows
            for media in row["media"]
        ),
        "failed": duplicate_ids,
    }
    return rows, summary


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Inspect or import a Telegram Desktop public-channel JSON export"
    )
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--channel-username", required=True)
    parser.add_argument("--message-id", type=int, help="Inspect or import one publication")
    parser.add_argument("--apply", action="store_true", help="Write validated rows to PostgreSQL")
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="Confirm that the production backup/restore check was completed",
    )
    args = parser.parse_args()
    ensure_export_outside_repository(args.json_path)
    payload = load_export(args.json_path)
    rows, inspected = parse_export(payload, args.channel_username)
    if args.message_id is not None:
        rows = [row for row in rows if args.message_id in row["message_ids"]]
        inspected = {**inspected, "selected_publications": len(rows)}
    print(json.dumps(inspected, ensure_ascii=False, indent=2))
    if inspected["failed"] or not rows:
        return 2
    if not args.apply:
        return 0
    if not args.backup_confirmed:
        parser.error("--apply requires --backup-confirmed")
    from app.content_service import import_telegram_items
    from app.database import SessionLocal

    with SessionLocal() as db:
        result = import_telegram_items(
            db,
            rows,
            channel_id=str(payload["id"]),
            channel_username=args.channel_username,
            display_name=str(payload["name"]),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
