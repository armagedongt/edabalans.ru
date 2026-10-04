import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from html import escape
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.blog_content import blog_description, blog_seo_title, parse_blog_metadata


@pytest.mark.parametrize('header', [
    'seo_title: Search title',
    'description: My description\nseo_title: Search title',
    'seo_title: Search title\ndescription: My description',
])
def test_title_is_independent_of_description_and_removed_from_body(header):
    markdown = '---\n' + header + '\n---\nFirst. Second. Third.'
    assert blog_seo_title(markdown, 'Visible title') == 'Search title'
    assert parse_blog_metadata(markdown)[1] == 'First. Second. Third.'
    assert blog_description(markdown) == ('My description' if 'description:' in header else 'First. Second.')


def test_missing_title_and_crlf_are_backward_compatible():
    assert blog_seo_title('---\r\ndescription: Existing.\r\n---\r\nBody.', 'Visible') == 'Visible'
    assert blog_seo_title('Body.', 'Visible') == 'Visible'
    assert blog_seo_title('---\r\nseo_title: "Search: title"\r\n---\r\nBody.', 'Visible') == 'Search: title'


def test_public_title_uses_git_markdown_before_first_api_publication(monkeypatch):
    from pathlib import Path
    from app.database import Base, get_db
    from app.blog_content import load_blog_catalog, default_content_dir
    from app.blog_routes import router

    article = load_blog_catalog().published[0]
    body_path = default_content_dir() / 'articles' / article.body_file
    original_read = Path.read_text
    source = original_read(body_path, encoding='utf-8')
    _, body = parse_blog_metadata(source)
    git_title = 'Git-only search title & question'

    def read_source(path, *args, **kwargs):
        if path == body_path:
            return '---\nseo_title: ' + json.dumps(git_title) + '\n---\n' + body
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read_source)
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)

    def get_test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as client:
        page = client.get('/blog/articles/' + article.slug)
        assert page.status_code == 200
        assert '<title>' + escape(git_title) + ' · Похудение — это есть</title>' in page.text
        assert '<h1>' + escape(article.title) + '</h1>' in page.text
    engine.dispose()


@pytest.mark.parametrize('header', [
    'seo_title: One\nseo_title: Two',
    'description: One\ndescription: Two',
    'title: Unknown', 'seo_title: ', 'seo_title: "unterminated',
    'seo_title: "' + 'x' * 201 + '"',
    'seo_title: "Line\\nBreak"', 'seo_title: "Control\\u0000character"',
    'seo_title: "Tab\\tcharacter"', 'seo_title: |\n  multiline', '',
])
def test_invalid_headers_are_rejected(header):
    with pytest.raises(HTTPException) as error:
        parse_blog_metadata('---\n' + header + '\n---\nBody.')
    assert error.value.status_code == 422


@pytest.mark.parametrize('seo_title', ['Search title & intrigue', '{{ARTICLE_BODY}}</title><script>alert(1)</script>'])
def test_api_save_preview_publish_and_later_draft_preserve_title_boundary(seo_title):
    from app.database import Base, get_db
    from app.blog_content import load_blog_catalog
    from app.blog_draft_routes import router as draft_router, optional_blog_admin, require_blog_admin, require_blog_mutation
    from app.blog_draft_service import ensure_existing_article
    from app.blog_routes import router as public_router

    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(draft_router)
    app.include_router(public_router)

    def get_test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    for dependency in (optional_blog_admin, require_blog_admin, require_blog_mutation):
        app.dependency_overrides[dependency] = lambda: 'test-owner'
    slug = 'pochemu-yapontsy-hudye-a-ty-net'
    title = load_blog_catalog().by_slug(slug).title
    markdown = '---\nseo_title: ' + json.dumps(seo_title) + '\n---\n\n## Section\n\nFirst. Second.'
    api = '/admin/api/blog/articles/' + slug
    with TestClient(app) as client:
        with Session(engine) as db:
            version = ensure_existing_article(db, slug).version_no
        before = client.get('/blog/articles/' + slug).text
        saved = client.patch(api + '/text', json={'expected_version': version, 'markdown': markdown})
        assert saved.status_code == 200, saved.text
        version = saved.json()['article']['version']
        assert client.get(api).json()['article']['markdown'] == markdown
        preview = client.post(api + '/preview', json={'markdown': markdown})
        assert preview.status_code == 200
        assert 'seo_title:' not in preview.json()['html']
        draft_page = client.get('/blog/drafts/' + slug).text
        assert '<title>' + escape(seo_title) + ' · Предпросмотр блога</title>' in draft_page
        assert client.get('/blog/articles/' + slug).text == before
        stale = client.patch(api + '/text', json={'expected_version': version - 1, 'markdown': 'Wrong.'})
        assert stale.status_code == 409
        published = client.post(api + '/publish', json={'expected_version': version, 'confirm': True})
        assert published.status_code == 200, published.text
        page = client.get('/blog/articles/' + slug).text
        assert '<title>' + escape(seo_title) + ' · Похудение — это есть</title>' in page
        assert '<h1>' + escape(title) + '</h1>' in page
        assert '<meta property="og:title" content="' + escape(title, quote=True) + '">' in page
        assert 'seo_title:' not in page
        assert '<script>alert(1)</script>' not in page
        assert client.patch(api + '/text', json={'expected_version': version, 'markdown': 'New beginning. Second.'}).status_code == 200
        assert client.get('/blog/articles/' + slug).text == page
        history = client.get(api).json()['history']
        assert len(history) >= 3
    engine.dispose()
