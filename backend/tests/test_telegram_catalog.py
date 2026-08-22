import json
from pathlib import Path

import pytest

from app.importers.telegram_catalog import (
    ensure_export_outside_repository,
    load_export,
    parse_export,
    repository_root,
)


FIXTURE = Path(__file__).parent / "fixtures" / "telegram_channel_export.json"


def test_telegram_export_groups_album_and_preserves_text_entities() -> None:
    rows, summary = parse_export(load_export(FIXTURE), "Example_Channel")

    assert summary["discovered"] == 5
    assert summary["publication_candidates"] == 3
    assert summary["albums"] == 1
    assert summary["duplicate_message_ids"] == 0
    album = rows[0]
    assert album["message_ids"] == [10, 11]
    assert album["external_id"] == "telegram:123456:10"
    assert album["canonical_url"] == "https://t.me/Example_Channel/10"
    assert album["app_deep_link"] == "tg://resolve?domain=Example_Channel&post=10"
    assert album["blocks"][0]["entities"][0]["type"] == "bold"
    assert len(album["media"]) == 2
    assert album["media"][0]["source_url"] is None
    assert album["media"][0]["metadata_json"]["omitted_from_export"] is True


def test_telegram_links_metrics_and_poll_are_normalized() -> None:
    rows, _ = parse_export(load_export(FIXTURE), "Example_Channel")

    album, linked, poll = rows
    assert album["links"][0]["link_type"] == "reference"
    assert album["links"][0]["ignored_for_generation"] is True
    assert album["metrics"]["emotions"][0]["count"] == 3
    assert linked["recommendations_status"] == "present"
    assert linked["links"][0]["link_type"] == "internal_post"
    assert linked["metrics"]["emotions"][0]["type"] == "paid"
    assert poll["blocks"][0]["poll"]["answers"] == ["A", "B"]
    assert poll["metrics"]["details_json"]["polls"][0]["total_voters"] == 7


def test_content_hash_ignores_reaction_and_poll_counter_changes() -> None:
    payload = load_export(FIXTURE)
    rows, _ = parse_export(payload, "Example_Channel")
    hashes = [row["content_hash"] for row in rows]

    changed = json.loads(json.dumps(payload))
    changed["messages"][1]["reactions"][0]["count"] = 99
    changed["messages"][4]["poll"]["total_voters"] = 100
    changed["messages"][4]["poll"]["answers"][0]["voters"] = 98
    changed_rows, _ = parse_export(changed, "Example_Channel")

    assert [row["content_hash"] for row in changed_rows] == hashes
    assert changed_rows[0]["metrics"] != rows[0]["metrics"]
    assert changed_rows[2]["metrics"] != rows[2]["metrics"]


def test_discussion_export_is_rejected_in_t1(tmp_path: Path) -> None:
    payload = load_export(FIXTURE)
    payload["type"] = "private_supergroup"
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="T2"):
        load_export(path)


def test_real_export_inside_repository_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        ensure_export_outside_repository(FIXTURE)


def test_repository_root_matches_flat_production_image() -> None:
    module = Path("/app/app/importers/telegram_catalog.py")

    assert repository_root(module) == Path("/app").resolve()
