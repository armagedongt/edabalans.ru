from blog_test_helpers import public_slug
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.blog_routes import router
from app.blog_draft_service import ensure_existing_article, publish_article, update_text
from app.database import Base, get_db


def test_shared_contents_follow_public_revision_and_replace_legacy_controls():
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
        baseline = client.get('/blog/' + public_slug(slug))
        assert baseline.status_code == 200
        assert baseline.text.count('data-site-menu-toggle') == 1
        assert 'site-menu-toggle--article' in baseline.text
        assert 'id="reader-sheet"' not in baseline.text and '{{READER_' not in baseline.text
        with Session(engine) as db:
            seed = ensure_existing_article(db, slug)
            markdown = 'Начало.\n\n## Первый раздел\n\nТекст.\n\n## Второй раздел\n\nТекст.\n\n## Третий <опасный> раздел\n\nТекст.'
            draft = update_text(db, slug=slug, markdown=markdown, expected_version=seed.version_no, admin='test')
            publish_article(db, slug=slug, expected_version=draft.version_no, admin='test')
            current = ensure_existing_article(db, slug)
            update_text(db, slug=slug, markdown='## Черновик\n\nНе выпускать.', expected_version=current.version_no, admin='test')
        html = client.get('/blog/' + public_slug(slug)).text
        panel = re.search(r'<div class="site-menu-disclosure-panel site-menu-contents".*?</div>', html, re.S).group(0)
        anchors = re.findall(r'href="#([^"]+)"', panel)
        assert len(anchors) == 3
        assert all('id="' + anchor + '"' in html for anchor in anchors)
        assert 'Черновик' not in panel and '<опасный>' not in panel
        assert 'class="toc-mobile"' not in html and 'class="toc-dock"' not in html
        menu = html.split('data-site-menu role="dialog"', 1)[1]
        assert menu.index('href="/">Мастер-класс') < menu.index('Содержание статьи')
        assert menu.index('>Контакты</button>') < menu.index('Содержание статьи')
        with Session(engine) as db:
            current = ensure_existing_article(db, slug)
            short = update_text(db, slug=slug, markdown='## Короткий раздел\n\nТекст.', expected_version=current.version_no, admin='test')
            publish_article(db, slug=slug, expected_version=short.version_no, admin='test')
        short_html = client.get('/blog/' + public_slug(slug)).text
        assert 'site-menu-toggle--article' in short_html and 'id="reader-sheet"' not in short_html
        short_panel = re.search(r'<div class="site-menu-disclosure-panel site-menu-contents".*?</div>', short_html, re.S).group(0)
        assert short_panel.count('href="#') == 1 and 'Короткий раздел' in short_panel
        with Session(engine) as db:
            current = ensure_existing_article(db, slug)
            plain = update_text(db, slug=slug, markdown='Обычный текст без подзаголовков.', expected_version=current.version_no, admin='test')
            publish_article(db, slug=slug, expected_version=plain.version_no, admin='test')
        plain_html = client.get('/blog/' + public_slug(slug)).text
        assert re.search(r'<div class="site-menu-disclosure" hidden>\s*<button[^>]*data-site-menu-contents', plain_html)
        profile = client.get('/blog/author/sergey-vorontsov').text
        assert 'id="reader-sheet"' not in profile and '{{READER_' not in profile
        for name in ('reader-navigation.css', 'reader-navigation.js'):
            assert client.get('/blog/assets/' + name).status_code == 200
    engine.dispose()


def test_blog_menu_reuses_curated_recommendations_without_article_contents():
    from app.blog_routes import _template
    from app.blog_content import load_blog_catalog
    import json
    html = _template('index.html')
    menu = re.search(r'<aside class="site-menu-panel".*?</aside>', html, re.S).group(0)
    panel = re.search(r'<div class="site-menu-disclosure-panel site-menu-contents".*?</div>', menu, re.S).group(0)
    catalog = load_blog_catalog()
    slugs = json.loads((catalog.content_dir / 'homepage.json').read_text(encoding='utf-8'))['starter_slugs']
    assert re.findall(r'href="/blog/([^"]+)"', panel) == slugs
    assert 'Рекомендую начать с этих статей' in menu
    assert 'site-menu-toggle--article' not in html
    assert 'href="/">Мастер-класс</a>' in menu
