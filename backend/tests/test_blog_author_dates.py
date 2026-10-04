from datetime import datetime, timezone
from dataclasses import replace
import json
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.blog_content import BLOG_PUBLIC_ORIGIN, load_blog_catalog, validate_blog_catalog
from app.blog_draft_service import ensure_existing_article, publish_article, update_text
from app.blog_routes import router
from app.database import Base, get_db


@pytest.fixture
def authoring():
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def structured(html):
    return [json.loads(value) for value in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_profile_and_article_share_one_author_without_generated_copy(authoring):
    client, _ = authoring
    profile = client.get('/blog/author/sergey-vorontsov')
    assert profile.status_code == 200
    person = structured(profile.text)[0]['mainEntity']
    assert person['name'] == 'Сергей Воронцов'
    assert person['jobTitle'] == 'Тренер по питанию'
    assert person['description'] == 'Пишу о питании и похудении так, чтобы вы менялись.'
    assert '600' not in profile.text
    assert 'related-section' not in profile.text
    assert 'blog-cta' not in profile.text
    assert '{{' not in profile.text
    assert '/blog/assets/sergey-author-channel.webp' in profile.text
    article = client.get('/blog/articles/pochemu-yapontsy-hudye-a-ty-net')
    assert structured(article.text)[0]['author'] == person
    assert f'href="{person["url"]}"' in article.text
    assert client.get('/blog/assets/sergey-author-channel.webp').status_code == 200
    assert person['url'] in client.get('/blog/sitemap.xml').text


def test_breadcrumbs_are_clickable_and_match_structured_data(authoring):
    client, _ = authoring
    article = load_blog_catalog().by_slug('pochemu-yapontsy-hudye-a-ty-net')
    page = client.get('/blog/articles/' + article.slug)
    breadcrumbs = structured(page.text)[1]['itemListElement']
    assert [item['position'] for item in breadcrumbs] == [1, 2, 3]
    assert breadcrumbs[0]['item'] == BLOG_PUBLIC_ORIGIN + '/'
    assert breadcrumbs[1]['item'] == BLOG_PUBLIC_ORIGIN + '/?' + urlencode({'category': article.category})
    assert breadcrumbs[2]['item'] == BLOG_PUBLIC_ORIGIN + '/articles/' + article.slug
    assert f'href="{breadcrumbs[1]["item"]}"' in page.text
    assert f'<span aria-current="page">{article.title}</span>' in page.text


def test_confirmed_source_date_is_shown_and_missing_date_is_not_invented(authoring):
    client, _ = authoring
    confirmed = load_blog_catalog().by_slug('kak-na-menya-napali-sobaki-v-lesu')
    page = client.get('/blog/articles/' + confirmed.slug)
    assert structured(page.text)[0]['datePublished'] == confirmed.original_published_at
    assert 'Исходная публикация: <time datetime="2023-06-17T13:18:08+03:00">17.06.2023</time>' in page.text
    missing = next(article for article in load_blog_catalog().published if article.original_published_at is None)
    page = client.get('/blog/articles/' + missing.slug)
    assert 'datePublished' not in structured(page.text)[0]
    assert 'Исходная публикация:' not in page.text
    assert 'dateModified' not in structured(page.text)[0]


def test_new_moderation_draft_cannot_change_public_revision_date(authoring):
    client, engine = authoring
    slug = 'pochemu-yapontsy-hudye-a-ty-net'
    with Session(engine) as db:
        seed = ensure_existing_article(db, slug)
        published = publish_article(db, slug=slug, expected_version=seed.version_no, admin='test')
        published.created_at = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        db.commit()
        before = client.get('/blog/articles/' + slug).text
        update_text(db, slug=slug, markdown='Новый черновик.', expected_version=seed.version_no, admin='test')
        after = client.get('/blog/articles/' + slug).text
    assert structured(before)[0]['dateModified'] == '2026-09-30T12:00:00+00:00'
    assert structured(after)[0]['dateModified'] == structured(before)[0]['dateModified']
    assert 'Новый черновик.' not in after
    assert 'Обновлено в блоге:' in after


@pytest.mark.parametrize('value', ['2026-10-04T00:00:00', 'not-a-date'])
def test_bad_source_timestamp_is_rejected(value):
    catalog = load_blog_catalog()
    first = replace(catalog.articles[0], original_published_at=value)
    with pytest.raises(ValueError):
        validate_blog_catalog(replace(catalog, articles=(first, *catalog.articles[1:])))


def test_public_proxy_exposes_only_exact_author_path():
    source = (Path(__file__).resolve().parents[2] / 'infra/caddy/Caddyfile').read_text(encoding='utf-8')
    blog = source.split('{$BLOG_DOMAIN} {', 1)[1]
    assert 'handle /author/sergey-vorontsov {' in blog
    assert 'rewrite * /blog/author/sergey-vorontsov' in blog
    assert 'handle /author/*' not in blog
    assert 'handle /blog/drafts/*' not in blog
    assert 'handle /admin/api/blog/articles*' not in blog
