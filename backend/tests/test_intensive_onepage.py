from html.parser import HTMLParser
from pathlib import Path
import os
import re
import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')

from sqlalchemy import select

from app.intensive_onepage import GROUPS, SOURCE, render_article, render_source
from app.intensive_web_access import issue_access_token
from app.main import app
from app.models import CourseEvent, CourseStageProgress, UserOffer
from test_intensive_web_access import make_client, create_user


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_public_article_archive_and_assets():
    client, factory = make_client()
    try:
        page = client.get('/intensive')
        assert page.status_code == 200
        assert 'data-intensive-identified="false"' in page.text
        assert '<!--' not in page.text
        assert 'ПЕРЕД ПУБЛИКАЦИЕЙ' not in page.text
        assert page.headers['cache-control'] == 'no-store'
        assert client.get('/intensive/').text == page.text
        archive = client.get('/intensive/archive')
        assert archive.content == (Path(__file__).parents[1] / 'app/static/intensive/index.html').read_bytes()
        assert client.get('/intensive/menu').text == archive.text
        assert 'data-view="menu"' in archive.text
        for tag, attrs in Elements(page.text).tags:
            url = attrs.get('src') or attrs.get('href')
            if url and url.startswith('/') and not url.startswith('//'):
                assert client.get(url).status_code == 200, url
        assert client.get('/intensive/onepage-secret.txt').status_code == 404
        assert client.get('/intensive/assets/roadmap/not-found.png').status_code == 404
        with factory() as db:
            assert db.scalar(select(CourseEvent)) is None
    finally:
        app.dependency_overrides.clear()


def test_personal_entry_strips_both_code_aliases_before_analytics_and_retains_attribution():
    client, factory = make_client()
    user = create_user(factory)
    try:
        with factory() as db:
            token, _ = issue_access_token(db, user.id, 'telegram')
            db.commit()
        for key in ['i', 'token']:
            client.cookies.clear()
            entry = client.get(f'/intensive?{key}={token}&utm_source=yandex&yclid=123&from=tg', follow_redirects=False)
            assert entry.status_code == 303
            assert token not in entry.headers['location']
            assert 'utm_source=yandex&yclid=123&from=tg' in entry.headers['location']
            assert 'HttpOnly' in entry.headers['set-cookie']
            assert entry.headers['referrer-policy'] == 'no-referrer'
            page = client.get(entry.headers['location'])
            assert 'data-intensive-identified="true"' in page.text
            assert token not in page.text
        assert client.get('/intensive?i=invalid').status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_personal_onepage_facts_are_validated_deduplicated_and_do_not_start_legacy_or_offer():
    client, factory = make_client()
    user = create_user(factory)
    try:
        payload = {'event_type':'intensive_onepage_end','event_id':'end-1'}
        assert client.post('/api/intensive/events', json=payload).status_code == 401
        with factory() as db:
            token, _ = issue_access_token(db, user.id, 'telegram')
            db.commit()
        client.get(f'/intensive?i={token}')
        for event, detail in [
            ('intensive_onepage_open', {}),
            *[('intensive_onepage_section', {'section':section}) for section in ['block-1','block-2','block-3','actions']],
            ('intensive_onepage_end', {}),
            *[('intensive_onepage_messenger_click', {'messenger':channel}) for channel in ['telegram','max']]
        ]:
            for attempt in range(2):
                response = client.post('/api/intensive/events', json={
                    'event_type':event, 'event_id':f'{event}-{attempt}', **detail,
                    'user_id':'forged', 'platform':'max', 'token':'never-store', 'utm_term':'untrusted'
                })
                assert response.status_code == 200, response.text
        assert client.post('/api/intensive/events', json={**payload,'event_type':'intensive_onepage_section','section':'bad'}).status_code == 422
        with factory() as db:
            rows = list(db.scalars(select(CourseEvent)))
            assert len(rows) == 8
            assert {row.details['section'] for row in rows if row.event_type == 'intensive_onepage_section'} == {'block-1','block-2','block-3','actions'}
            assert {row.details['messenger'] for row in rows if row.event_type == 'intensive_onepage_messenger_click'} == {'telegram','max'}
            assert all(row.user_id == user.id and row.details['platform'] == 'telegram' for row in rows)
            assert all('never-store' not in str(row.details) and 'untrusted' not in str(row.details) for row in rows)
            assert db.scalar(select(CourseStageProgress)) is None
            assert db.scalar(select(UserOffer)) is None
    finally:
        app.dependency_overrides.clear()


