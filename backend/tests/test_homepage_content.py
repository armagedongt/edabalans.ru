import hashlib
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth import require_admin  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def database():
        with Session(engine) as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_admin] = lambda: "homepage-test"
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    engine.dispose()


def source(client):
    return client.get("/admin/api/public-site/homepage").json()["active"]


def test_initial_homepage_keeps_the_accepted_html_without_client_content_fetch(client):
    response = client.get("/preview/homepage-release-candidate")
    assert response.status_code == 200
    # Migration fingerprint of the accepted current page, before replacing text with slots.
    assert hashlib.sha256(response.text.encode()).hexdigest() == "6ce208de3369f6a755749eed7c2f66e15736c9879c1490cb936379390eda5c28"
    assert "<!-- homepage-slot:" not in response.text
    faq = response.text.split("<template data-local-faq-template>", 1)[1].split("</template>", 1)[0]
    assert faq.count('class="faq-question-text"') == 17
    assert response.text.count('class="homepage-program__card"') == 5


def test_generated_link_quotes_cannot_escape_href_attribute(client):
    from html.parser import HTMLParser
    current = source(client)
    payload = '[x](https://example.com/"onmouseover="alert&#40;document.domain&#41;)'
    edited = current["markdown"].replace("Мастер-класс · 21 день", payload, 1)
    result = client.put("/admin/api/public-site/homepage", json={
        "expected_version": current["version"], "markdown": edited,
    })
    assert result.status_code == 200
    attributes = []
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                attributes.extend(attrs)
    Links().feed(client.get("/preview/homepage-release-candidate").text)
    assert any('"onmouseover="' in value for name, value in attributes if name == "href")
    assert not any(name.startswith("on") for name, _ in attributes)


def test_one_published_slot_changes_only_its_text_and_not_a_dated_snapshot(client):
    initial = client.get("/preview/homepage-release-candidate").text
    snapshot = client.get("/preview/homepage-version/v2026-09-22-3").text
    current = source(client)
    updated = current["markdown"].replace("Мастер-класс · 21 день", "Одно изменённое поле", 1)
    saved = client.put("/admin/api/public-site/homepage", json={
        "expected_version": current["version"], "markdown": updated,
    })
    assert saved.status_code == 200
    assert saved.json()["active"]["version"] == current["version"] + 1
    assert client.get("/preview/homepage-release-candidate").text == initial.replace(
        "Мастер-класс · 21 день", "Одно изменённое поле", 1)
    assert client.get("/preview/homepage-version/v2026-09-22-3").text == snapshot
    embedded = client.get("/preview/homepage-release-candidate?embed=tilda").text
    assert 'data-tilda-homepage-embed="true"' in embedded
    assert 'data-pricing-endpoint="/api/pricing/site"' in embedded
    assert "Одно изменённое поле" in embedded


def test_stale_publication_does_not_overwrite_the_current_original(client):
    current = source(client)
    first = current["markdown"].replace("Мастер-класс · 21 день", "Первая редакция", 1)
    assert client.put("/admin/api/public-site/homepage", json={
        "expected_version": current["version"], "markdown": first,
    }).status_code == 200
    stale = client.put("/admin/api/public-site/homepage", json={
        "expected_version": current["version"], "markdown": current["markdown"],
    })
    assert stale.status_code == 409
    assert source(client)["markdown"] == first


@pytest.mark.parametrize("change", [
    "unsafe_html", "unsafe_markdown_link", "unknown_slot", "duplicate_slot", "missing_slot",
    "lost_inline_component", "unmarked_copy",
    "lost_visual_markup", "invalid_url",
])
def test_invalid_source_preserves_the_published_page(client, change):
    current = source(client)
    markdown = current["markdown"]
    match = re.search(r"<!-- homepage:([^ ]+) -->\n[\s\S]*?\n<!-- /homepage:\1 -->", markdown)
    assert match
    if change == "unsafe_html":
        markdown = markdown.replace("Мастер-класс · 21 день", '<img src=x onerror="alert(1)">', 1)
    elif change == "unsafe_markdown_link":
        markdown = markdown.replace("Мастер-класс · 21 день", '<a href="javascript:alert(1)">Текст</a>', 1)
    elif change == "unknown_slot":
        markdown = markdown.replace(match[1], "unknown.slot", 2)
    elif change == "duplicate_slot":
        markdown += "\n" + match[0]
    elif change == "missing_slot":
        markdown = markdown.replace(match[0], "", 1)
    elif change == "lost_inline_component":
        markdown = markdown.replace("homepage_inline(button-1)", "", 1)
    elif change == "lost_visual_markup":
        markdown = markdown.replace('<span class="site-title__plain" data-homepage-field="line-1">', "", 1)
    elif change == "invalid_url":
        markdown = markdown.replace("Мастер-класс · 21 день", "[Текст](https://[)", 1)
    else:
        markdown += "\nТекст вне адресного поля\n"
    initial = client.get("/preview/homepage-release-candidate").text
    assert client.put("/admin/api/public-site/homepage", json={
        "expected_version": current["version"], "markdown": markdown,
    }).status_code == 422
    assert source(client)["markdown"] == current["markdown"]
    assert client.get("/preview/homepage-release-candidate").text == initial


def test_shared_price_fields_and_media_are_not_a_second_markdown_owner(client):
    markdown = source(client)["markdown"]
    assert "data-price-field" not in markdown
    assert "data-product=" not in markdown
    assert "<img" not in markdown
    assert "<svg" not in markdown
    page = client.get("/preview/homepage-release-candidate").text
    assert 'data-price-field="sale"' in page
    assert 'data-product="program"' in page
    assert 'data-homepage-block="result"' in page and 'aria-labelledby="result-title" hidden' in page


def test_homepage_original_requires_existing_admin_authentication(client):
    app.dependency_overrides.pop(require_admin)
    assert client.get("/admin/api/public-site/homepage").status_code == 401
