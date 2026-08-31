import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.blog_content import (
    add_heading_anchors,
    load_blog_catalog,
    render_blog_component,
)


def write_catalog(root: Path, *, related: list[str] | None = None, cta: str = "intensive") -> None:
    (root / "articles").mkdir(parents=True)
    (root / "media").mkdir()
    (root / "media" / "hero.jpg").write_bytes(b"image")
    (root / "media" / "card.jpg").write_bytes(b"image")
    source_ids = ["1", "2", "3", "4"]
    entries = []
    for index, source_id in enumerate(source_ids):
        body_cta = cta if source_id == "1" else "telegram"
        (root / "articles" / f"{source_id}.md").write_text(
            "## Первый раздел\n\nТекст.\n\n## Второй раздел\n\nТекст.\n\n"
            f"## Третий раздел\n\nТекст.\n\nblog_cta(\n{body_cta}\n)",
            encoding="utf-8",
        )
        article_related = (
            related
            if source_id == "1" and related is not None
            else [item for item in source_ids if item != source_id][:3]
        )
        entries.append(
            {
                "source_id": source_id,
                "slug": f"article-{source_id}",
                "title": f"Статья {source_id}",
                "excerpt": "Короткое описание статьи.",
                "category": "Похудение",
                "body_file": f"{source_id}.md",
                "hero": {
                    "file": "hero.jpg",
                    "alt": "Обложка",
                    "provenance": "owner source",
                },
                "card": {
                    "file": "card.jpg",
                    "alt": "Обложка карточки",
                    "provenance": "owner source",
                },
                "related_source_ids": article_related,
                "cta": cta if source_id == "1" else "telegram",
                "status": "published",
                "media": [],
            }
        )
    (root / "manifest.json").write_text(
        json.dumps({"version": 1, "articles": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_catalog_rejects_self_related_link(tmp_path: Path) -> None:
    write_catalog(tmp_path, related=["1", "2", "3"])

    with pytest.raises(ValueError, match="cannot relate to itself"):
        load_blog_catalog(tmp_path)


def test_catalog_rejects_unknown_cta(tmp_path: Path) -> None:
    write_catalog(tmp_path, cta="unknown")

    with pytest.raises(ValueError, match="unknown public CTA"):
        load_blog_catalog(tmp_path)


def test_catalog_rejects_missing_required_media(tmp_path: Path) -> None:
    write_catalog(tmp_path)
    (tmp_path / "media" / "hero.jpg").unlink()

    with pytest.raises(ValueError, match="missing blog media"):
        load_blog_catalog(tmp_path)


def test_catalog_requires_dedicated_card_metadata(tmp_path: Path) -> None:
    write_catalog(tmp_path)
    manifest = tmp_path / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["articles"][0].pop("card")
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="must have card metadata"):
        load_blog_catalog(tmp_path)


def test_catalog_rejects_missing_dedicated_card_file(tmp_path: Path) -> None:
    write_catalog(tmp_path)
    (tmp_path / "media" / "card.jpg").unlink()

    with pytest.raises(ValueError, match="missing blog media: card.jpg"):
        load_blog_catalog(tmp_path)


def test_dedicated_card_file_is_added_to_media_whitelist(tmp_path: Path) -> None:
    write_catalog(tmp_path)

    assert load_blog_catalog(tmp_path).allowed_media == frozenset({"hero.jpg", "card.jpg"})


def test_catalog_rejects_external_image_hotlink(tmp_path: Path) -> None:
    write_catalog(tmp_path)
    body = tmp_path / "articles" / "1.md"
    body.write_text(body.read_text(encoding="utf-8") + "\n\n![](https://example.com/image.jpg)", encoding="utf-8")

    with pytest.raises(ValueError, match="hotlinks an external image"):
        load_blog_catalog(tmp_path)


def test_catalog_rejects_arbitrary_raw_html(tmp_path: Path) -> None:
    write_catalog(tmp_path)
    body = tmp_path / "articles" / "1.md"
    body.write_text(
        body.read_text(encoding="utf-8") + '\n\n<div onclick="track()">raw</div>',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contains forbidden HTML"):
        load_blog_catalog(tmp_path)


def test_catalog_resolves_directives_against_manifest_cta(tmp_path: Path) -> None:
    write_catalog(tmp_path)
    body = tmp_path / "articles" / "1.md"
    source = body.read_text(encoding="utf-8")
    body.write_text(source + "\n\nunknown_widget(\nx\n)", encoding="utf-8")

    with pytest.raises(ValueError, match="has an invalid directive"):
        load_blog_catalog(tmp_path)

    body.write_text(source.replace("intensive\n)", "telegram\n)"), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its manifest CTA"):
        load_blog_catalog(tmp_path)

    body.write_text(source.replace("blog_cta(\nintensive\n)", "В тексте упомянут blog_cta("), encoding="utf-8")
    with pytest.raises(ValueError, match="must contain exactly one CTA directive"):
        load_blog_catalog(tmp_path)


def test_heading_anchors_are_deterministic_and_unique() -> None:
    rendered, toc = add_heading_anchors(
        "<h2>Первый шаг</h2><p>Текст</p><h2>Первый шаг</h2>"
        "<h3>Детали</h3>"
    )

    assert 'id="первый-шаг"' in rendered
    assert 'id="первый-шаг-2"' in rendered
    assert 'id="детали"' in rendered
    assert toc == (("первый-шаг", "Первый шаг"), ("первый-шаг-2", "Первый шаг"))


def test_blog_component_is_closed_and_preserves_tracking_key() -> None:
    rendered = render_blog_component("blog_cta", ["intensive"])

    assert 'data-component="blog-cta"' in rendered
    assert 'data-tracking-key="blog_intensive"' in rendered
    assert "Читать бесплатно" in rendered

    with pytest.raises(HTTPException):
        render_blog_component("script", ["intensive"])
