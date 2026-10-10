from dataclasses import replace
from html import unescape
import re
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from test_blog_author_dates import authoring
from test_blog_server_pagination import slugs, canonical
from app.blog_content import BLOG_PUBLIC_ORIGIN, load_blog_catalog
from app.blog_draft_service import ensure_existing_article, update_text, publish_article


def test_title_search_normalizes_case_spaces_and_yo(authoring):
    client, _ = authoring
    result = client.get('/blog', params={'q': '  НЕПРИЯТНАЯ   МЕД  '})
    assert result.status_code == 200
    expected = load_blog_catalog().by_source_id('11875492')
    assert slugs(result.text) == [expected.slug]
    assert result.headers['X-Robots-Tag'] == 'noindex, follow'
    assert canonical(result.text) == BLOG_PUBLIC_ORIGIN + '/'
    assert 'value="НЕПРИЯТНАЯ МЕД"' in result.text


def test_published_body_is_searchable_but_new_draft_is_not(authoring):
    client, engine = authoring
    slug = 'pochemu-yapontsy-hudye-a-ty-net'
    with Session(engine) as db:
        seed = ensure_existing_article(db, slug)
        version = update_text(db, slug=slug, markdown='Первое предложение. Второе предложение.\n\nВ глубине статьи уникальныйпубличныймаркер.', expected_version=seed.version_no, admin='test')
        publish_article(db, slug=slug, expected_version=version.version_no, admin='test')
        update_text(db, slug=slug, markdown='Новая ревизия секретныйчерновоймаркер.', expected_version=version.version_no, admin='test')
    assert slugs(client.get('/blog', params={'q': 'уникальныйпубличныймаркер'}).text) == [slug]
    assert slugs(client.get('/blog', params={'q': 'секретныйчерновоймаркер'}).text) == []


def test_nonpublic_manifest_article_is_not_searchable(authoring, monkeypatch):
    client, _ = authoring
    catalog = load_blog_catalog()
    private = replace(catalog.published[0], status='moderation', title='закрытыйсекретныймаркер')
    monkeypatch.setattr('app.blog_routes._public_catalog', lambda db: replace(catalog, articles=(private,)))
    result = client.get('/blog', params={'q': 'закрытыйсекретныймаркер'})
    assert slugs(result.text) == []
    assert 'Ничего не найдено' in result.text


def test_search_pagination_and_categories_keep_query(authoring):
    client, _ = authoring
    q = 'похуд'
    first = client.get('/blog', params={'q': q})
    second = client.get('/blog', params={'q': q, 'page': 2})
    assert len(slugs(first.text)) == 15
    assert slugs(second.text)
    assert not set(slugs(first.text)) & set(slugs(second.text))
    assert '?page=2&amp;q=' in first.text
    category = 'Похудение'
    query = urlencode({'category': category, 'q': q})
    assert f'href="?{query}#articles"' in unescape(first.text)
    filtered = client.get('/blog', params={'category': category, 'q': q})
    allowed = {a.slug for a in load_blog_catalog().published if a.category == category}
    assert set(slugs(filtered.text)) <= allowed


def test_empty_search_is_regular_catalog_and_query_is_escaped(authoring):
    client, _ = authoring
    empty = client.get('/blog', params={'q': '  '})
    assert 'X-Robots-Tag' not in empty.headers
    assert slugs(empty.text) == [a.slug for a in load_blog_catalog().published[:15]]
    attack = '<script>alert("x")</script>'
    result = client.get('/blog', params={'q': attack})
    assert attack not in result.text
    assert '&lt;script&gt;' in result.text
    assert client.get('/blog', params={'q': 'x' * 201}).status_code == 422


def test_search_is_available_on_catalog_article_and_profile(authoring):
    client, _ = authoring
    for route in ('/blog', '/blog/articles/pochemu-yapontsy-hudye-a-ty-net', '/blog/author/sergey-vorontsov'):
        result = client.get(route)
        assert result.status_code == 200
        assert 'role="search"' in result.text
        assert f'action="{BLOG_PUBLIC_ORIGIN}/"' in result.text
        form = re.search(r'<form\b[^>]*role="search"[^>]*>(.*?)</form>', result.text, re.S)
        assert form is not None
        assert 'method="get"' in form.group(0)
        assert re.search(r'<input\b[^>]*type="search"[^>]*name="q"', form.group(1))
        assert '{{SEARCH_' not in result.text
