from html import unescape
from dataclasses import replace
import re
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.blog_content import BLOG_CATEGORIES, BLOG_PUBLIC_ORIGIN, load_blog_catalog
from app.blog_routes import router
from app.database import Base, get_db


@pytest.fixture(scope="module")
def client():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def slugs(html):
    return re.findall(r'<a class="card-link" href="/articles/([^"]+)"', html)


def canonical(html):
    return unescape(re.search(r'<link rel="canonical" href="([^"]+)"', html)[1])


def test_all_public_articles_are_reachable_once_without_javascript(client):
    expected = [article.slug for article in load_blog_catalog().published]
    found = []
    for page in range(1, (len(expected) + 14) // 15 + 1):
        response = client.get("/blog", params={"page": page})
        assert response.status_code == 200
        current = slugs(response.text)
        assert current == expected[(page - 1) * 15:page * 15]
        assert len(current) <= 15
        assert canonical(response.text) == BLOG_PUBLIC_ORIGIN + "/" + (f"?page={page}" if page > 1 else "")
        assert 'data-blog-server-catalog' in response.text
        assert 'owner-panel' not in response.text
        found.extend(current)
    assert found == expected
    assert len(set(found)) == len(found)


def test_category_pages_and_links_preserve_filter(client):
    category = max(BLOG_CATEGORIES, key=lambda name: sum(article.category == name for article in load_blog_catalog().published))
    expected = [article.slug for article in load_blog_catalog().published if article.category == category]
    response = client.get("/blog", params={"category": category, "page": 2})
    assert response.status_code == 200
    assert slugs(response.text) == expected[15:30]
    query = urlencode({"category": category, "page": "2"})
    assert canonical(response.text) == f"{BLOG_PUBLIC_ORIGIN}/?{query}"
    assert f'href="?{unescape(urlencode({"category": category}))}#articles"' in response.text
    assert 'aria-current="page">2</a>' in response.text


@pytest.mark.parametrize("query", ["?page=wrong", "?page=0", "?page=-2", "?category=unknown"])
def test_invalid_selection_retains_first_page_compatibility(client, query):
    response = client.get("/blog" + query)
    assert response.status_code == 200
    assert slugs(response.text) == [article.slug for article in load_blog_catalog().published[:15]]
    assert canonical(response.text) == BLOG_PUBLIC_ORIGIN + "/"


def test_large_page_is_clamped_and_last_page_has_no_next_link(client):
    expected = load_blog_catalog().published
    last = (len(expected) + 14) // 15
    response = client.get("/blog/?page=999999")
    assert slugs(response.text) == [article.slug for article in expected[(last - 1) * 15:]]
    assert canonical(response.text) == f"{BLOG_PUBLIC_ORIGIN}/?page={last}"
    assert 'rel="next"' not in response.text


def test_unknown_category_keeps_valid_page_number(client):
    response = client.get("/blog?category=unknown&page=2")
    assert slugs(response.text) == [article.slug for article in load_blog_catalog().published[15:30]]
    assert canonical(response.text) == BLOG_PUBLIC_ORIGIN + "/?page=2"


def test_empty_catalogue_has_visible_message_and_no_pagination(client, monkeypatch):
    monkeypatch.setattr("app.blog_routes._public_catalog", lambda db: replace(load_blog_catalog(), articles=()))
    response = client.get("/blog?page=99")
    assert slugs(response.text) == []
    assert '<p class="empty-state" >' in response.text
    assert '<nav class="pagination" aria-label="Навигация по страницам блога"></nav>' in response.text
    assert canonical(response.text) == BLOG_PUBLIC_ORIGIN + "/"
