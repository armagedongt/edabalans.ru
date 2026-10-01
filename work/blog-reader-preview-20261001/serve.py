"""Loopback-only reader prototype; no database, publication or identity API."""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import mimetypes
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.blog_content import load_blog_catalog, render_article_body, related_cards_html, toc_html, render_blog_component

HERE = Path(__file__).resolve().parent
STATIC = ROOT / "backend/app/static/blog"


def page():
    catalog = load_blog_catalog()
    article = catalog.by_source_id("11927800")
    body, toc = render_article_body(catalog, article)
    # Placement belongs to this disposable preview, not to the author's Markdown.
    inserts = (
        ("Принцип №5. Достаточно времени", "habits-formation-and-one-percent"),
        ("Вот так и закладывается фундамент здоровья на всю жизнь.", "tilda-49745867"),
    )
    for heading, source_id in inserts:
        target = catalog.by_source_id(source_id)
        card = (f'<aside class="reader-related"><a href="/articles/{target.slug}">'
                f'<small>↗ Читайте также</small><strong>{escape(target.title)}</strong>'
                f'<span>{escape(target.excerpt)}</span></a></aside>')
        body = re.sub(r'(<h2 id="[^"]+">' + re.escape(heading) + r'</h2>)', lambda m: card + m[0], body, count=1)
    channel = render_blog_component("blog_cta", ["telegram"])
    channel = channel.replace('class="blog-cta ', 'class="reader-channel blog-cta ')
    channel = channel.replace('<span class="blog-cta-eyebrow">', '<img class="reader-avatar" src="/blog/assets/sergey-author-v2.webp" alt="Сергей Воронцов"><span class="blog-cta-eyebrow">')
    inline = '<div id="reader-channel-inline" hidden>' + channel + '</div>'
    body = re.sub(r'(<h2 id="[^"]+">Принцип №4\.)', lambda m: inline + m[0], body, count=1)
    # The requested demo uses intensive; the production masterclass assignment is untouched.
    body = re.sub(r'<section class="blog-cta blog-cta-masterclass".*?</section>', lambda _: render_blog_component("blog_cta", ["intensive"]), body, count=1, flags=re.DOTALL)
    items = ''.join(f'<li><a href="#{escape(a, quote=True)}">{escape(t)}</a></li>' for a, t in toc)
    navigation = (STATIC / "article.html").read_text(encoding="utf-8").split('<nav class="nav"')[1].split('</nav>')[0]
    # Reuse the current destinations. The preview sheet gets independent ids.
    navigation = '<nav class="reader-site-menu"' + navigation + '</nav>'
    navigation = navigation.replace('id="public-blog-nav"', 'id="reader-site-nav"').replace('blog-contact-panel', 'reader-contact-panel')
    panel = f'<strong>В этом материале</strong><ol>{items}</ol>'
    extra = f'''
<div class="reader-preview-controls"><label>Локальный пример · посетитель
<select id="reader-visitor"><option value="unknown">Не опознан</option><option value="unsubscribed">Опознан, не подписан</option><option value="subscribed">Подписан</option></select></label>
<button id="reader-show-popup" type="button" disabled>Показать popup для проверки</button><span>Тестовый режим, не настоящая авторизация</span></div>
<aside class="reader-sidebar" aria-label="Новое содержание">{panel}</aside>
<div class="reader-bottom"><button type="button" id="reader-top" aria-label="Наверх">↑</button><button type="button" id="reader-menu" aria-haspopup="dialog">☰ Содержание и меню</button></div>
<dialog id="reader-sheet" aria-label="Содержание и меню"><button class="reader-close" type="button" aria-label="Закрыть содержание">×</button>{navigation}<nav aria-label="Новое содержание">{panel}</nav></dialog>
<aside id="reader-popup" aria-label="Приглашение в Telegram-канал" hidden><button class="reader-close" type="button" aria-label="Закрыть приглашение">×</button>{channel}</aside>
'''
    template = (STATIC / "article.html").read_text(encoding="utf-8")
    replacements = {"{{TITLE}}": escape(article.title), "{{DESCRIPTION}}": escape(article.excerpt, quote=True), "{{CATEGORY}}": escape(article.category), "{{CANONICAL}}": "", "{{HERO_ABSOLUTE}}": "", "{{HERO}}": "", "{{ARTICLE_BODY}}": body, "{{TOC_DESKTOP}}": toc_html(toc, mobile=False), "{{TOC_MOBILE}}": toc_html(toc, mobile=True), "{{RELATED_CARDS}}": related_cards_html(catalog, article), "{{STRUCTURED_DATA}}": "{}"}
    for key, value in replacements.items():
        template = template.replace(key, value)
    template = template.replace('</head>', '<meta name="robots" content="noindex,nofollow"><link rel="stylesheet" href="/preview/reader.css"></head>')
    template = template.replace('<main>', extra + '<main>')
    template = template.replace('</body>', '<script src="/preview/reader.js" defer></script></body>')
    return template


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/articles/pochemu-yapontsy-hudye-a-ty-net'):
            self.send_data(page().encode(), 'text/html; charset=utf-8')
            return
        roots = {'/preview/': HERE, '/blog/assets/': STATIC / 'assets', '/blog/fonts/': STATIC / 'fonts', '/blog/media/': ROOT / 'content/blog/media'}
        if path in ('/blog/assets/article-typography.css', '/blog/assets/article-note.css'):
            name = 'typography.css' if 'typography' in path else 'note.css'
            file = ROOT / 'content/article-components' / name
        else:
            file = None
            for prefix, root in roots.items():
                if path.startswith(prefix):
                    candidate = (root / path[len(prefix):]).resolve()
                    if candidate.is_relative_to(root.resolve()):
                        file = candidate
                    break
        if file and file.is_file():
            self.send_data(file.read_bytes(), mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        elif path.startswith('/articles/'):
            target = load_blog_catalog().by_slug(path.split('/')[-1])
            if target:
                self.send_response(302)
                self.send_header('Location', 'https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/articles/' + target.slug)
                self.end_headers()
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def send_data(self, data, kind):
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Robots-Tag', 'noindex, nofollow')
        self.end_headers()
        self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8771), Handler).serve_forever()
