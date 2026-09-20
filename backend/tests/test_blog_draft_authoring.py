from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.blog_draft_routes import (
    optional_blog_admin,
    require_blog_admin,
    require_blog_mutation,
)
from app.blog_content import load_blog_catalog
from app.blog_draft_service import (
    DOCUMENT_TYPE,
    PUBLISHED_DOCUMENT_TYPE,
    prepare_package,
    save_package,
    update_text,
)
from app.database import Base, get_db
from app.main import app
from app.models import ManagedDocumentVersion
from scripts.publish_blog_draft import build_package, upload


FIXTURE = Path(__file__).parent / "fixtures" / "blog-draft-real"
FIXTURE_SLUG = "vse-znayut-nikto-ne-delaet"
SLUG = "skolko-vremeni-nuzhno-na-pohudenie"


def _real_package(*, expected_version: int = 0, visibility: str = "public") -> dict:
    facts = json.loads((FIXTURE / "real-article.metadata.json").read_text(encoding="utf-8"))
    known = {
        "title", "slug", "category", "visibility", "editorial_status", "cta",
        "sources", "source_id", "hero", "media",
    }
    media = []
    for item in facts["media"]:
        raw = (FIXTURE / "media" / item["name"]).read_bytes()
        media.append({
            **item,
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "alt": "",
        })
    return {
        "expected_version": expected_version,
        "title": facts["title"],
        "excerpt": "",
        "category": facts["category"],
        "markdown": (FIXTURE / "real-article.md").read_text(encoding="utf-8"),
        "visibility": visibility,
        "editorial_status": "moderation",
        "cta": facts["cta"],
        "sources": facts["sources"],
        "source_id": facts["source_id"],
        "hero": facts["hero"],
        "media": media,
        "metadata": {key: value for key, value in facts.items() if key not in known},
    }


def test_cli_package_builder_preserves_exact_source_and_provenance() -> None:
    slug, package = build_package(
        FIXTURE / "real-article.metadata.json",
        FIXTURE / "real-article.md",
        FIXTURE / "media",
        0,
    )
    assert slug == FIXTURE_SLUG
    assert package["markdown"] == (FIXTURE / "real-article.md").read_text(encoding="utf-8")
    assert package["metadata"]["source_sha256"] == "b47661efb2f9d8b895f2097b4f8e3663b50df229366ff4415d41283172000ea9"
    assert [item["name"] for item in package["media"]] == ["01.webp", "02.webp", "03.webp"]


def test_cli_refuses_to_send_admin_credentials_over_remote_http() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        upload("http://example.test", SLUG, {}, "owner", "secret")
    with pytest.raises(ValueError, match="unsafe blog slug"):
        upload("https://example.test", "../admin", {}, "owner", "secret")


