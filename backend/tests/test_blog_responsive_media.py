import hashlib
import json
from pathlib import Path
import re
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.blog_content import load_blog_catalog
from app.blog_draft_service import ensure_existing_article, publish_article, update_text
from app.blog_responsive_media import apply_responsive_images, derivative_files, responsive_manifest
from app.blog_routes import router
from app.database import Base, get_db

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build_blog_responsive_media import build


@pytest.fixture
def media_client():
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


def test_builder_preserves_originals_aspect_ratio_transparency_and_animation(tmp_path):
    (tmp_path / 'media').mkdir()
    (tmp_path / 'articles').mkdir()
    photo = Image.new('RGBA', (1000, 500), (80, 80, 80, 100))
    draw = ImageDraw.Draw(photo)
    draw.rectangle((0, 0, 99, 499), fill=(230, 20, 20, 100))
    draw.rectangle((900, 0, 999, 499), fill=(20, 20, 230, 100))
    draw.rectangle((100, 0, 899, 49), fill=(20, 230, 20, 100))
    draw.rectangle((100, 450, 899, 499), fill=(230, 230, 20, 100))
    photo.save(tmp_path / 'media/photo.png')
    Image.new('RGB', (120, 60), 'red').save(tmp_path / 'media/small.png')
    Image.new('RGB', (100, 100), 'red').save(tmp_path / 'media/motion.gif', save_all=True, append_images=[Image.new('RGB', (100, 100), 'blue')], duration=100, loop=0)
    original = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (tmp_path / 'media').iterdir()}
    (tmp_path / 'articles/one.md').write_text('![small](/blog/media/small.png)\n![motion](/blog/media/motion.gif)', encoding='utf-8')
    (tmp_path / 'manifest.json').write_text(json.dumps({'articles': [{'status': 'published', 'body_file': 'one.md', 'media': ['small.png', 'motion.gif'], 'card': {'file': 'photo.png'}, 'hero': {'file': 'photo.png', 'show': False}}]}), encoding='utf-8')
    built = build(tmp_path)
    assert 'motion.gif' not in built['images']
    assert built['skipped'][0]['file'] == 'motion.gif'
    assert built['images']['small.png']['variants'] == []
    variants = built['images']['photo.png']['variants']
    assert variants and variants[0]['width'] == 480
    for variant in variants:
        with Image.open(tmp_path / 'media' / variant['file']) as image:
            assert image.width == variant['width'] <= 1000
            assert image.height == image.width // 2
            assert image.mode == 'RGBA'
            assert image.getpixel((0, 0))[3] == 100
            samples = [((5, image.height // 2), (230, 20, 20)), ((image.width - 6, image.height // 2), (20, 20, 230)), ((image.width // 2, 5), (20, 230, 20)), ((image.width // 2, image.height - 6), (230, 230, 20))]
            for point, color in samples:
                assert all(abs(actual - expected) < 20 for actual, expected in zip(image.getpixel(point)[:3], color))
    assert {name: hashlib.sha256((tmp_path / 'media' / name).read_bytes()).hexdigest() for name in original} == original


def test_html_uses_distinct_sizes_and_preserves_fallback_alt_and_loading():
    catalog = load_blog_catalog()
    images = responsive_manifest(catalog.content_dir)
    name = next(name for name, item in images.items() if item['variants'])
    original = f'<img class="card-image" src="/blog/media/{name}" alt="Мой текст" loading="eager">'
    rendered = apply_responsive_images(original, catalog.content_dir, catalog.allowed_media)
    assert f'src="/blog/media/{name}"' in rendered
    assert 'alt="Мой текст" loading="eager"' in rendered
    assert 'srcset=' in rendered and ' / 3)' in rendered
    body = apply_responsive_images(original.replace(' class="card-image"', ''), catalog.content_dir, catalog.allowed_media)
    assert '760px' in body and ' / 3)' not in body
    assert apply_responsive_images(original, catalog.content_dir, frozenset()) == original
    remote = '<img src="https://example.com/image.webp" alt="external">'
    assert apply_responsive_images(remote, catalog.content_dir, catalog.allowed_media) == remote


def test_builder_rejects_larger_downscaled_encoding_before_registration(tmp_path):
    catalog = load_blog_catalog()
    original = (catalog.content_dir / 'media/10369434/01.webp').read_bytes()
    (tmp_path / 'media').mkdir()
    (tmp_path / 'articles').mkdir()
    (tmp_path / 'media/photo.webp').write_bytes(original)
    (tmp_path / 'articles/one.md').write_text('', encoding='utf-8')
    (tmp_path / 'manifest.json').write_text(json.dumps({'articles': [{'status': 'published', 'body_file': 'one.md', 'media': ['photo.webp'], 'card': {'file': 'photo.webp'}, 'hero': {'file': 'photo.webp', 'show': False}}]}), encoding='utf-8')
    built = build(tmp_path)
    image = built['images']['photo.webp']
    assert image['width'] > 960
    assert [variant['width'] for variant in image['variants']] == [480]
    assert all(variant['bytes'] < len(original) for variant in image['variants'])
    assert not list((tmp_path / 'media/responsive').rglob('960w.webp'))
    assert (tmp_path / 'media/photo.webp').read_bytes() == original


def test_public_catalog_and_git_article_serve_only_registered_derivatives(media_client):
    client, _ = media_client
    catalogue = client.get('/blog')
    assert catalogue.status_code == 200 and 'srcset=' in catalogue.text
    article = client.get('/blog/articles/pochemu-yapontsy-hudye-a-ty-net')
    assert article.status_code == 200
    body = article.text.split('<div class="article-body" id="article">', 1)[1].split('</article>', 1)[0]
    assert re.search(r'<img[^>]*src="/blog/media/[^"]+"[^>]*srcset=', body)
    variants = re.findall(r'/blog/media/(responsive/[a-f0-9]+-q90-v1/\d+w.webp)', article.text)
    assert variants
    response = client.get('/blog/media/' + variants[0])
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/webp'
    assert 'immutable' in response.headers['cache-control']
    assert client.get('/blog/media/responsive/unregistered/480w.webp').status_code == 404
    assert client.get('/blog/media/responsive/%2E%2E/manifest.json').status_code == 404


def test_api_published_body_gets_responsive_images_without_rewriting_markdown(media_client):
    client, engine = media_client
    catalog = load_blog_catalog()
    article = catalog.by_slug('pochemu-yapontsy-hudye-a-ty-net')
    mapping = responsive_manifest(catalog.content_dir)
    name = next(name for name in article.media if name in mapping and mapping[name]['variants'])
    markdown = f'Мой исходный текст.\n\n![Моя подпись](/blog/media/{name})'
    with Session(engine) as db:
        seed = ensure_existing_article(db, article.slug)
        draft = update_text(db, slug=article.slug, markdown=markdown, expected_version=seed.version_no, admin='test')
        published = publish_article(db, slug=article.slug, expected_version=draft.version_no, admin='test')
        assert published.payload['markdown'] == markdown
    html = client.get('/blog/articles/' + article.slug).text
    body = html.split('<div class="article-body" id="article">', 1)[1].split('</article>', 1)[0]
    assert 'Мой исходный текст.' in html and 'alt="Моя подпись"' in html
    image = re.search(r'<img[^>]*src="' + re.escape('/blog/media/' + name) + r'"[^>]*>', body)
    assert image is not None and 'srcset=' in image.group(0) and 'sizes=' in image.group(0)


def test_every_derivative_has_a_real_image_and_a_public_original():
    catalog = load_blog_catalog()
    images = responsive_manifest(catalog.content_dir)
    registered = derivative_files(catalog.content_dir, catalog.allowed_media)
    assert registered
    for name, image in images.items():
        assert name in catalog.allowed_media
        original = (catalog.content_dir / 'media' / name).read_bytes()
        assert hashlib.sha256(original).hexdigest() == image['sha256']
        for variant in image['variants']:
            assert variant['file'] in registered
            assert (catalog.content_dir / 'media' / variant['file']).stat().st_size < len(original)
            with Image.open(catalog.content_dir / 'media' / variant['file']) as rendered:
                assert rendered.size == (variant['width'], variant['height'])
