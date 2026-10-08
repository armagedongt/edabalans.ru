"""Install educational examples through the real shared and product renderers."""
from html import escape, unescape
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def page(title: str, body: str, css: str, script: str = "", *, article_class: str = "",
         base_url: str = "https://edabalans.ru/") -> str:
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow">'
            f'<base href="{escape(base_url, quote=True)}">'
            f'<title>{escape(title)}</title><style>{css}\n'
            'body{margin:24px auto;padding:0 16px;max-width:760px}'
            '</style></head><body>'
            '<p>Учебный пример. Он не публикуется на сайте. Медиа требуют интернет.</p>'
            f'<article id="article" class="{escape(article_class, quote=True)}">{body}</article>'
            + (f'<script>{script}</script>' if script else '') + '</body></html>')


def local_media_links(body: str) -> str:
    # Existing players prohibit file-origin iframe parents. Open the same player
    # separately, without changing its CSP or creating another player engine.
    def replace(match):
        source = unescape(match.group(1))
        title = unescape(match.group(2))
        return (f'<p><a href="{escape(source, quote=True)}" target="_blank" rel="noopener">'
                f'Открыть плеер: {escape(title)}</a></p>')
    return re.sub(r'<iframe src="([^"]+)"[^>]* title="([^"]+)"[^>]*></iframe>', replace, body)


def blog_example(markdown: str) -> str:
    from app.article_markup import markdown_to_article_html
    from app.blog_content import (add_heading_anchors, insert_inline_related, load_blog_catalog,
                                  related_cards_html, render_blog_component)
    matches = re.findall(r"<!-- example-blog-source-id: ([a-zA-Z0-9_-]+) -->", markdown)
    if len(matches) != 1:
        raise ValueError("У примера блога должна быть одна ссылка на существующую manifest-запись")
    catalog = load_blog_catalog()
    article = catalog.by_source_id(matches[0])
    if article is None or article.inline_related is None:
        raise ValueError("В manifest нет статьи с выбранной вставкой «Читайте также»")
    calls = []

    def component(name, arguments):
        if name != "blog_cta" or arguments != [article.cta]:
            raise ValueError("Баннер примера должен совпадать с CTA manifest-статьи")
        calls.append(name)
        return render_blog_component(name, arguments)

    rendered, _ = add_heading_anchors(markdown_to_article_html(markdown, component_renderer=component))
    if len(calls) != 1:
        raise ValueError("В примере должен быть ровно один баннер")
    with_related = insert_inline_related(catalog, article, rendered)
    if with_related == rendered:
        raise ValueError("Заголовок примера не совпадает с местом «Читайте также» в manifest")
    return with_related + '<section class="related-section"><h2>Связанные статьи</h2><div class="article-grid">' + related_cards_html(catalog, article) + '</div></section>'


def install(root: Path) -> None:
    from app.article_markup import markdown_to_article_html
    source = REPO / "content/article-components"
    folder = root / "Шпаргалка"
    folder.mkdir(parents=True, exist_ok=True)
    guide = (source / "MARKDOWN_GUIDE.md").read_text(encoding="utf-8")
    guide = guide.replace("[каталоге компонентов](../masterclass/components/README.md)", "каталоге компонентов проекта (Codex знает его)")
    guide = guide.replace("../../docs/knowledge-base/EDITORIAL_VAULT.md", "<../Правила публикации.md>")
    guide = guide.replace("examples/common.md", "Пример.md")
    guide = guide.replace("examples/masterclass.md", "Вставки МК.md").replace("examples/blog.md", "Вставки блога.md")
    (folder / "Шпаргалка.md").write_text(guide, encoding="utf-8")
    markdown = (source / "examples/common.md").read_text(encoding="utf-8")
    (folder / "Пример.md").write_text(markdown, encoding="utf-8")
    css = "\n".join((source / name).read_text(encoding="utf-8") for name in ("typography.css", "note.css"))
    html = page("Пример разметки", markdown_to_article_html(markdown), css)
    (folder / "Пример.html").write_text(html, encoding="utf-8")
    from app.masterclass_article_components import component_styles, render_masterclass_component
    components = REPO / "content/masterclass/components"
    course_css = (REPO / "backend/app/static/course-visual.css").read_text(encoding="utf-8")
    course_css += '\n' + css + '\n' + component_styles()
    slider = (components / "dqs-image-slider/slider.js").read_text(encoding="utf-8")
    masterclass = (source / "examples/masterclass.md").read_text(encoding="utf-8")
    (folder / "Вставки МК.md").write_text(masterclass, encoding="utf-8")
    body = local_media_links(markdown_to_article_html(masterclass, component_renderer=render_masterclass_component))
    (folder / "Вставки МК.html").write_text(page("Вставки МК", body, course_css,
        slider + '\nwindow.bindGallery(document);', article_class="article"), encoding="utf-8")
    blog = (source / "examples/blog.md").read_text(encoding="utf-8")
    (folder / "Вставки блога.md").write_text(blog, encoding="utf-8")
    blog_css = (REPO / "backend/app/static/blog/assets/blog.css").read_text(encoding="utf-8")
    (folder / "Вставки блога.html").write_text(page("Вставки блога", blog_example(blog),
        blog_css + '\n' + css, article_class="article-body",
        base_url="https://blog.похудение-это-есть.рф/"), encoding="utf-8")


if __name__ == "__main__":
    install(Path(sys.argv[1]))