def test_cli_upload_sends_basic_put_and_exact_json(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return BytesIO(b'{"ok": true}')

    monkeypatch.setattr("scripts.publish_blog_draft.urlopen", fake_urlopen)
    package = {"expected_version": 0, "markdown": "## Exact"}
    assert upload("https://example.test", SLUG, package, "owner", "secret") == {"ok": True}
    request = captured["request"]
    assert request.full_url == f"https://example.test/admin/api/blog/articles/{SLUG}"
    assert request.method == "PUT"
    assert request.get_header("Authorization") == "Basic b3duZXI6c2VjcmV0"
    assert json.loads(request.data) == package


def test_cli_rejects_media_path_escape(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    secret = tmp_path / "secret.env"
    secret.write_text("must-not-be-read", encoding="utf-8")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({
        "slug": "unsafe",
        "title": "Unsafe",
        "category": "Тренировки",
        "cta": "masterclass",
        "sources": ["content://unsafe"],
        "media": [{"name": "../secret.env", "provenance": "content://unsafe"}],
    }), encoding="utf-8")
    markdown = tmp_path / "article.md"
    markdown.write_text("## Test", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe media name"):
        build_package(metadata, markdown, media, 0)


@pytest.fixture()
def authoring(monkeypatch) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[optional_blog_admin] = lambda: "owner"
    app.dependency_overrides[require_blog_admin] = lambda: "owner"
    app.dependency_overrides[require_blog_mutation] = lambda: "owner"
    monkeypatch.setattr("app.blog_draft_routes.admin_identity", lambda *_: "owner")
    try:
        yield TestClient(app, base_url="https://edabalans.ru"), factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _put(client: TestClient, package: dict | None = None):
    return client.put(
        f"/admin/api/blog/articles/{SLUG}",
        json=package or _real_package(),
    )


def test_real_markdown_package_round_trip_and_owner_preview(authoring) -> None:
    client, _ = authoring
    original = _real_package()
    created = _put(client, original)
    assert created.status_code == 200, created.text
    assert created.json()["article"]["version"] == 1
    assert created.json()["article"]["editorial_status"] == "moderation"

    reopened = client.get(f"/admin/api/blog/articles/{SLUG}")
    assert reopened.status_code == 200
    article = reopened.json()["article"]
    assert article["markdown"] == original["markdown"]
    assert article["metadata"]["source_sha256"] == original["metadata"]["source_sha256"]
    assert [item["name"] for item in article["media"]] == ["01.webp", "02.webp", "03.webp"]
    assert "content_base64" not in article["media"][0]
    assert article["media"][0]["url"] == f"/blog/drafts/{SLUG}/media/01.webp"
    history = reopened.json()["history"]
    assert len(history) == 1
    assert history[0]["version"] == 1
    assert history[0]["updated_by"] == "owner"
    assert history[0]["active"] is True
    listing = client.get("/admin/api/blog/articles").json()["articles"]
    assert len(listing) == len(load_blog_catalog().published)
    listed = next(item for item in listing if item["slug"] == SLUG)
    assert "markdown" not in listed
    assert "content_base64" not in json.dumps(listing)

    media = client.get(f"/blog/drafts/{SLUG}/media/02.webp")
    assert media.status_code == 200
    assert media.content == (FIXTURE / "media" / "02.webp").read_bytes()
    assert media.headers["cache-control"] == "private, no-store"
    assert media.headers["x-robots-tag"] == "noindex, nofollow"

    page = client.get(f"/blog/drafts/{SLUG}")
    assert page.status_code == 200
    assert original["title"] in page.text
    assert page.text.count(f'<img src="/blog/drafts/{SLUG}/media/01.webp"') == 1
    assert "На модерации" in page.text
    editor = client.get(f"/blog/drafts/{SLUG}/edit")
    preview = client.post(
        f"/admin/api/blog/articles/{SLUG}/preview",
        json={"markdown": original["markdown"]},
    )
    assert preview.status_code == 200
    assert f"/blog/drafts/{SLUG}/media/01.webp" in preview.json()["html"]
    assert "blog-cta" in preview.json()["html"]
    assert "Посмотреть программу" in preview.json()["html"]
    for response in (created, reopened, media, page, editor, preview):
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "first_media",
    [
        '![Кадр из телесюжета](/media/01.webp "Подпись")',
        '[Скачать изображение](/media/01.webp)',
    ],
)
def test_draft_page_renders_hero_exactly_once_for_supported_markdown_forms(authoring, first_media) -> None:
    client, _ = authoring
    package = _real_package()
    package["markdown"] = package["markdown"].replace(
        "![Кадр из телесюжета](/media/01.webp)", first_media, 1
    )
    assert _put(client, package).status_code == 200
    page = client.get(f"/blog/drafts/{SLUG}")
    assert page.status_code == 200
    assert page.text.count(f'<img src="/blog/drafts/{SLUG}/media/01.webp"') == 1


def test_text_update_preserves_package_and_conflict_preserves_active_version(authoring) -> None:
    client, _ = authoring
    assert _put(client).status_code == 200
    before = client.get(f"/admin/api/blog/articles/{SLUG}").json()["article"]
    changed = before["markdown"] + "\n\n## Проверенная редакция\n\nТолько небольшая правка.\n"
    saved = client.patch(
        f"/admin/api/blog/articles/{SLUG}/text",
        json={"expected_version": 1, "markdown": changed},
    )
    assert saved.status_code == 200
    after = saved.json()["article"]
    assert after["version"] == 2
    assert after["markdown"] == changed
    assert after["media"] == before["media"]
    assert after["metadata"] == before["metadata"]

    stale = client.patch(
        f"/admin/api/blog/articles/{SLUG}/text",
        json={"expected_version": 1, "markdown": changed + "Ещё одна правка."},
    )
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "private, no-store"
    assert stale.headers["x-robots-tag"] == "noindex, nofollow"
    assert stale.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/admin/api/blog/articles/{SLUG}").json()["article"]["markdown"] == changed


def test_existing_article_seed_publish_and_later_draft_do_not_leak(authoring) -> None:
    client, factory = authoring
    seeded = client.get(f"/admin/api/blog/articles/{SLUG}")
    assert seeded.status_code == 200
    article = seeded.json()["article"]
    assert article["version"] == 1
    assert article["editorial_status"] == "published"
    assert "blog_cta(" not in article["markdown"]
    assert all("content_base64" not in item for item in article["media"])

    marker = "Проверка публикации существующей статьи."
    changed = article["markdown"] + f"\n\n## Проверка выпуска\n\n{marker}\n"
    git_fallback = client.get(f"/blog/articles/{SLUG}")
    assert "Мне надолго запомнился звонок женщины" in git_fallback.text
    saved = client.patch(
        f"/admin/api/blog/articles/{SLUG}/text",
        json={"expected_version": 1, "markdown": changed},
    )
    assert saved.status_code == 200
    assert saved.json()["article"]["editorial_status"] == "moderation"
    assert marker not in client.get(f"/blog/articles/{SLUG}").text

    published = client.post(
        f"/admin/api/blog/articles/{SLUG}/publish",
        json={"expected_version": 2, "confirm": True},
    )
    assert published.status_code == 200, published.text
    assert published.json()["article"]["editorial_status"] == "published"
    assert published.json()["public_url"].startswith("https://blog.")
    assert published.json()["public_url"].endswith(f"/articles/{SLUG}")
    public_page = client.get(f"/blog/articles/{SLUG}")
    assert marker in public_page.text
    assert public_page.text.count('data-component="blog-cta"') == 1
    assert 'data-tracking-key="blog_intensive"' in public_page.text
    assert f'<link rel="canonical" href="https://blog.' in public_page.text

    repeated = client.post(
        f"/admin/api/blog/articles/{SLUG}/publish",
        json={"expected_version": 2, "confirm": True},
    )
    assert repeated.status_code == 200
    assert repeated.json()["published_version"] == 1

    # The stored snapshot owns the body only. Manifest-controlled CTA/media/SEO
    # must stay fresh even if an old row contains stale metadata.
    with factory() as db:
        stored = db.scalar(
            select(ManagedDocumentVersion).where(
                ManagedDocumentVersion.document_type == PUBLISHED_DOCUMENT_TYPE,
                ManagedDocumentVersion.document_key == SLUG,
                ManagedDocumentVersion.is_active.is_(True),
            )
        )
        stale_payload = deepcopy(stored.payload)
        stale_payload["cta"] = "telegram"
        stored.payload = stale_payload
        db.commit()
    refreshed_public_page = client.get(f"/blog/articles/{SLUG}")
    assert marker in refreshed_public_page.text
    assert 'data-tracking-key="blog_intensive"' in refreshed_public_page.text
    assert 'data-tracking-key="blog_telegram"' not in refreshed_public_page.text

    next_marker = "Эта строка пока только на модерации."
    next_saved = client.patch(
        f"/admin/api/blog/articles/{SLUG}/text",
        json={"expected_version": 2, "markdown": changed + f"\n{next_marker}\n"},
    )
    assert next_saved.status_code == 200
    assert next_saved.json()["article"]["editorial_status"] == "moderation"
    public_page = client.get(f"/blog/articles/{SLUG}")
    assert marker in public_page.text
    assert next_marker not in public_page.text
    stale_publish = client.post(
        f"/admin/api/blog/articles/{SLUG}/publish",
        json={"expected_version": 2, "confirm": True},
    )
    assert stale_publish.status_code == 409
    after_conflict = client.get(f"/blog/articles/{SLUG}")
    assert marker in after_conflict.text
    assert next_marker not in after_conflict.text
    with factory() as db:
        published_rows = list(db.scalars(
            select(ManagedDocumentVersion).where(
                ManagedDocumentVersion.document_type == PUBLISHED_DOCUMENT_TYPE
            )
        ))
        assert len(published_rows) == 1
        assert marker in published_rows[0].payload["markdown"]
        assert next_marker not in published_rows[0].payload["markdown"]
        assert db.scalar(
            select(func.count()).select_from(ManagedDocumentVersion).where(
                ManagedDocumentVersion.document_type == PUBLISHED_DOCUMENT_TYPE
            )
        ) == 1


def test_publish_api_requires_literal_confirmation(authoring) -> None:
    client, factory = authoring
    seeded = client.get(f"/admin/api/blog/articles/{SLUG}").json()["article"]
    for payload in (
        {"expected_version": seeded["version"], "confirm": False},
        {"expected_version": seeded["version"]},
    ):
        response = client.post(
            f"/admin/api/blog/articles/{SLUG}/publish",
            json=payload,
        )
        assert response.status_code == 422
    with factory() as db:
        assert db.scalar(
            select(func.count()).select_from(ManagedDocumentVersion).where(
                ManagedDocumentVersion.document_type == PUBLISHED_DOCUMENT_TYPE
            )
        ) == 0


def test_manifest_managed_draft_refreshes_canonical_fields_before_publish(authoring) -> None:
    client, factory = authoring
    seeded = client.get(f"/admin/api/blog/articles/{SLUG}").json()["article"]
    with factory() as db:
        draft = db.scalar(
            select(ManagedDocumentVersion).where(
                ManagedDocumentVersion.document_type == DOCUMENT_TYPE,
                ManagedDocumentVersion.document_key == SLUG,
                ManagedDocumentVersion.is_active.is_(True),
            )
        )
        stale = deepcopy(draft.payload)
        stale["title"] = "Старый заголовок"
        stale["cta"] = "telegram"
        stale["media"] = []
        draft.payload = stale
        db.commit()

    reopened = client.get(f"/admin/api/blog/articles/{SLUG}").json()["article"]
    canonical = load_blog_catalog().by_slug(SLUG)
    assert reopened["title"] == canonical.title
    assert reopened["cta"] == canonical.cta
    assert reopened["media"]

    marker = "Редакция после обновления manifest."
    saved = client.patch(
        f"/admin/api/blog/articles/{SLUG}/text",
        json={
            "expected_version": seeded["version"],
            "markdown": reopened["markdown"] + f"\n\n{marker}\n",
        },
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        f"/admin/api/blog/articles/{SLUG}/publish",
        json={"expected_version": 2, "confirm": True},
    )
    assert published.status_code == 200, published.text
    public_page = client.get(f"/blog/articles/{SLUG}")
    assert marker in public_page.text
    assert 'data-tracking-key="blog_intensive"' in public_page.text


def test_unknown_slug_cannot_be_created(authoring) -> None:
    client, factory = authoring
    response = client.put(
        "/admin/api/blog/articles/novaya-statya",
        json=_real_package(),
    )
    assert response.status_code == 404
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManagedDocumentVersion)) == 0


