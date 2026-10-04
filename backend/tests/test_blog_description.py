import json

import pytest
from fastapi import HTTPException

from app.blog_content import blog_description, split_blog_metadata


def test_opening_sentences_skip_heading_media_and_preserve_inline_text():
    source = '## Вводная\n\n![Картинка](/blog/media/image.webp)\n\n**Первое** предложение? [Второе](https://example.com) предложение! Третье.\n'
    assert blog_description(source) == 'Первое предложение? Второе предложение!'


@pytest.mark.parametrize(('source', 'expected'), [
    ('Первое. **Сначала база**. Третье.', 'Первое. Сначала база.'),
    ('**Первое**? [Второе](https://example.com). Третье.', 'Первое? Второе.'),
    ('*Первое* (со [ссылкой](https://example.com)). Второе & <3.',
     'Первое (со ссылкой). Второе & <3.'),
    ('> **Первое** предложение.\n> Второе со *словом*.\n> Третье.',
     'Первое предложение. Второе со словом.'),
    ('> Первая\n> фраза. Вторая фраза. Третья.', 'Первая фраза. Вторая фраза.'),
])
def test_inline_formatting_does_not_insert_description_spaces(source, expected):
    assert blog_description(source) == expected


def test_explicit_description_wins_without_becoming_article_body():
    body = '\nПервое. Второе.\n'
    source = '---\ndescription: ' + json.dumps('Мой "ручной" анонс.', ensure_ascii=False) + '\n---\n' + body
    assert blog_description(source) == 'Мой "ручной" анонс.'
    assert split_blog_metadata(source)[1] == body


@pytest.mark.parametrize('prefix', ['> ', '- '])
def test_quote_or_list_opening_is_not_skipped(prefix):
    assert blog_description(prefix + 'Первое предложение. Второе предложение.\n\nТретье предложение.') == 'Первое предложение. Второе предложение.'


def test_plain_description_and_windows_newlines():
    assert blog_description('---\r\ndescription: Ручной анонс.\r\n---\r\nТекст.') == 'Ручной анонс.'


@pytest.mark.parametrize('source', [
    '---\ndescription: "bad\n---\nТекст.',
    '---\ndescription: \n---\nТекст.',
    '---\ntitle: Неизвестное поле\n---\nТекст.',
    '---\ndescription: Текст.\nНе закрыто',
    '---\ndescription: "' + 'x' * 501 + '"\n---\nТекст.',
])
def test_bad_description_header_is_rejected(source):
    with pytest.raises(HTTPException) as exc:
        blog_description(source)
    assert exc.value.status_code == 422


def test_long_opening_is_bounded_without_keyword_generation():
    value = blog_description(('слово ' * 90) + '. Следующее.')
    assert len(value) <= 300
    assert value.endswith('…')
    assert value[:-1].endswith('слово')


def test_repeated_description_reuses_render_but_changed_text_is_fresh(monkeypatch):
    from app import blog_content

    original_render = blog_content.markdown_to_article_html
    rendered = []

    def record_render(markdown, **kwargs):
        rendered.append(markdown)
        return original_render(markdown, **kwargs)

    blog_description.cache_clear()
    monkeypatch.setattr(blog_content, 'markdown_to_article_html', record_render)
    first = blog_description('Первое начало. Второе предложение.')
    second = blog_description('Первое начало. Второе предложение.')
    assert len(rendered) == 1
    assert first == second
    assert blog_description('Изменённое начало. Новое второе предложение.') == 'Изменённое начало. Новое второе предложение.'
    assert len(rendered) == 2
    blog_description.cache_clear()


def test_git_catalog_ignores_legacy_manifest_excerpt(monkeypatch):
    from pathlib import Path
    from app.blog_content import load_blog_catalog, default_content_dir

    original_read = Path.read_text
    root = default_content_dir()
    manifest_path = root / 'manifest.json'
    manifest = json.loads(original_read(manifest_path, encoding='utf-8'))
    for article in manifest['articles']:
        article['excerpt'] = 'LEGACY MANIFEST MUST NOT WIN'
    first = manifest['articles'][0]
    body_path = root / 'articles' / first['body_file']

    def read_source(path, *args, **kwargs):
        if path == manifest_path:
            return json.dumps(manifest)
        if path == body_path:
            return 'Авторское первое предложение. Второе предложение. Третье.\n\n' + original_read(path, *args, **kwargs)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read_source)
    catalog = load_blog_catalog()
    assert catalog.by_source_id(first['source_id']).excerpt == 'Авторское первое предложение. Второе предложение.'


@pytest.mark.parametrize('description', ['Ручной анонс & интрига.', '{{STRUCTURED_DATA}}"><img src=x onerror=alert(1)>'])
def test_description_stays_draft_until_publish_and_drives_catalog_and_page(description):
    from html import escape
    from html.parser import HTMLParser
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.blog_content import load_blog_catalog
    from app.blog_draft_service import ensure_existing_article, update_text, publish_article
    from app.blog_routes import router

    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)

    def get_test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    client = TestClient(app)
    slug = 'pochemu-yapontsy-hudye-a-ty-net'
    catalog = load_blog_catalog()
    catalog_page = catalog.published.index(catalog.by_slug(slug)) // 15 + 1
    with Session(engine) as db:
        seed = ensure_existing_article(db, slug)
        draft = update_text(db, slug=slug, markdown='---\ndescription: ' + json.dumps(description, ensure_ascii=False) + '\n---\n\nПервое предложение. Второе предложение.', expected_version=seed.version_no, admin='test')
        before = client.get('/blog/articles/' + slug).text
        assert escape(description, quote=True) not in before
        publish_article(db, slug=slug, expected_version=draft.version_no, admin='test')
        page = client.get('/blog/articles/' + slug).text
        assert '<meta name="description" content="' + escape(description, quote=True) + '">' in page
        class ImageParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == 'img':
                    assert 'onerror' not in dict(attrs)

        ImageParser().feed(page)
        assert 'description:' not in page
        assert escape(description, quote=True) in client.get('/blog', params={'page': catalog_page}).text
        assert escape(description, quote=True) in client.get('/blog/articles/skolko-vremeni-nuzhno-na-pohudenie').text
        update_text(db, slug=slug, markdown='Новое начало. Вторая фраза. Третья.', expected_version=draft.version_no, admin='test')
        assert escape(description, quote=True) in client.get('/blog', params={'page': catalog_page}).text
    engine.dispose()
