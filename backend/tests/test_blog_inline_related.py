from dataclasses import replace
from html import unescape
import json
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest

from app.blog_content import BlogInlineRelated, insert_inline_related, load_blog_catalog, render_article_body, validate_blog_catalog
from app.blog_draft_service import ensure_existing_article, publish_article, update_text
from app.blog_routes import router
from app.database import Base, get_db


def test_single_slot_follows_completed_section_without_changing_body_or_toc():
    catalog = load_blog_catalog()
    article = catalog.by_source_id('11927800')
    body, toc = render_article_body(catalog, article)
    rendered = insert_inline_related(catalog, article, body)
    block = re.search(r'<aside class="reader-related">.*?</aside>', rendered)
    assert block is not None and rendered.count('class="reader-related"') == 1
    assert rendered.replace(block.group(0), '') == body
    assert rendered.index('Короче, вы либо формируете обстоятельства') < block.start()
    assert rendered[block.end():].startswith('<h2 id="принцип-no5-достаточно-времени">')
    target = catalog.by_source_id(article.inline_related.source_id)
    assert f'href="/articles/{target.slug}"' in block.group(0)
    assert target.title in unescape(block.group(0)) and target.excerpt in unescape(block.group(0))
    assert all(target.title != title for _, title in toc)


def test_absent_slot_or_changed_heading_never_inserts_into_another_section():
    catalog = load_blog_catalog()
    article = catalog.by_source_id('11927800')
    body, _ = render_article_body(catalog, article)
    assert insert_inline_related(catalog, replace(article, inline_related=None), body) == body
    changed = body.replace('id="принцип-no5-достаточно-времени"', 'id="новое-имя"')
    assert insert_inline_related(catalog, article, changed) == changed


@pytest.mark.parametrize('source_id', ['11927800', 'unknown'])
def test_manifest_rejects_self_or_unpublished_target(source_id):
    catalog = load_blog_catalog()
    article = catalog.by_source_id('11927800')
    changed = replace(article, inline_related=BlogInlineRelated(source_id, 'принцип-no5-достаточно-времени'))
    with pytest.raises(ValueError, match='invalid inline related target'):
        validate_blog_catalog(replace(catalog, articles=tuple(changed if item == article else item for item in catalog.articles)))


def test_manifest_rejects_multiple_slots(tmp_path):
    catalog = load_blog_catalog()
    raw = json.loads((catalog.content_dir / 'manifest.json').read_text(encoding='utf-8'))
    raw['articles'][0]['inline_related'] = [{}, {}]
    # Parsing rejects the first entry before validation needs the rest of the catalogue.
    (tmp_path / 'articles').mkdir()
    first_body = raw['articles'][0]['body_file']
    (tmp_path / 'articles' / first_body).write_text('Текст.', encoding='utf-8')
    (tmp_path / 'manifest.json').write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='one source_id/before_heading object'):
        load_blog_catalog(tmp_path)


def test_curated_pool_rejects_published_but_non_conversion_target():
    catalog = load_blog_catalog()
    article = catalog.by_source_id('10425659')
    changed = replace(article, inline_related=BlogInlineRelated('10573917', 'программа'))
    with pytest.raises(ValueError, match='outside curated pool'):
        validate_blog_catalog(replace(catalog, articles=tuple(changed if item == article else item for item in catalog.articles)))


@pytest.mark.parametrize('pool', [('unknown',), ('11801517', '11801517')])
def test_curated_pool_rejects_unknown_or_duplicate_members(pool):
    with pytest.raises(ValueError, match='unique published targets'):
        validate_blog_catalog(replace(load_blog_catalog(), inline_related_pool_source_ids=pool))


@pytest.mark.parametrize('pool', [None, '11801517', [None], [''], [' 11801517']])
def test_manifest_rejects_malformed_curated_pool(tmp_path, pool):
    catalog = load_blog_catalog()
    raw = json.loads((catalog.content_dir / 'manifest.json').read_text(encoding='utf-8'))
    raw['inline_related_pool_source_ids'] = pool
    raw['articles'] = []
    (tmp_path / 'manifest.json').write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='source_id string list'):
        load_blog_catalog(tmp_path)