def test_internal_existing_draft_cannot_be_published(authoring) -> None:
    client, _ = authoring
    package = _real_package(visibility="internal")
    assert _put(client, package).status_code == 200
    response = client.post(
        f"/admin/api/blog/articles/{SLUG}/publish",
        json={"expected_version": 1, "confirm": True},
    )
    assert response.status_code == 422
    assert "Служебный" in response.text


def test_existing_publish_keeps_manifest_media_contract(authoring) -> None:
    client, factory = authoring
    assert _put(client, _real_package()).status_code == 200
    response = client.post(
        f"/admin/api/blog/articles/{SLUG}/publish",
        json={"expected_version": 1, "confirm": True},
    )
    assert response.status_code == 422
    assert "media" in response.text
    public_page = client.get(f"/blog/articles/{SLUG}")
    assert "Мне надолго запомнился звонок женщины" in public_page.text
    assert 'data-tracking-key="blog_intensive"' in public_page.text
    with factory() as db:
        assert db.scalar(
            select(func.count()).select_from(ManagedDocumentVersion).where(
                ManagedDocumentVersion.document_type == PUBLISHED_DOCUMENT_TYPE
            )
        ) == 0


def test_largest_existing_article_seeds_without_inline_media(authoring) -> None:
    client, _ = authoring
    slug = "samyy-zdorovyy-chelovek-na-planete"
    article = client.get(f"/admin/api/blog/articles/{slug}").json()["article"]
    assert len(article["media"]) == 39
    assert "content_base64" not in json.dumps(article)


