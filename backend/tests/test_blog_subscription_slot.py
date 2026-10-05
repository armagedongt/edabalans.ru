from dataclasses import replace
from html import unescape
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.blog_content import load_blog_catalog
from app.blog_routes import router
from app.database import Base, get_db


@pytest.fixture
def client():
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app) as result:
            yield result
    finally:
        engine.dispose()


def test_approved_japan_slot_is_manifest_backed_and_author_profile_has_no_slot(client):
    article = load_blog_catalog().by_source_id('11927800')
    assert article.subscription_before_heading == 'принцип-no4-контролировать-окружение'
    html = client.get('/blog/articles/' + article.slug).text
    assert f'data-subscription-before-heading="{article.subscription_before_heading}"' in html
    assert f'<h2 id="{article.subscription_before_heading}">' in html
    assert 'id="reader-popup"' in html
    profile = client.get('/blog/author/sergey-vorontsov')
    assert profile.status_code == 200
    assert 'data-subscription-before-heading' not in profile.text
    assert '{{SUBSCRIPTION_SLOT}}' not in profile.text


def test_other_article_receives_its_own_curated_slot_without_japan_path_dependency(client, monkeypatch):
    catalog = load_blog_catalog()
    article = catalog.by_source_id('13277231')
    before = client.get('/blog/articles/' + article.slug).text
    assert 'data-subscription-before-heading' not in before
    slot = 'как-прикинуть-срок-похудения'
    changed = replace(catalog, articles=tuple(
        replace(item, subscription_before_heading=slot) if item == article else item
        for item in catalog.articles
    ))
    monkeypatch.setattr('app.blog_routes._public_catalog', lambda _: changed)
    after = client.get('/blog/articles/' + article.slug)
    assert after.status_code == 200
    attribute = f' data-subscription-before-heading="{slot}"'
    assert after.text.replace(attribute, '') == before
    assert f'<h2 id="{slot}">' in after.text


def test_curated_anchor_is_escaped_as_data_not_html(client, monkeypatch):
    catalog = load_blog_catalog()
    article = catalog.by_source_id('11927800')
    value = '" onclick="alert(1)<'
    changed = replace(catalog, articles=tuple(
        replace(item, subscription_before_heading=value) if item == article else item
        for item in catalog.articles
    ))
    monkeypatch.setattr('app.blog_routes._public_catalog', lambda _: changed)
    html = client.get('/blog/articles/' + article.slug).text
    assert 'data-subscription-before-heading="&quot; onclick=&quot;alert(1)&lt;"' in html
    assert 'id="article" data-subscription-before-heading="" onclick=' not in html
    assert value in unescape(html)


@pytest.mark.parametrize('value', ['', '  ', 1, [], {}])
def test_manifest_rejects_non_string_or_empty_subscription_anchor(tmp_path, value):
    catalog = load_blog_catalog()
    raw = json.loads((catalog.content_dir / 'manifest.json').read_text(encoding='utf-8'))
    raw['articles'] = raw['articles'][:1]
    raw['articles'][0]['subscription_before_heading'] = value
    (tmp_path / 'articles').mkdir()
    (tmp_path / 'articles' / raw['articles'][0]['body_file']).write_text('Text.', encoding='utf-8')
    (tmp_path / 'manifest.json').write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='subscription_before_heading must be a non-empty string'):
        load_blog_catalog(tmp_path)
