import pytest
from fastapi import HTTPException

from app.article_markup import markdown_to_article_html, sanitize_article_html
from app.masterclass_article_components import render_masterclass_component


SOURCE = 'https://telegra.ph/file/c614abe3c7ffdfc43b93e.mp4'


def test_video_uses_only_standard_player_without_caption_link_or_autoplay():
    rendered = markdown_to_article_html(
        f'video(\n{SOURCE}\nПоели — подвигались!\n)',
        component_renderer=render_masterclass_component,
    )
    assert '<div class="media"><iframe src="/apps/video-player.html?src=https%3A%2F%2Ftelegra.ph%2Ffile%2Fc614abe3c7ffdfc43b93e.mp4"' in rendered
    assert 'title="Поели — подвигались!" loading="lazy"' in rendered
    assert 'allowfullscreen></iframe></div>' in rendered
    assert '<a ' not in rendered
    assert '<p>' not in rendered
    assert 'autoplay' not in rendered
    assert sanitize_article_html(rendered, course_semantics=True, allow_product_components=True) == rendered


@pytest.mark.parametrize('source', [
    'http://example.com/a.mp4', '//example.com/a.mp4', 'javascript:alert(1)',
    'https://user:pass@example.com/a.mp4', 'https://example.com/a.html',
    'https://example.com/a.mp4#x', 'https://example.com:8000/a.mp4',
    'https://example.com/%0aa.mp4', 'https://example.com/%5ca.mp4',
    ' https://example.com/a.mp4', 'https://[broken/a.mp4',
])
def test_video_rejects_unsafe_or_unsupported_sources(source):
    with pytest.raises(HTTPException) as caught:
        render_masterclass_component('video', [source, 'Видео'])
    assert caught.value.status_code == 422


@pytest.mark.parametrize('arguments', [[], [SOURCE], [SOURCE, ''], [SOURCE, 'a' * 201], [SOURCE, 'a', 'b']])
def test_video_requires_source_and_short_title(arguments):
    with pytest.raises(HTTPException):
        render_masterclass_component('video', arguments)


def test_video_escapes_title_and_cannot_inject_frame_attributes():
    html = render_masterclass_component('video', [SOURCE, '\"><img src=x onerror=alert(1)>'])
    rendered = sanitize_article_html(html, course_semantics=True, allow_product_components=True)
    assert '<img' not in rendered
    assert 'title="&quot;&gt;&lt;img' in rendered


def test_plain_html_cannot_embed_even_the_standard_player():
    html = render_masterclass_component('video', [SOURCE, 'Видео']) + '<p>Текст</p>'
    assert '<iframe' not in sanitize_article_html(html, course_semantics=True)


@pytest.mark.parametrize('src', [
    'https://example.com/frame', '/apps/video-player.html?src=javascript:alert(1)',
    '/apps/video-player.html?src=https://example.com/a.mp4&src=https://example.com/b.mp4',
    '/apps/video-player.html?src=https://example.com/a.mp4&autoplay=1',
    '/apps/video-player.html?src=https://example.com/a.mp4#x',
])
def test_trusted_html_still_rejects_arbitrary_frames(src):
    html = f'<iframe src="{src}"></iframe><p>Текст</p>'
    assert '<iframe' not in sanitize_article_html(html, course_semantics=True, allow_product_components=True)


def test_blocked_parent_does_not_leak_trusted_frame():
    html = '<object>' + render_masterclass_component('video', [SOURCE, 'Видео']) + '</object><p>Текст</p>'
    assert sanitize_article_html(html, course_semantics=True, allow_product_components=True) == '<p>Текст</p>'