def test_existing_seed_is_idempotent(authoring) -> None:
    client, factory = authoring
    assert len(client.get("/admin/api/blog/articles").json()["articles"]) == 9
    assert len(client.get("/admin/api/blog/articles").json()["articles"]) == 9
    with factory() as db:
        assert db.scalar(
            select(func.count()).select_from(ManagedDocumentVersion).where(
                ManagedDocumentVersion.document_type == DOCUMENT_TYPE
            )
        ) == 9


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("markdown", "# Запрещённый H1\n", "H1"),
        ("markdown", "Запрещённый H1\n================\n", "H1"),
        ("markdown", "## Раздел\n\n<script>alert(1)</script>", "Raw HTML"),
        ("markdown", "## Раздел\n\n![Внешняя](https://example.test/a.jpg)", "media"),
        ("category", "Неизвестная", "рубрика"),
        ("editorial_status", "published", "moderation"),
    ],
)
def test_invalid_package_never_creates_active_document(authoring, field, value, message) -> None:
    client, factory = authoring
    package = _real_package()
    package[field] = value
    response = _put(client, package)
    assert response.status_code == 422
    assert message.casefold() in response.text.casefold()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManagedDocumentVersion)) == 0


def test_invalid_image_and_unknown_media_reference_are_rejected(authoring) -> None:
    client, factory = authoring
    package = _real_package()
    package["media"][0]["content_base64"] = base64.b64encode(b"not-an-image").decode("ascii")
    assert _put(client, package).status_code == 422
    package = _real_package()
    package["markdown"] += "\n\n![Нет файла](/media/missing.webp)"
    assert _put(client, package).status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManagedDocumentVersion)) == 0