def test_empty_curated_pool_forbids_slots_but_not_articles_without_slots():
    catalog = load_blog_catalog()
    with pytest.raises(ValueError, match='outside curated pool'):
        validate_blog_catalog(replace(catalog, inline_related_pool_source_ids=()))
    validate_blog_catalog(replace(catalog, inline_related_pool_source_ids=(), articles=tuple(replace(a, inline_related=None) for a in catalog.articles)))


def test_curated_pool_does_not_assign_links_automatically():
    catalog = load_blog_catalog()
    validate_blog_catalog(catalog)
    article = next(a for a in catalog.published if a.inline_related is None)
    body, _ = render_article_body(catalog, article)
    assert insert_inline_related(catalog, article, body) == body


@pytest.mark.parametrize('declare_empty', [True, False])
def test_loader_preserves_explicit_empty_pool_vs_legacy_absence(tmp_path, declare_empty):
    payload = {'version': 1, 'articles': []}
    if declare_empty:
        payload['inline_related_pool_source_ids'] = []
    (tmp_path / 'manifest.json').write_text(json.dumps(payload), encoding='utf-8')
    loaded = load_blog_catalog(tmp_path)
    current = load_blog_catalog()
    # Exercise the loader's pool interpretation against actual assigned articles.
    restored = replace(loaded, articles=current.articles, content_dir=current.content_dir)
    if declare_empty:
        with pytest.raises(ValueError, match='outside curated pool'):
            validate_blog_catalog(restored)
    else:
        validate_blog_catalog(restored)


def test_curated_pool_rejects_draft_member():
    catalog = load_blog_catalog()
    target = catalog.inline_related_pool_source_ids[0]
    with pytest.raises(ValueError, match='unique published targets'):
        validate_blog_catalog(replace(catalog, articles=tuple(replace(a, status='draft') if a.source_id == target else a for a in catalog.articles)))


def test_manifest_rejects_existing_draft_target():
    catalog = load_blog_catalog()
    article = catalog.by_source_id('11927800')
    target = next(item for item in catalog.published if item.source_id != article.source_id and item.source_id not in article.related_source_ids)
    changed = replace(article, inline_related=BlogInlineRelated(target.source_id, 'принцип-no5-достаточно-времени'))
    others = tuple(replace(item, status='draft') if item == target else item for item in catalog.articles if item != article)
    with pytest.raises(ValueError, match='invalid inline related target'):
        validate_blog_catalog(replace(catalog, articles=(changed, *others)))


def test_public_git_and_api_use_current_target_description_not_draft():
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        path = '/blog/articles/pochemu-yapontsy-hudye-a-ty-net'
        baseline = client.get(path)
        assert baseline.status_code == 200 and baseline.text.count('class="reader-related"') == 1
        with Session(engine) as db:
            slug = load_blog_catalog().by_source_id(load_blog_catalog().by_source_id('11927800').inline_related.source_id).slug
            seed = ensure_existing_article(db, slug)
            draft = update_text(db, slug=slug, markdown='---\ndescription: "Утверждённый анонс <img onerror=bad>"\n---\n\nМой текст.', expected_version=seed.version_no, admin='test')
            publish_article(db, slug=slug, expected_version=draft.version_no, admin='test')
            current = ensure_existing_article(db, slug)
            update_text(db, slug=slug, markdown='---\ndescription: "Ещё не опубликовано"\n---\n\nЧерновик.', expected_version=current.version_no, admin='test')
            japan_slug = 'pochemu-yapontsy-hudye-a-ty-net'
            japan = ensure_existing_article(db, japan_slug)
            body = 'Текст сохранён.\n\n## Принцип №5. Достаточно времени\n\nПродолжение.'
            changed = update_text(db, slug=japan_slug, markdown=body, expected_version=japan.version_no, admin='test')
            published = publish_article(db, slug=japan_slug, expected_version=changed.version_no, admin='test')
            assert published.payload['markdown'] == body
        rendered = client.get(path)
        assert rendered.status_code == 200
        inline = re.search(r'<aside class="reader-related">.*?</aside>', rendered.text).group(0)
        assert 'Утверждённый анонс &lt;img onerror=bad&gt;' in inline
        assert 'Ещё не опубликовано' not in inline and '<img' not in inline
        assert rendered.text.count('class="reader-related"') == 1
        assert 'Текст сохранён.' in rendered.text
    engine.dispose()
