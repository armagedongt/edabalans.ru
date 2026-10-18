from html import unescape
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.site_links import relative_site_html, relative_site_url, public_site_origin


@pytest.mark.parametrize("origin", [
    "https://edabalans.ru", "https://app.edabalans.ru",
    "https://похудение-это-есть.рф", "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
])
def test_internal_links_keep_path_query_and_anchor_on_every_mirror(origin):
    assert relative_site_url(origin + "/lk?open=calories:step&x=1#part") == "/lk?open=calories:step&x=1#part"


@pytest.mark.parametrize("value", [
    "https://admin.похудение-это-есть.рф/crm", "https://old.похудение-это-есть.рф/hello",
    "https://app.edabalans.ru/sherbakova/", "https://edabalans.ru.evil.test/lk",
    "https://edabalans.ru@evil.test/lk", "https://user@edabalans.ru/lk",
    "https://edabalans.ru:444/lk", "https://edabalans.ru/%2f%2fevil.test",
    "https://edabalans.ru/%5cevil.test", "https://edabalans.ru/\nother",
    "https://[bad", "//evil.test/lk", "mailto:owner@example.test",
])
def test_external_and_unsafe_addresses_are_never_reinterpreted(value):
    assert relative_site_url(value) == value


def test_future_primary_domain_is_read_from_configuration(monkeypatch):
    monkeypatch.setenv("ACCOUNT_PUBLIC_URL", "https://future.example/lk")
    assert public_site_origin() == "https://future.example"
    assert relative_site_url("https://future.example/blog/a?x=1#heading") == "/blog/a?x=1#heading"
    assert relative_site_url("https://www.future.example/lk") == "/lk"


def test_html_rewrite_preserves_text_scripts_metadata_and_external_images():
    source = '''<p>https://edabalans.ru/lk</p>
<script>const example = '<a href="https://edabalans.ru/lk">';</script>
<link rel="canonical" href="https://edabalans.ru/blog/a">
<a class="button" href='https://edabalans.ru/lk?x=1&amp;y=2#part'>Войти</a>
<img src="https://app.edabalans.ru/media/reviews/v1/a.jpg" alt="Фото">
<img src="https://other.example/a.jpg">'''
    rendered = relative_site_html(source)
    assert rendered == source.replace(
        "href='https://edabalans.ru/lk?x=1&amp;y=2#part'", "href='/lk?x=1&amp;y=2#part'"
    ).replace('src="https://app.edabalans.ru/media/reviews/v1/a.jpg"', 'src="/media/reviews/v1/a.jpg"')
    assert relative_site_html(rendered) == rendered


def test_saved_course_versions_render_portably_without_mutating_source():
    from app.course_material_service import version_payload as masterclass
    from app.calorie_course_material_service import version_payload as calories
    source = '<p><a href="https://edabalans.ru/blog/a">Статья</a></p><img src="https://app.edabalans.ru/media/reviews/v1/a.jpg">'
    version = SimpleNamespace(text_content=source, version_no=7, imported_at=None, blocks=[])
    # Stored source is returned separately by the existing editorial source contract.
    from datetime import datetime, timezone
    version.imported_at = datetime.now(timezone.utc)
    for renderer in (masterclass, calories):
        result = renderer("step", 1, {}, version)
        assert 'href="/blog/a"' in result["html"]
        assert 'src="/media/reviews/v1/a.jpg"' in result["html"]
        assert result["source_content"] == source
        assert result["version"] == 7
        assert version.text_content == source


@pytest.mark.parametrize("prefix", ["", "https://edabalans.ru", "https://похудение-это-есть.рф"])
def test_embedded_audio_uses_current_origin_for_both_media_files(prefix):
    from app.article_markup import safe_audio_arguments
    source = '<iframe src="/course-assets/masterclass/audio-player?src=https%3A%2F%2Fapp.edabalans.ru%2Fmedia%2Freviews%2Fv1%2Fa.mp3&amp;avatar=https%3A%2F%2Fapp.edabalans.ru%2Fmedia%2Freviews%2Fv1%2Fa.webp&amp;author=Sergey&amp;duration=1%3A00"></iframe>'
    source = source.replace('src="/course-assets/', 'src="' + prefix + '/course-assets/')
    rendered = relative_site_html(source)
    query = parse_qs(urlsplit(unescape(rendered.split('src="', 1)[1].split('"', 1)[0])).query)
    assert query["src"] == ["/media/reviews/v1/a.mp3"]
    assert query["avatar"] == ["/media/reviews/v1/a.webp"]
    assert safe_audio_arguments(query["src"][0], query["avatar"][0], "Sergey", "1:00")
    assert not safe_audio_arguments("//evil.test/a.mp3", query["avatar"][0], "Sergey", "1:00")


@pytest.mark.parametrize("prefix", ["https://www.edabalans.ru", "http://edabalans.ru", "https://edabalans.ru:443"])
def test_saved_editorial_aliases_match_same_scope_and_published_reference(prefix):
    from app.editorial_media import image_url, references
    from app.blog_draft_service import markdown_media_from_saved
    name = "a" * 64 + ".png"
    path = image_url("blog:example", name)
    item = {"name": name, "storage": "editorial", "url": prefix + path}
    assert markdown_media_from_saved("example", {"media": [item]}) == [item]
    assert references(f"![Фото]({prefix}{path})", path)
    assert references(f'<img src="{prefix}{path}">', path)
    assert not references(f"![Фото](https://foreign.example{path})", path)
    assert not markdown_media_from_saved("other", {"media": [item]})


def test_html_attributes_do_not_rewrite_attribute_looking_alt_text():
    source = """<img alt='src="https://edabalans.ru/media/reviews/a.jpg"' src=https://edabalans.ru/media/reviews/a.jpg>"""
    assert relative_site_html(source) == source.replace(' src=https://edabalans.ru/media/reviews/a.jpg>', ' src="/media/reviews/a.jpg">')


def test_responsive_media_candidates_keep_descriptors_and_external_source():
    source = '<img srcset="https://edabalans.ru/media/reviews/a.webp 1x, https://other.example/b.webp 2x">'
    assert relative_site_html(source) == '<img srcset="/media/reviews/a.webp 1x, https://other.example/b.webp 2x">'