def test_media_boundaries_and_integrity_are_enforced(authoring, monkeypatch) -> None:
    client, factory = authoring
    too_many = _real_package()
    too_many["media"] = too_many["media"] * 3
    assert _put(client, too_many).status_code == 422

    monkeypatch.setattr("app.blog_draft_service.MAX_MEDIA_BYTES", 10_000)
    assert _put(client).status_code == 422
    monkeypatch.setattr("app.blog_draft_service.MAX_MEDIA_BYTES", 1024 * 1024)
    monkeypatch.setattr("app.blog_draft_service.MAX_TOTAL_MEDIA_BYTES", 100_000)
    assert _put(client).status_code == 422
    monkeypatch.setattr("app.blog_draft_service.MAX_TOTAL_MEDIA_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_EDGE", 600)
    assert _put(client).status_code == 422
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_EDGE", 6000)
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_PIXELS", 100_000)
    assert _put(client).status_code == 422
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_PIXELS", 25_000_000)

    mismatch = _real_package()
    mismatch["media"][0]["name"] = "01.jpg"
    mismatch["hero"] = "01.jpg"
    mismatch["markdown"] = mismatch["markdown"].replace("/media/01.webp", "/media/01.jpg")
    assert _put(client, mismatch).status_code == 422

    assert _put(client).status_code == 200
    with factory() as db:
        row = db.scalar(select(ManagedDocumentVersion).where(ManagedDocumentVersion.is_active.is_(True)))
        payload = deepcopy(row.payload)
        payload["media"][0]["sha256"] = "0" * 64
        row.payload = payload
        db.commit()
    assert client.get(f"/blog/drafts/{SLUG}/media/01.webp").status_code == 503


def test_exact_media_boundaries_accept_limit_and_reject_one_less(monkeypatch) -> None:
    package = _real_package()
    source = {key: value for key, value in package.items() if key != "expected_version"}
    sizes = [len(base64.b64decode(item["content_base64"])) for item in package["media"]]
    largest = max(sizes)
    total = sum(sizes)

    monkeypatch.setattr("app.blog_draft_service.MAX_MEDIA_BYTES", largest)
    monkeypatch.setattr("app.blog_draft_service.MAX_TOTAL_MEDIA_BYTES", total)
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_EDGE", 1280)
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_PIXELS", 1280 * 720)
    assert prepare_package(SLUG, source)["hero"] == "01.webp"

    monkeypatch.setattr("app.blog_draft_service.MAX_MEDIA_BYTES", largest - 1)
    with pytest.raises(HTTPException, match="1 MiB"):
        prepare_package(SLUG, source)
    monkeypatch.setattr("app.blog_draft_service.MAX_MEDIA_BYTES", largest)
    monkeypatch.setattr("app.blog_draft_service.MAX_TOTAL_MEDIA_BYTES", total - 1)
    with pytest.raises(HTTPException, match="4 MiB"):
        prepare_package(SLUG, source)
    monkeypatch.setattr("app.blog_draft_service.MAX_TOTAL_MEDIA_BYTES", total)
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_EDGE", 1279)
    with pytest.raises(HTTPException, match="6000 px"):
        prepare_package(SLUG, source)
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_EDGE", 1280)
    monkeypatch.setattr("app.blog_draft_service.MAX_IMAGE_PIXELS", 1280 * 720 - 1)
    with pytest.raises(HTTPException, match="25 млн"):
        prepare_package(SLUG, source)


