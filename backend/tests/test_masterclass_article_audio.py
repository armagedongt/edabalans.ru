from urllib.parse import urlencode

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.article_markup import markdown_to_article_html, sanitize_article_html
from app.masterclass_article_components import render_masterclass_component
from app.course_material_routes import router


ARGS = ["https://example.com/voice.mp3", "https://example.com/avatar.webp", "Сергей Воронцов", "9:00"]


def test_audio_component_survives_published_html_roundtrip():
    rendered = markdown_to_article_html(
        "audio(\n" + "\n".join(ARGS) + "\n)",
        component_renderer=render_masterclass_component,
    )
    assert '<div class="article-audio"><iframe' in rendered
    assert '/course-assets/masterclass/audio-player?' in rendered
    assert 'loading="lazy"' in rendered
    assert '<a ' not in rendered
    assert sanitize_article_html(rendered, course_semantics=True, allow_product_components=True) == rendered
    assert '<iframe' not in sanitize_article_html(rendered + '<p>Текст</p>', course_semantics=True)


@pytest.mark.parametrize('index,value', [
    (0, 'javascript:alert(1)'), (0, 'http://example.com/a.mp3'),
    (0, 'https://user:pass@example.com/a.mp3'), (0, 'https://example.com:88/a.mp3'),
    (0, 'https://[broken/a.mp3'), (0, 'https://example.com/%0aa.mp3'),
    (0, 'https://example.com/a.html'), (0, 'https://example.com/a.mp3#x'),
    (1, 'https://example.com/a.svg'), (1, '//example.com/a.png'),
    (2, ''), (2, 'x' * 101), (3, '9:99'), (3, '<img>'),
])
def test_audio_rejects_unsafe_or_invalid_arguments(index, value):
    args = ARGS.copy()
    args[index] = value
    with pytest.raises(HTTPException):
        render_masterclass_component('audio', args)


def test_audio_frame_rejects_duplicate_and_unknown_parameters():
    query = urlencode(dict(zip(('src', 'avatar', 'author', 'duration'), ARGS)))
    for suffix in ('&src=https://example.com/b.mp3', '&autoplay=1', '#x'):
        html = f'<iframe src="/course-assets/masterclass/audio-player?{query}{suffix}"></iframe><p>Текст</p>'
        assert '<iframe' not in sanitize_article_html(html, course_semantics=True, allow_product_components=True)


def test_player_endpoint_escapes_text_and_has_controls_without_autoplay():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    params = dict(zip(('src', 'avatar', 'author', 'duration'), ARGS))
    params['author'] = '\"><img src=x onerror=alert(1)> {{src}}'
    response = client.get('/course-assets/masterclass/audio-player', params=params)
    assert response.status_code == 200
    assert '&lt;img src=x onerror=alert(1)&gt; {{src}}' in response.text
    assert '<img src=x' not in response.text
    assert 'data-voice-play' in response.text and 'data-voice-seek' in response.text
    assert 'data-voice-speed' in response.text
    assert 'preload="none"' in response.text and 'autoplay' not in response.text
    assert 'width:100%' in response.text
    params['src'] = 'javascript:alert(1)'
    assert client.get('/course-assets/masterclass/audio-player', params=params).status_code == 422
