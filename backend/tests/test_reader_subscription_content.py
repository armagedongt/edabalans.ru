import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.models import MessengerAccount
from app.public_site_routes import router as public_site_router
from app.public_site_content_service import (
    ensure_public_site_document,
    render_reader_subscription_source,
    seed_markdown,
)
from test_blog_reader_context import reader_client


SLUG = "reader-subscription"
EDITOR = f"/admin/api/public-site/content/{SLUG}"
ARTICLE = "/blog/pochemu-yapontsy-hudye"


@pytest.fixture
def editor(reader_client):
    client, engine, token, ids = reader_client
    client.app.include_router(public_site_router)
    client.app.dependency_overrides[require_admin] = lambda: "reader-test"
    return client, engine, token, ids


def source(settings, text="Изменённый владельцем текст"):
    return "```json\n" + json.dumps(settings, ensure_ascii=False, indent=2) + "\n```\n\n## Статья и подписка\n\n" + text + "\n\n## Только подписка\n\nПодпишитесь, чтобы не пропускать новые посты."


def test_approved_seed_copy_preserves_author_buttons_without_counter(editor):
    client, _, _, _ = editor
    html = client.get(ARTICLE).text.split('<dialog id="reader-popup"', 1)[1]
    assert ('Познакомьтесь с моим подходом поближе — читайте статью-инструкцию в моем канале '
            '<strong>«Как сделать похудение проще»</strong>.') in html
    assert html.index('reader-channel-actions') < html.index('reader-channel-footer')
    assert 'И не забудьте подписаться, чтобы не пропускать новые посты.' in html
    assert 'Сергей Воронцов 🍌' in html and 'Тренер по питанию' in html
    assert '/blog/assets/sergey-author-channel.webp' in html
    assert 'href="https://t.me/Fitness_Talks_bot/channel?startapp=site"' in html
    assert 'href="https://max.ru/id230409966750_biz"' in html
    assert 'Нас уже' not in html and '{{READER_' not in html


def test_existing_editor_updates_card_context_and_versions_without_deploy(editor):
    client, engine, token, ids = editor
    initial = client.get(EDITOR).json()["active"]
    settings = {**initial["settings"],
                "telegram_url": "https://t.me/Fitness_Talks_bot/channel?startapp=pk",
                "max_url": "https://max.ru/id230409966750_biz"}
    saved = client.put(EDITOR, json={"expected_version": initial["version"],
                                    "markdown": source(settings, "Один общий **текст**")})
    assert saved.status_code == 200, saved.text
    assert saved.json()["active"]["version"] == 2
    html = client.get(ARTICLE).text
    assert 'Один общий <strong>текст</strong>' in html
    assert f'href="{settings["telegram_url"]}"' in html
    assert f'href="{settings["max_url"]}"' in html
    assert client.get('/blog/reader/context').json()['telegram']['url'] == settings['telegram_url']
    assert client.get('/blog/reader/context').json()['max']['url'] == settings['max_url']
    assert client.post('/blog/reader/recognize', json={'token': token}).status_code == 204
    with Session(engine) as db:
        account = db.get(MessengerAccount, ids[2])
        account.main_scenario_seen_at = datetime.now(timezone.utc)
        db.commit()
        assert ensure_public_site_document(db, SLUG).version_no == 2
    context = client.get('/blog/reader/context').json()
    assert context['telegram']['url'] == settings['telegram_url']
    assert context['show_subscription'] is True
    assert client.put(EDITOR, json={"expected_version": 1, "markdown": seed_markdown(SLUG)}).status_code == 409


def test_editor_escapes_html_in_both_variants(editor):
    client, _, _, _ = editor
    initial = client.get(EDITOR).json()["active"]
    result = client.put(EDITOR, json={'expected_version': initial['version'],
                                    'markdown': source(initial['settings'], '<script>alert(1)</script>')})
    assert result.status_code == 200
    html = client.get(ARTICLE).text.split('<dialog id="reader-popup"', 1)[1]
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html


@pytest.mark.parametrize('patch', [
    {'telegram_url': 'javascript:alert(1)'},
    {'telegram_url': 'https://t.me.evil.test/post'},
    {'telegram_url': 'https://attacker@t.me/Fitness_Talks'},
    {'max_url': 'https://t.me/Fitness_Talks'},
    {'max_url': 'https://[invalid'},
    {'subscriber_count': -1}, {'subscriber_count': True}, {'subscriber_count': '7315'},
    {'auto_update': True},
])
def test_invalid_settings_fail_without_changing_active_document(editor, patch):
    client, _, _, _ = editor
    initial = client.get(EDITOR).json()['active']
    changed = source({**initial['settings'], **patch})
    response = client.put(EDITOR, json={'expected_version': initial['version'], 'markdown': changed})
    assert response.status_code == 422
    assert client.get(EDITOR).json()['active']['version'] == initial['version']


def test_missing_settings_and_anonymous_editor_are_rejected(editor):
    client, _, _, _ = editor
    initial = client.get(EDITOR).json()['active']
    response = client.put(EDITOR, json={'expected_version': initial['version'], 'markdown': 'Текст без настроек'})
    assert response.status_code == 422
    client.app.dependency_overrides.pop(require_admin)
    assert client.get(EDITOR).status_code == 401
    assert client.put(EDITOR, json={'expected_version': 1, 'markdown': seed_markdown(SLUG)}).status_code == 401


def test_invalid_source_json_is_reported_as_editor_error():
    with pytest.raises(HTTPException) as exc:
        render_reader_subscription_source('```json\n{invalid}\n```\nТекст')
    assert exc.value.status_code == 422


def test_editor_footer_is_separate_escaped_and_removed_for_subscribe_variant(editor):
    client, engine, token, ids = editor
    initial = client.get(EDITOR).json()["active"]
    changed = source(initial["settings"], "Article invitation\n\nFooter <script>alert(1)</script>")
    saved = client.put(EDITOR, json={"expected_version": initial["version"], "markdown": changed})
    assert saved.status_code == 200
    context = client.get('/blog/reader/context').json()
    assert context['copy_html'] == 'Article invitation'
    assert context['footer_html'] == 'Footer &lt;script&gt;alert(1)&lt;/script&gt;'
    from app.models import CourseEvent
    client.post('/blog/reader/recognize', json={'token': token})
    with Session(engine) as db:
        db.add(CourseEvent(user_id=ids[0], course_code='intensive',
                           event_key='footer-test-read', event_type='intensive_onepage_progress', details={'viewed_percent': 80}))
        db.commit()
    context = client.get('/blog/reader/context').json()
    assert context['subscription_variant'] == 'subscribe'
    assert context['footer_html'] == ''