def test_image_that_passes_verify_but_fails_full_decode_is_rejected(authoring) -> None:
    client, _ = authoring
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "red").save(buffer, format="JPEG")
    truncated = buffer.getvalue()[:-2]
    with Image.open(BytesIO(truncated)) as image:
        image.verify()
    package = _real_package()
    package["media"] = [{
        "name": "truncated.jpg",
        "content_base64": base64.b64encode(truncated).decode("ascii"),
        "provenance": "content://decode-test",
        "alt": "",
    }]
    package["hero"] = "truncated.jpg"
    package["markdown"] = "![Проверка](/media/truncated.jpg)\n\n## Раздел\n\nТекст."
    assert _put(client, package).status_code == 422


def test_markdown_and_metadata_byte_limits_are_enforced(authoring) -> None:
    client, factory = authoring
    markdown = _real_package()
    markdown["markdown"] = "## Раздел\n\n" + "я" * 130_000
    assert _put(client, markdown).status_code == 422
    metadata = _real_package()
    metadata["metadata"] = {"large": "я" * 60_000}
    assert _put(client, metadata).status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManagedDocumentVersion)) == 0


def test_invalid_update_preserves_existing_active_version(authoring) -> None:
    client, _ = authoring
    assert _put(client).status_code == 200
    invalid = _real_package(expected_version=1)
    invalid["markdown"] = "# H1"
    assert _put(client, invalid).status_code == 422
    assert client.patch(
        f"/admin/api/blog/articles/{SLUG}/text",
        json={"expected_version": 1, "markdown": "# H1"},
    ).status_code == 422
    active = client.get(f"/admin/api/blog/articles/{SLUG}").json()["article"]
    assert active["version"] == 1
    assert active["markdown"] == _real_package()["markdown"]


def test_parallel_independent_sessions_keep_one_active_version(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.sqlite"
    engine = create_engine(
        f"sqlite+pysqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = _real_package()
    source.pop("expected_version")
    with factory() as db:
        save_package(db, slug=SLUG, source=source, expected_version=0, admin="seed")
    barrier = Barrier(2)

    def write(index: int):
        try:
            with factory() as db:
                barrier.wait()
                return update_text(
                    db,
                    slug=SLUG,
                    markdown=source["markdown"] + f"\n\nПараллельная правка {index}.",
                    expected_version=1,
                    admin=f"writer-{index}",
                ).version_no
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (1, 2)))
    assert sorted(results) == [2, 409]
    with factory() as db:
        rows = list(db.scalars(select(ManagedDocumentVersion).where(
            ManagedDocumentVersion.document_type == DOCUMENT_TYPE
        )))
    assert len(rows) == 2
    assert [row.version_no for row in rows if row.is_active] == [2]
    engine.dispose()


def test_idempotency_and_retention_keep_last_twenty_versions(authoring) -> None:
    client, factory = authoring
    package = _real_package()
    assert _put(client, package).json()["article"]["version"] == 1
    package["expected_version"] = 1
    assert _put(client, package).json()["article"]["version"] == 1
    markdown = package["markdown"]
    for expected in range(1, 22):
        response = client.patch(
            f"/admin/api/blog/articles/{SLUG}/text",
            json={"expected_version": expected, "markdown": markdown + f"\n\nРедакция {expected}."},
        )
        assert response.status_code == 200, response.text
        markdown = response.json()["article"]["markdown"]
    with factory() as db:
        versions = list(db.scalars(
            select(ManagedDocumentVersion.version_no)
            .where(ManagedDocumentVersion.document_type == DOCUMENT_TYPE)
            .order_by(ManagedDocumentVersion.version_no.desc())
        ))
    assert versions == list(range(22, 2, -1))