def test_renderer_preserves_markers_toc_and_safe_text():
    source = SOURCE.read_text(encoding='utf-8')
    _, body, toc = render_article(source + '\n\n<script>alert(1)</script>\n\n> First line.\n> Second line.\n')
    tags = Elements(body).tags
    assert 'script' not in [tag for tag, _ in tags]
    assert '<blockquote>First line.<br>Second line.</blockquote>' in body
    sections = [attrs['data-intensive-section'] for _, attrs in tags if 'data-intensive-section' in attrs]
    assert sections == ['block-1','block-2','block-3','actions']
    ids = [attrs['id'] for _, attrs in tags if 'id' in attrs]
    assert len(set(ids)) == len(ids)
    assert all(attrs['href'][1:] in ids for tag, attrs in Elements(toc).tags if tag == 'a')
    assert len([1 for tag, attrs in tags if tag == 'img' and attrs.get('class') != 'social-logo']) == len(re.findall(r'^!\[', source, re.M))


def test_article_heading_hierarchy_preserves_existing_links_without_duplicate_toc_groups():
    source = SOURCE.read_text(encoding='utf-8')
    _, body, toc = render_article(source)
    group_labels = [label for _, label, _ in GROUPS]
    assert re.findall(r'<h2(?: [^>]*)?>(.*?)</h2>', body) == group_labels
    assert re.search(r'<h3 id="section-\d+">', body)
    for label in group_labels:
        assert toc.count(f'>{label}</a>') == 1

    # The three new group headings must not shift links published before this layout.
    previous = source
    for label in group_labels[:-1]:
        previous = previous.replace(f'## {label}\n', '')
    _, previous_body, _ = render_article(previous)
    section_links = r'<h[23] id="(section-\d+)">(.*?)</h[23]>'
    assert re.findall(section_links, body) == re.findall(section_links, previous_body)
    fixture = (
        f'# Test\n\n## {group_labels[0]}\n\n### A\n\n### B\n\n'
        f'## {group_labels[1]}\n\n### C\n\n'
        f'## {group_labels[2]}\n\n### D\n\n## {group_labels[-1]}\n'
    )
    _, numbered, _ = render_source(fixture)
    assert re.findall(section_links, numbered) == [
        ('section-1', 'A'), ('section-2', 'B'), ('section-3', 'C'),
        ('section-4', 'D'), ('section-5', group_labels[-1]),
    ]


@pytest.mark.parametrize('destination', ['', 'https://max.ru/id230409966750_biz'])
def test_max_button_retains_brand_and_only_tracks_when_it_has_a_destination(destination):
    source = re.sub(r'> \[Открыть MAX\]\([^\n]*\)', f'> [Открыть MAX]({destination})', SOURCE.read_text(encoding='utf-8'))
    _, body, _ = render_article(source)
    tags = Elements(body).tags
    max_button = next(attrs for tag, attrs in tags if tag == 'a' and attrs.get('class') == 'social-max')
    telegram = next(attrs for tag, attrs in tags if tag == 'a' and attrs.get('class') == 'social-telegram')
    assert telegram['href'].startswith('https://t.me/')
    assert telegram['data-intensive-channel'] == 'telegram'
    assert any(tag == 'img' and attrs.get('src') == '/intensive/max-full-colored-official.png' for tag, attrs in tags)
    if destination:
        assert max_button['href'] == destination
        assert max_button['data-intensive-channel'] == 'max'
        assert 'aria-disabled' not in max_button
    else:
        assert max_button['aria-disabled'] == 'true'
        assert 'href' not in max_button
        assert 'data-intensive-channel' not in max_button


def test_empty_telegram_destination_is_rejected():
    source = re.sub(r'> \[Telegram\]\([^\n]*\)', '> [Telegram]()', SOURCE.read_text(encoding='utf-8'))
    with pytest.raises(ValueError, match='Only the MAX button'):
        render_article(source)
