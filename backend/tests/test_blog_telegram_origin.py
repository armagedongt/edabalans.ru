import pytest
from fastapi import HTTPException

from app.blog_content import blog_description, parse_blog_metadata
from app.blog_draft_service import render_article

POST = 'https://t.me/Fitness_Talks/123'


@pytest.mark.parametrize('header', [
    'telegram_post_url: javascript:alert(1)',
    'telegram_post_url: https://t.me.evil/Fitness_Talks/123',
    'telegram_post_url: https://t.me/Fitness_Talks/0',
    'telegram_post_url: https://t.me/Another/123',
    'telegram_post_url: https://t.me/Fitness_Talks/123?start=abc',
    'telegram_discussion_url: ' + POST + '?comment=1',
    'telegram_post_url: ' + POST + '\ntelegram_discussion_url: https://t.me/Fitness_Talks/124?comment=1',
    'telegram_post_url: ' + POST + '\ntelegram_discussion_url: ' + POST + '?comment=0',
])
def test_origin_rejects_unsafe_or_unrelated_links(header):
    with pytest.raises(HTTPException) as error:
        parse_blog_metadata('---\n' + header + '\n---\nText.')
    assert error.value.status_code == 422


@pytest.mark.parametrize('discussion', [False, True])
def test_origin_is_outside_author_text_before_cta_and_not_in_description(discussion):
    header = 'telegram_post_url: ' + POST
    if discussion:
        header += '\ntelegram_discussion_url: ' + POST + '?comment=2'
    markdown = '---\n' + header + '\n---\n## Section\n\nFirst. Second.'
    body, toc = render_article('test', {'markdown': markdown, 'media': [], 'cta': 'masterclass'})
    assert body.count('data-channel-origin="telegram"') == 1
    assert body.index('First. Second.') < body.index('data-channel-origin') < body.index('data-component="blog-cta"')
    assert ('>Обсудить</a>' in body) is discussion
    assert f'href="{POST}"' in body
    assert 'href="https://t.me/Fitness_Talks"' in body
    assert (f'href="{POST}?comment=2"' in body) is discussion
    assert 'telegram_post_url:' not in body
    assert len(toc) == 1
    assert blog_description(markdown) == 'First. Second.'


def test_api_origin_publication_and_draft_boundary():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.blog_draft_routes import router, optional_blog_admin, require_blog_admin, require_blog_mutation
    from app.blog_draft_service import ensure_existing_article
    from app.blog_routes import router as public_router

    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)

    def test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    for dependency in (optional_blog_admin, require_blog_admin, require_blog_mutation):
        app.dependency_overrides[dependency] = lambda: 'test-owner'
    slug = 'pochemu-yapontsy-hudye-a-ty-net'
    api = '/admin/api/blog/articles/' + slug
    public = '/blog/articles/' + slug
    markdown = '---\ntelegram_post_url: ' + POST + '\n---\n## Section\n\nFirst. Second.'
    try:
        with TestClient(app) as client:
            with Session(engine) as db:
                version = ensure_existing_article(db, slug).version_no
            before = client.get(public).text
            saved = client.patch(api + '/text', json={'expected_version': version, 'markdown': markdown})
            assert saved.status_code == 200, saved.text
            version = saved.json()['article']['version']
            assert client.get(api).json()['article']['markdown'] == markdown
            preview = client.post(api + '/preview', json={'markdown': markdown})
            assert preview.status_code == 200, preview.text
            assert 'data-channel-origin="telegram"' in preview.json()['html']
            assert client.get(public).text == before
            assert client.post(api + '/publish', json={'expected_version': version, 'confirm': True}).status_code == 200
            page = client.get(public).text
            assert page.count('data-channel-origin="telegram"') == 1
            assert 'id="reader-popup"' not in page
            assert 'reader-subscription.js' not in page
            assert client.patch(api + '/text', json={'expected_version': version, 'markdown': 'New draft.'}).status_code == 200
            assert client.get(public).text == page
    finally:
        engine.dispose()


def test_git_fallback_origin_keeps_author_body_and_cta(tmp_path):
    from dataclasses import replace
    from app.blog_content import load_blog_catalog, render_article_body

    catalog = load_blog_catalog()
    article = catalog.published[0]
    (tmp_path / 'articles').mkdir()
    source = '---\ntelegram_post_url: ' + POST + '\n---\n## Section\n\nAuthor text.\n\nblog_cta(\nmasterclass\n)\n'
    (tmp_path / 'articles' / article.body_file).write_text(source, encoding='utf-8')
    body, toc = render_article_body(replace(catalog, content_dir=tmp_path), article)
    assert body.count('data-channel-origin="telegram"') == 1
    assert body.index('Author text.') < body.index('data-channel-origin') < body.index('data-component="blog-cta"')
    assert len(toc) == 1
