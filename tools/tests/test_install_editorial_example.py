from html.parser import HTMLParser
import os
import subprocess
import sys

import pytest

from tools import install_editorial_example as examples


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def with_class(self, value):
        return [(tag, attrs) for tag, attrs in self.tags if value in attrs.get("class", "").split()]


def test_install_keeps_common_and_renders_real_product_components(tmp_path):
    examples.install(tmp_path)
    folder = tmp_path / "Шпаргалка"
    assert (folder / "Пример.md").read_text(encoding="utf-8") == (examples.REPO / "content/article-components/examples/common.md").read_text(encoding="utf-8")
    common = Elements((folder / "Пример.html").read_text(encoding="utf-8"))
    assert common.with_class("article-note-accent")
    html = (folder / "Вставки МК.html").read_text(encoding="utf-8")
    elements = Elements(html)
    for component in ("dqs-score-table", "article-gallery", "article-spoiler", "article-audio", "media", "recipe-card"):
        assert len(elements.with_class(component)) == 1
    assert len(elements.with_class("gallery-slide")) == 2
    assert "window.bindGallery(document);" in html
    assert [(attrs["href"]) for tag, attrs in elements.tags if tag == "base"] == ["https://edabalans.ru/"]
    assert not any(tag == "iframe" for tag, attrs in elements.tags)
    players = [attrs for tag, attrs in elements.tags if tag == "a" and attrs.get("target") == "_blank"]
    assert any(attrs["href"].startswith("/apps/video-player.html?src=") for attrs in players)
    assert any(attrs["href"].startswith("/course-assets/masterclass/audio-player?") for attrs in players)
    assert all(attrs["rel"] == "noopener" for attrs in players)
    download = elements.with_class("recipe-card-save")[0][1]
    assert "download" in download and download["href"].startswith("/course-assets/masterclass/media/15-recipes/")
    assert (folder / "Вставки МК.md").read_text(encoding="utf-8") == (examples.REPO / "content/article-components/examples/masterclass.md").read_text(encoding="utf-8")
    assert "/bot-api/" not in html and "onepage-tracking" not in html


def test_blog_installed_example_uses_real_manifest_related_targets(tmp_path):
    from app.blog_content import load_blog_catalog
    examples.install(tmp_path)
    folder = tmp_path / "Шпаргалка"
    html = (folder / "Вставки блога.html").read_text(encoding="utf-8")
    parsed = Elements(html)
    assert [attrs["href"] for tag, attrs in parsed.tags if tag == "base"] == ["https://blog.похудение-это-есть.рф/"]
    article = load_blog_catalog().by_source_id("amkbo7kgg1")
    target = load_blog_catalog().by_source_id(article.inline_related.source_id)
    assert len(parsed.with_class("blog-cta")) == 1
    assert len(parsed.with_class("reader-related")) == 1
    assert len(parsed.with_class("article-card")) == len(article.related_source_ids)
    assert len(parsed.with_class("article-grid")) == 1
    assert html.index('class="reader-related"') < html.index('id="' + article.inline_related.before_heading + '"')
    assert any(tag == "a" and attrs.get("href") == "/articles/" + target.slug for tag, attrs in parsed.tags)
    assert (folder / "Вставки блога.md").read_text(encoding="utf-8") == (examples.REPO / "content/article-components/examples/blog.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("change,error", [
    (lambda md: md.replace("masterclass\n)", "intensive\n)"), "CTA"),
    (lambda md: md.replace("## А как посчитать расход калорий на тренировках", "## Другой раздел"), "Заголовок"),
    (lambda md: md.replace("amkbo7kgg1", "not-an-article"), "manifest"),
])
def test_blog_demo_never_invents_cta_or_readmore_hook(change, error):
    markdown = (examples.REPO / "content/article-components/examples/blog.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        examples.blog_example(change(markdown))


def test_normal_owner_install_does_not_require_or_initialize_database(tmp_path):
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    script = ("from pathlib import Path; import sys; "
              "from tools.install_editorial_example import install; "
              "install(Path(sys.argv[1])); "
              "assert 'app.database' not in sys.modules; "
              "assert 'app.config' not in sys.modules; "
              "assert 'app.course_material_routes' not in sys.modules")
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=examples.REPO,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "Шпаргалка/Вставки МК.html").is_file()
    assert (tmp_path / "Шпаргалка/Вставки блога.html").is_file()
