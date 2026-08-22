import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from app.content_service import (
    classify_link,
    decode_pikabu_redirect,
    normalized_payload,
    telegram_app_deep_link,
)
from app.database import Base
from app.main import app


def sample() -> dict:
    return {
        "external_id": "14183275",
        "canonical_url": "https://pikabu.ru/story/example_14183275",
        "title": "Тестовый пост",
        "text": "Основной текст\n\nСергей Воронцов. Телеграм-канал",
        "blocks": [{"type": "p", "text": "Основной текст"}],
        "ending_text": "Сергей Воронцов. Телеграм-канал",
        "cta_url": "https://pikabu.ru/story/example_14183275?u=https%3A%2F%2Ft.me%2FFitness_Talks%2F260",
        "links": [
            {
                "text": "Канал",
                "wrapped_url": "https://pikabu.ru/story/example_14183275?u=https%3A%2F%2Ft.me%2FFitness_Talks%2F260",
            },
            {"text": "Исследование", "url": "https://jamanetwork.com/example"},
        ],
        "media": [
            {"type": "image", "source_url": "https://cs20.pikabu.ru/image.jpg"},
            {"type": "video", "source_url": "https://pikabu.ru/video/story/example/1"},
        ],
    }


def test_normalized_payload_keeps_original_and_media_urls() -> None:
    result = normalized_payload(sample())
    assert result["canonical_url"].endswith("_14183275")
    assert [item["source_url"] for item in result["media"]] == [
        "https://cs20.pikabu.ru/image.jpg",
        "https://pikabu.ru/video/story/example/1",
    ]
    assert "content" not in result["media"][0]


def test_pikabu_redirect_is_decoded_and_reference_is_ignored() -> None:
    result = normalized_payload(sample())
    assert result["cta_url"] == "https://t.me/Fitness_Talks/260"
    assert result["links"][0]["target_url"] == "https://t.me/Fitness_Talks/260"
    assert result["links"][0]["link_type"] == "telegram"
    assert result["links"][0]["is_cta"] is True
    assert result["links"][1]["link_type"] == "reference"
    assert result["links"][1]["ignored_for_generation"] is True


def test_canonical_url_must_match_story_id() -> None:
    payload = sample()
    payload["canonical_url"] = "https://pikabu.ru/story/other_999"
    with pytest.raises(ValueError, match="canonical_url"):
        normalized_payload(payload)


def test_redirect_and_link_helpers() -> None:
    wrapped = "https://pikabu.ru/story/example_1?u=https%3A%2F%2Ft.me%2Fchannel%2F1"
    assert decode_pikabu_redirect(wrapped) == "https://t.me/channel/1"
    assert classify_link("https://doi.org/10.1/example") == ("reference", True)


def test_telegram_app_deep_link_is_derived_from_public_post_url() -> None:
    assert telegram_app_deep_link(
        "https://t.me/Fitness_Talks/466", "telegram"
    ) == "tg://resolve?domain=Fitness_Talks&post=466"
    assert telegram_app_deep_link("https://pikabu.ru/story/example_1", "pikabu") is None


def test_content_tables_are_registered() -> None:
    assert {
        "content_sources",
        "content_items",
        "content_item_versions",
        "content_media",
        "content_links",
        "content_metric_snapshots",
        "content_import_runs",
    }.issubset(Base.metadata.tables)


def test_shared_media_and_metric_schema_supports_future_sources() -> None:
    media = Base.metadata.tables["content_media"]
    metrics = Base.metadata.tables["content_metric_snapshots"]

    assert media.c.source_url.nullable is True
    assert any(
        constraint.name == "uq_content_media_position"
        for constraint in media.constraints
    )
    assert "details_json" in metrics.c


def test_content_api_requires_admin_session() -> None:
    response = TestClient(app, base_url="https://testserver").get("/admin/api/content/summary")
    assert response.status_code == 401
