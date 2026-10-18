import json
import os
import re
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://test:test@127.0.0.1:5432/test')
os.environ.setdefault('ADMIN_USERNAME', 'admin@example.com')
os.environ.setdefault('ADMIN_PASSWORD', 'test-admin-password')

from fastapi.testclient import TestClient
from app import admin_assets, knowledge_routes
from app.config import get_settings
from app.main import app


def client():
    get_settings.cache_clear()
    c = TestClient(app, base_url='https://admin.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai')
    assert c.post('/admin/api/login', json={'username': 'admin@example.com', 'password': 'test-admin-password'}).status_code == 200
    return c


def test_navigation_is_authenticated_and_only_contains_catalog_fields(tmp_path, monkeypatch):
    assert TestClient(app).get('/admin/api/navigation').status_code == 401
    original = knowledge_routes.read_project_map()
    source = tmp_path / 'map.json'
    source.write_text(json.dumps(original), encoding='utf-8')
    monkeypatch.setattr(knowledge_routes, 'PROJECT_MAP_PATH', source)
    knowledge_routes._navigation_snapshot.cache_clear()
    c = client()
    expected = [{'id': m['id'], 'admin_catalog': m['admin_catalog']} for m in original['modules'] if m.get('admin_catalog')]
    with patch.object(knowledge_routes, 'read_project_map', wraps=knowledge_routes.read_project_map) as read:
        first = c.get('/admin/api/navigation')
        assert first.status_code == 200
        assert first.json() == {'modules': expected}
        assert first.headers['cache-control'] == 'no-store'
        assert len(first.content) < 20000
        assert c.get('/admin/api/navigation').json() == first.json()
        assert read.call_count == 1
        target = next(m for m in original['modules'] if m.get('admin_catalog'))
        target['admin_catalog'][0]['label'] = 'Обновлённый раздел'
        source.write_text(json.dumps(original, ensure_ascii=False), encoding='utf-8')
        updated = c.get('/admin/api/navigation')
        assert updated.json()['modules'][0]['admin_catalog'][0]['label'] == 'Обновлённый раздел'
        assert read.call_count == 2
    source.write_text('{broken', encoding='utf-8')
    assert c.get('/admin/api/navigation').status_code == 503
    source.unlink()
    assert c.get('/admin/api/navigation').status_code == 503


def test_code_versions_cache_and_authentication_boundaries():
    c = client()
    page = c.get('/crm')
    assert page.headers['cache-control'] == 'no-store'
    assets = re.findall(r'(?:src|href)="(/(?:admin/static/|crm/)[^"?]+\.(?:js|css)\?v=[0-9a-f]{64})"', page.text)
    assert any('/crm/crm.js?' in url for url in assets)
    assert any('/admin/static/admin-shell.js?' in url for url in assets)
    for url in assets:
        response = c.get(url)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'private, max-age=31536000, immutable'
        assert c.get(url, headers={'If-None-Match': response.headers['etag']}).status_code == 304
        assert TestClient(app).get(url, headers={'If-None-Match': response.headers['etag']}).status_code == 401
        stale = c.get(url.split('?')[0] + '?v=old')
        assert stale.headers['cache-control'] == 'private, no-cache'
    assert c.get('/admin/api/audit/tags').headers['cache-control'] == 'no-store'
    c.post('/admin/api/logout')
    assert c.get(assets[0], headers={'If-None-Match': response.headers['etag']}).status_code == 401


def test_shared_application_pages_use_current_code_versions():
    c = client()
    for route in ('/admin/dqs', '/admin/strength', '/admin/metabolism'):
        page = c.get(route)
        assert page.status_code == 200
        assert page.headers['cache-control'] == 'no-store'
        assert re.search(r'/admin/static/admin-shell\.js\?v=[0-9a-f]{64}', page.text)
        assert re.search(r'/admin/static/admin\.js\?v=[0-9a-f]{64}', page.text)


def test_changed_code_changes_html_version_without_restart(tmp_path, monkeypatch):
    (tmp_path / 'crm.js').write_text('old code', encoding='utf-8')
    (tmp_path / 'crm.html').write_text('<script src="/crm/crm.js?v=old"></script>', encoding='utf-8')
    monkeypatch.setattr(admin_assets, 'STATIC_DIR', tmp_path)
    old_html = admin_assets.admin_file('crm.html').body
    (tmp_path / 'crm.js').write_text('new released code', encoding='utf-8')
    new_html = admin_assets.admin_file('crm.html').body
    assert old_html != new_html
    assert b'?v=old' not in new_html