def test_owner_catalog_is_private_and_public_catalog_stays_git_backed(authoring) -> None:
    client, _ = authoring
    internal = _real_package(visibility="internal")
    assert _put(client, internal).status_code == 200
    owner_page = client.get("/blog")
    assert owner_page.status_code == 200
    assert "Редакция блога" in owner_page.text
    assert "data-owner-visibility=\"internal\"" in owner_page.text
    assert owner_page.headers["x-robots-tag"] == "noindex, nofollow"
    sitemap = client.get("/blog/sitemap.xml")
    assert SLUG in sitemap.text

    app.dependency_overrides[optional_blog_admin] = lambda: None
    public_page = client.get("/blog")
    assert "Редакция блога" not in public_page.text
    assert _real_package()["title"] not in public_page.text
    hidden = client.get(f"/blog/drafts/{SLUG}")
    assert hidden.status_code == 404
    assert hidden.headers["cache-control"] == "private, no-store"
    assert hidden.headers["x-robots-tag"] == "noindex, nofollow"


def test_anonymous_api_is_401_and_error_is_private(authoring) -> None:
    client, _ = authoring
    app.dependency_overrides[require_blog_admin] = lambda: (_ for _ in ()).throw(
        HTTPException(401, "admin authentication required")
    )
    response = client.get("/admin/api/blog/articles")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_real_admin_guard_protects_source_and_media(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(admin_username="owner", admin_password="secret"),
    )
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app, base_url="https://edabalans.ru")
        assert client.get("/admin/api/blog/articles").status_code == 401
        assert client.put(f"/admin/api/blog/articles/{SLUG}", json=_real_package()).status_code == 401
        assert client.put(
            f"/admin/api/blog/articles/{SLUG}",
            json=_real_package(),
            auth=("owner", "secret"),
        ).status_code == 200
        assert client.get(
            f"/admin/api/blog/articles/{SLUG}", auth=("owner", "secret")
        ).status_code == 200
        assert client.get(f"/blog/drafts/{SLUG}/media/01.webp").status_code == 404
        assert client.get(
            f"/blog/drafts/{SLUG}/media/01.webp", auth=("owner", "secret")
        ).status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_oversized_body_is_rejected_before_route_processing(authoring) -> None:
    client, factory = authoring
    response = client.put(
        f"/admin/api/blog/articles/{SLUG}",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(9 * 1024 * 1024)},
    )
    assert response.status_code == 413
    assert response.headers["cache-control"] == "private, no-store"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManagedDocumentVersion)) == 0


def test_chunked_oversized_body_is_stopped_by_stream_limit(authoring) -> None:
    client, factory = authoring
    response = client.put(
        f"/admin/api/blog/articles/{SLUG}",
        content=(b"x" * (1024 * 1024) for _ in range(9)),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManagedDocumentVersion)) == 0


def _request(*, origin: str | None) -> Request:
    headers = [] if origin is None else [(b"origin", origin.encode("ascii"))]
    return Request({
        "type": "http",
        "method": "PATCH",
        "scheme": "https",
        "path": "/admin/api/blog/articles/test/text",
        "raw_path": b"/admin/api/blog/articles/test/text",
        "query_string": b"",
        "headers": headers,
        "server": ("edabalans.ru", 443),
        "client": ("127.0.0.1", 1234),
    })


def test_cookie_style_mutation_requires_exact_same_origin(monkeypatch) -> None:
    monkeypatch.setattr("app.blog_draft_routes.admin_identity", lambda *_: "owner")
    assert require_blog_mutation(_request(origin="https://edabalans.ru"), None) == "owner"
    with pytest.raises(HTTPException) as missing:
        require_blog_mutation(_request(origin=None), None)
    assert missing.value.status_code == 403
    with pytest.raises(HTTPException) as foreign:
        require_blog_mutation(_request(origin="https://evil.example"), None)
    assert foreign.value.status_code == 403


def test_editor_contract_keeps_unsaved_text_on_failure() -> None:
    script = (Path(__file__).parents[1] / "app" / "static" / "blog" / "assets" / "draft-editor.js").read_text(encoding="utf-8")
    assert "beforeunload" in script
    assert "setDirty(true)" in script
    assert "Конфликт версий — текст сохранён в поле" in script
    assert "Публичный блог не изменился" in script
    assert "Предпросмотр обновлён. Изменения пока не сохранены." in script
    editor = (Path(__file__).parents[1] / "app" / "static" / "blog" / "draft-editor.html").read_text(encoding="utf-8")
    assert editor.index('class="draft-result"') < editor.index('class="draft-source"')
    catalog_script = (Path(__file__).parents[1] / "app" / "static" / "blog" / "assets" / "blog.js").read_text(encoding="utf-8")
    assert "aria-pressed" in catalog_script
