import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.blog_routes import router
from app.blog_draft_service import ensure_existing_article, publish_article, update_text
from app.database import Base, get_db


def test_contents_follow_public_api_revision_not_draft_and_keep_original_controls():
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database
    slug = 'pochemu-yapontsy-hudye-a-ty-net'
    with TestClient(app) as client:
        baseline = client.get('/blog/articles/' + slug)
        assert baseline.status_code == 200
        assert 'class="toc-mobile"' in baseline.text and 'class="toc-dock"' in baseline.text
        assert 'id="reader-sheet"' in baseline.text and '{{READER_' not in baseline.text
        with Session(engine) as db:
            seed = ensure_existing_article(db, slug)
            markdown = 'Начало.\n\n## Первый раздел\n\nТекст.\n\n## Второй раздел\n\nТекст.\n\n## Третий <опасный> раздел\n\nТекст.'
            draft = update_text(db, slug=slug, markdown=markdown, expected_version=seed.version_no, admin='test')
            publish_article(db, slug=slug, expected_version=draft.version_no, admin='test')
            current = ensure_existing_article(db, slug)
            update_text(db, slug=slug, markdown='## Черновик\n\nНе выпускать.', expected_version=current.version_no, admin='test')
        html = client.get('/blog/articles/' + slug).text
        panel = re.search(r'<aside class="reader-sidebar".*?</aside>', html, re.S).group(0)
        anchors = re.findall(r'href="#([^"]+)"', panel)
        assert len(anchors) == 3
        assert all('id="' + anchor + '"' in html for anchor in anchors)
        assert 'Черновик' not in panel and '<опасный>' not in panel
        assert 'class="toc-mobile"' in html and 'class="toc-dock"' in html
        with Session(engine) as db:
            current = ensure_existing_article(db, slug)
            short = update_text(db, slug=slug, markdown='## Короткий раздел\n\nТекст.', expected_version=current.version_no, admin='test')
            publish_article(db, slug=slug, expected_version=short.version_no, admin='test')
        short_html = client.get('/blog/articles/' + slug).text
        assert 'id="reader-sheet"' in short_html and 'class="reader-site-menu"' in short_html
        short_panel = re.search(r'<aside class="reader-sidebar".*?</aside>', short_html, re.S).group(0)
        assert '<ol>' not in short_panel and 'class="toc-mobile"' not in short_html
        profile = client.get('/blog/author/sergey-vorontsov').text
        assert 'id="reader-sheet"' not in profile and '{{READER_' not in profile
        for name in ('reader-navigation.css', 'reader-navigation.js'):
            assert client.get('/blog/assets/' + name).status_code == 200
    engine.dispose()
