"""Read-only local formatting stand. No database, publication or course mutation."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from html import escape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
from types import ModuleType
from uuid import uuid4
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = HERE / "01-99 — Тест переноса Markdown.md"
REF = "99051db9b3e3435861e220d95e2cb7a516481157"
SHELL_REF = "f151218ee685857ffd32ae02dc75b915328093a9"
DEMO_STEP = "local-day-01-md-formatting"
COMPONENTS = ROOT / 'content/article-components'


def git_file(path: str, ref: str = REF) -> bytes:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT,
        capture_output=True, check=True,
    ).stdout


def load_renderer() -> ModuleType:
    module = ModuleType("demo_article_markup")
    exec(compile(git_file("backend/app/article_markup.py"), "article_markup.py", "exec"), module.__dict__)
    return module


RENDERER = load_renderer()
RENDERER.COURSE_TAGS.update({'del', 'mark', 'code', 'pre'})
RENDERER.COURSE_CLASS_TOKENS.update({'article-note-accent', 'article-copy-block', 'article-copy-button'})
RENDERER.COURSE_CLASS_TOKENS.update({'article-actions', 'article-actions-stack', 'article-actions-row', 'article-actions-center'})
INLINE_PATTERNS = re.compile(
    r'\[((?:\\[\[\]]|[^\]])+)\]\((https?://[^\s)]+|/(?!/)[^\s)]+)\)'
    r'|\*\*\*(.+?)\*\*\*|___(.+?)___|\*\*(.+?)\*\*|__(.+?)__'
    r'|~~(.+?)~~|==(.+?)==|(?<!\*)\*([^*]+)\*(?!\*)|(?<![\w_])_([^_]+)_(?![\w_])'
)


def inline_formatting(value: str) -> str:
    parts = []
    position = 0
    tags = [('strong', 'em'), ('strong', 'em'), ('strong',), ('strong',),
        ('del',), ('mark',), ('em',), ('em',)]
    for match in INLINE_PATTERNS.finditer(value):
        parts.append(escape(value[position:match.start()]))
        if match.group(1) is not None:
            label = match.group(1).replace(r'\[', '[').replace(r'\]', ']')
            parts.append('<a href="' + escape(match.group(2), quote=True) +
                '" target="_blank" rel="noopener">' + inline_formatting(label) + '</a>')
        else:
            index = next(index for index, item in enumerate(match.groups()[2:]) if item is not None)
            inner = inline_formatting(match.groups()[index + 2])
            for tag in reversed(tags[index]):
                inner = '<' + tag + '>' + inner + '</' + tag + '>'
            parts.append(inner)
        position = match.end()
    parts.append(escape(value[position:]))
    return ''.join(parts)


RENDERER.inline_markdown = inline_formatting


def encoded_component(name: str, values: list[str]) -> str:
    payload = base64.b64encode(json.dumps(values).encode()).decode()
    return '\n' + name + '(\n' + payload + '\n)\n'


def basic_blocks(source: str) -> tuple[str, dict[str, str]]:
    """Protect literal code before removing editorial comments or reading callouts."""
    lines = source.splitlines()
    blocks = []
    index = 0
    while index < len(lines):
        opening = re.match(r'^\s*(`{3,}|~{3,})([^\n]*)$', lines[index])
        if opening:
            fence = opening.group(1)
            code = []
            index += 1
            while index < len(lines) and not re.fullmatch(
                r'\s*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*', lines[index]
            ):
                code.append(lines[index])
                index += 1
            if index == len(lines):
                raise RENDERER.HTTPException(422, 'Закройте блок кода такой же строкой обратных кавычек')
            blocks.append(encoded_component('obsidian_code', ['\n'.join(code)]))
        else:
            blocks.append(lines[index])
        index += 1
    source = '\n'.join(blocks)
    literals = {}

    def protect_inline(match):
        token = 'LITERAL' + uuid4().hex
        literals[token] = '<code>' + escape(match.group(2)) + '</code>'
        return token

    source = re.sub(r'(`+)([^\n]*?)\1(?!`)', protect_inline, source)
    source = re.sub(r'%%[\s\S]*?%%|<!--[\s\S]*?-->', '', source)
    if '%%' in source:
        raise RENDERER.HTTPException(422, 'Закройте комментарий символами %%')
    source = re.sub(r'^\s*(?:-{3,}|\*{3,}|_{3,})\s*$', '\nobsidian_rule(\n)\n', source, flags=re.M)
    return source, literals


def image_links(markdown: str) -> str:
    """Prototype-only convention: a standalone HTTPS image URL keeps its position."""
    result = []
    fence = None
    for line in markdown.splitlines():
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            result.append(line)
            continue
        parsed = urlsplit(stripped)
        if (
            fence is None
            and parsed.scheme == "https" and parsed.netloc
            and not re.search(r'[\s()<>"]', stripped)
            and RENDERER.safe_href(stripped)
            and re.search(r"\.(?:png|jpe?g|webp|gif|avif)$", parsed.path, re.I)
        ):
            result.append(f"![Иллюстрация к материалу]({stripped})")
        else:
            result.append(line)
    return "\n".join(result)


class Contents(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str, str]] = []
        self.heading = None
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"h2", "h3"}:
            self.heading = tag
            self.parts = []

    def handle_data(self, data):
        if self.heading:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading:
            self.items.append((tag, f"section-{len(self.items) + 1}", "".join(self.parts)))
            self.heading = None


class InlineLiterals(HTMLParser):
    """Restore escaped code only in text, never inside link/image attributes."""
    def __init__(self, literals):
        super().__init__(convert_charrefs=True)
        self.literals = literals
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        self.parts.append('</' + tag + '>')

    def handle_data(self, data):
        text = escape(data)
        for token, literal in self.literals.items():
            text = text.replace(token, literal)
        self.parts.append(text)


def obsidian_spoilers(source: str) -> str:
    """NOTE is an accent panel; NOTE-minus is a closed spoiler."""
    lines = source.splitlines()
    result = []
    index = 0
    fence = None
    while index < len(lines):
        line = lines[index]
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        action = None if fence else re.match(r'^\s*>\s*\[!link\](?:\s+(.+?))?\s*$', line, re.I)
        title = None if fence else re.match(r'^\s*>\s*\[!note\](-?)(?:\s+(.+?))?\s*$', line, re.I)
        if not fence and re.match(r'^\s*>\s*\[!', line) and not (title or action):
            raise RENDERER.HTTPException(422, 'Поддержаны только NOTE, NOTE- и LINK; проверьте тип блока')
        if not (title or action):
            result.append(line)
            index += 1
            continue
        body = []
        index += 1
        while index < len(lines):
            quoted = re.match(r'^\s*>\s?(.*)$', lines[index])
            if not quoted:
                break
            body.append(quoted.group(1))
            index += 1
        if action:
            mode = (action.group(1) or '').strip().lower()
            modes = {'': 'stack', 'в строку': 'row', 'по центру': 'center'}
            if mode not in modes:
                raise RENDERER.HTTPException(422, 'LINK: оставьте заголовок пустым, В строку или По центру')
            values = [modes[mode]]
            for item in body:
                if not item.strip():
                    continue
                link = re.fullmatch(r'\[([^\[\]\n]+)\]\((https?://[^\s)]+|/(?!/)[^\s)]+)\)', item.strip())
                if not link or not RENDERER.safe_href(link.group(2)):
                    raise RENDERER.HTTPException(422, 'LINK: каждая строка — [Подпись](https://адрес) с безопасной ссылкой')
                parsed = urlsplit(link.group(2))
                if parsed.scheme and not parsed.netloc:
                    raise RENDERER.HTTPException(422, 'LINK: у ссылки должен быть адрес сайта')
                values.extend(link.groups())
            if not 3 <= len(values) <= 9:
                raise RENDERER.HTTPException(422, 'LINK принимает от одной до четырёх кнопок')
            result.append(encoded_component('obsidian_actions', values))
            continue
        paragraphs = [' '.join(block.splitlines()) for block in
            re.split(r'\n\s*\n', '\n'.join(body)) if block.strip()]
        # Keep arbitrary prose out of the component DSL (a paragraph may be ')').
        name = 'obsidian_spoiler' if title.group(1) == '-' else 'obsidian_note'
        result.append(encoded_component(name, [title.group(2) or 'Подробнее', *paragraphs]))
    return '\n'.join(result)


def spoiler_component(name: str, arguments: list[str]) -> str:
    if name == 'obsidian_rule' and not arguments:
        return '<hr>'
    if name in {'obsidian_spoiler', 'obsidian_note', 'obsidian_code', 'obsidian_actions'}:
        try:
            if len(arguments) != 1:
                raise ValueError('Expected one encoded callout')
            arguments = json.loads(base64.b64decode(arguments[0], validate=True))
            if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
                raise ValueError('Expected text arguments')
        except (ValueError, TypeError) as exc:
            raise RENDERER.HTTPException(422, 'Некорректный блок NOTE') from exc
        if name == 'obsidian_actions':
            if len(arguments) not in {3, 5, 7, 9} or arguments[0] not in {'stack', 'row', 'center'}:
                raise RENDERER.HTTPException(422, 'Некорректный блок кнопок')
            links = []
            for label, href in zip(arguments[1::2], arguments[2::2]):
                parsed = urlsplit(href)
                if not label.strip() or not RENDERER.safe_href(href) or not (
                    (parsed.scheme in {'http', 'https'} and parsed.netloc) or
                    (not parsed.scheme and href.startswith('/') and not href.startswith('//'))
                ):
                    raise RENDERER.HTTPException(422, 'Некорректная ссылка кнопки')
                links.append('<a href="' + escape(href, quote=True) + '">' + escape(label) + '</a>')
            return '<div class="article-actions article-actions-' + arguments[0] + '">' + ''.join(links) + '</div>'
        if name == 'obsidian_code':
            if len(arguments) != 1:
                raise RENDERER.HTTPException(422, 'Блок кода принимает один текст')
            return ('<div class="article-copy-block"><pre><code>' + escape(arguments[0]) + '</code></pre>'
                '<button class="article-copy-button" '
                'aria-label="Скопировать текст блока" type="button">Скопировать</button>'
                '</div>')
        if name == 'obsidian_note':
            if not 2 <= len(arguments) <= 40:
                raise RENDERER.HTTPException(422, 'Добавьте текст внутрь NOTE')
            # NOTE's title is editorial metadata, not an extra heading on the site.
            return '<div class="article-note-accent">' + ''.join(
                '<p>' + RENDERER.inline_markdown(paragraph) + '</p>' for paragraph in arguments[1:]
            ) + '</div>'
        name = 'spoiler'
    # Same closed markup/limits as render_spoiler in masterclass_article_components@f151218.
    if name != 'spoiler' or not 2 <= len(arguments) <= 40:
        raise RENDERER.HTTPException(422, 'Спойлер принимает заголовок и от 1 до 39 абзацев текста')
    title, *paragraphs = arguments
    return ('<details class="article-spoiler">'
        f'<summary>{RENDERER.inline_markdown(title)}</summary>'
        '<div class="article-spoiler-body">' + ''.join(
        f'<p>{RENDERER.inline_markdown(paragraph)}</p>' for paragraph in paragraphs)
        + '</div></details>')


class ResponsiveTables(HTMLParser):
    """Label only ordinary, already sanitized tables; never special DQS tables."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.active = False
        self.headers = []
        self.header = None
        self.column = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.active = dict(attrs).get('class') == 'article-data-table'
            self.headers = []
        if self.active and tag == 'th':
            self.header = []
        if self.active and tag == 'tr':
            self.column = 0
        if self.active and tag == 'td':
            label = self.headers[self.column] if self.column < len(self.headers) else ''
            self.parts.append('<td data-label="' + escape(label, quote=True) + '">')
            self.column += 1
        elif self.active and tag == 'th':
            self.parts.append('<th scope="col">')
        else:
            self.parts.append(self.get_starttag_text())

    def handle_data(self, data):
        if self.header is not None:
            self.header.append(data)
        self.parts.append(escape(data))

    def handle_endtag(self, tag):
        if self.active and tag == 'th':
            self.headers.append(''.join(self.header or []))
            self.header = None
        if tag == 'table':
            self.active = False
        self.parts.append('</' + tag + '>')


def render_source(source: str) -> tuple[str, str, str]:
    title_match = re.match(r"\A\ufeff?# ([^\n]+)", source)
    if not title_match:
        raise ValueError("Демо-файл должен начинаться с # Название")
    title = title_match.group(1).strip()
    prepared, literals = basic_blocks(image_links(source))
    body = RENDERER.markdown_to_article_html(obsidian_spoilers(prepared),
        component_renderer=spoiler_component)
    restored = InlineLiterals(literals)
    restored.feed(body)
    restored.close()
    body = ''.join(restored.parts)
    body = re.sub(r'<li>\[([ xX])\]\s*', lambda match:
        '<li class="article-task' + (' article-task-negative' if match.group(1).lower() != 'x' else '') +
        '"><span class="article-status-label">' +
        ('Да: ' if match.group(1).lower() == 'x' else 'Нет: ') + '</span>', body)
    tables = ResponsiveTables()
    tables.feed(body)
    tables.close()
    body = ''.join(tables.parts)
    contents = Contents()
    contents.feed(body)
    anchors = iter(contents.items)

    def add_anchor(match):
        _, anchor, _ = next(anchors)
        return f'<{match.group(1)} id="{anchor}">'

    body = re.sub(r"<(h2|h3)>", add_anchor, body)
    links = "".join(
        f'<a class="level-{tag}" href="#{anchor}">{escape(label)}</a>'
        for tag, anchor, label in contents.items
    )
    return title, body, links


def shell(title: str, content: str) -> bytes:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{escape(title)} — локальный стенд</title>
<link rel="stylesheet" href="/demo.css"></head><body>
<header class="top"><a href="/day-1">Оглавление: тест дня 1</a><span>Только локальный просмотр</span></header>
<main>{content}</main><footer>Не настоящий ЛК. Нет публикации, отправок или записи прогресса.</footer>
</body></html>""".encode("utf-8")


def material_page() -> bytes:
    title, body, contents = render_source(SOURCE.read_text(encoding="utf-8"))
    return shell(title, f"""<div class="demo-status">День 1 · дополнительный тестовый материал · не добавлен в настоящий курс</div>
<details class="contents"><summary>Содержание материала</summary><nav aria-label="Содержание">{contents}</nav></details>
<article class="article"><h1>{escape(title)}</h1>{body}</article>
<p class="files"><a href="/source.md">Исходный Markdown</a> · <a href="/map.md">Карта переноса</a> · <a href="/lab.md">Лаборатория Obsidian</a></p>""")


def day_page() -> bytes:
    title, _, _ = render_source(SOURCE.read_text(encoding="utf-8"))
    return shell("Тест первого дня", f"""<article class="article"><p class="demo-status">Локальная песочница, не опубликованная программа</p>
<h1>День 1: проверка оформления</h1><p>Здесь добавлен только тестовый материал. Настоящие уроки первого дня не изменены.</p>
<a class="material-card" href="/material"><span>Тестовый материал</span><strong>{escape(title)}</strong><span>Открыть →</span></a>
<p>Измените демо-MD в Obsidian и обновите страницу материала в браузере.</p></article>""")


def course_shell() -> bytes:
    """Use the actual course UI unchanged; only adapt local assets and demo state."""
    template = git_file('backend/app/static/masterclass-first-days-preview.html', SHELL_REF).decode('utf-8')
    template = template.replace('edabalans_first_days_v2', 'edabalans_md_shell_preview_v1')
    template = template.replace('https://app.edabalans.ru/apps/dqs-category-rules.js', '/apps/dqs-category-rules.js')
    template = template.replace('</head>', '<link rel="stylesheet" href="/lk-preview.css"><link rel="stylesheet" href="/article-assets/components.css"><script src="/lk-bootstrap.js"></script><script defer src="/md-copy.js"></script></head>')
    return template.encode('utf-8')


def demo_manifest() -> bytes:
    manifest = json.loads(git_file('content/masterclass/course/course.json', SHELL_REF))
    title, _, _ = render_source(SOURCE.read_text(encoding='utf-8'))
    for day in manifest['days']:
        for step in day.get('steps', []):
            step['locked'] = True
            step.pop('contentAsset', None)
    first = manifest['days'][0]
    first['steps'].insert(0, dict(id=DEMO_STEP, kind='article', title=title,
        summary='Локальная проверка Markdown в настоящей оболочке курса.',
        durationMinutes=3, required=True, contentKind='imported',
        contentAsset='local-formatting.json', contentPageTitle=title))
    first['intro'] = 'Локальный тест оформления. Только тестовый материал доступен; остальные материалы не публикуются и не изменены.'
    first['media'] = 'none'
    first['videoId'] = ''
    first['image'] = ''
    return json.dumps(manifest, ensure_ascii=False).encode('utf-8')


def demo_content() -> bytes:
    source = SOURCE.read_text(encoding='utf-8')
    title, body, _ = render_source(source)
    return json.dumps({'pages': [{'title': title, 'rich_html': body,
        'word_count': len(source.split())}]}, ensure_ascii=False).encode('utf-8')


GIT_ASSETS = {
    '/assets/content-gallery.js': 'backend/app/static/content-gallery.js',
    '/apps/dqs-category-rules.js': 'backend/app/static/apps/dqs-category-rules.js',
    '/course-assets/masterclass/article-components.js': 'content/masterclass/components/dqs-image-slider/slider.js',
}


def content_policy(body: bytes, mime: str) -> str:
    # Only trusted canonical inline scripts execute; authored MD never enters script text.
    hashes = []
    if mime.startswith('text/html'):
        for script in re.findall(r'<script(?:\s[^>]*)?>([\s\S]*?)</script>', body.decode('utf-8')):
            hashes.append("'sha256-" + base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode() + "'")
    return ("default-src 'self'; connect-src 'self'; img-src 'self' https:; "
        "style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self' "
        + ' '.join(hashes) + "; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path in {"/", "/day-1", "/material", "/lk"}:
                body, mime = course_shell(), "text/html; charset=utf-8"
            elif path == '/content/masterclass/course/course.json':
                body, mime = demo_manifest(), 'application/json; charset=utf-8'
            elif path == '/content/masterclass/source-current/local-formatting.json':
                body, mime = demo_content(), 'application/json; charset=utf-8'
            elif path in GIT_ASSETS:
                body, mime = git_file(GIT_ASSETS[path], SHELL_REF), 'application/javascript; charset=utf-8'
            elif path == '/course-assets/masterclass/article-components.css':
                body = b'\n'.join(git_file('content/masterclass/components/' + asset, SHELL_REF)
                    for asset in ('dqs-image-slider/slider.css', 'dqs-score-tables/score-tables.css', 'article-spoiler/spoiler.css'))
                mime = 'text/css; charset=utf-8'
            elif path == '/article-assets/components.css':
                body = b'\n'.join((COMPONENTS / asset).read_bytes() for asset in
                    ('formatting.css', 'note.css', 'copy.css', 'actions.css', 'status-list.css', 'table.css'))
                mime = 'text/css; charset=utf-8'
            elif path in {"/source.md", "/map.md", "/lab.md", "/demo.css", '/lk-preview.css', '/lk-bootstrap.js', '/md-copy.js'}:
                files = {
                    "/source.md": SOURCE,
                    "/map.md": HERE / "Карта переноса.md",
                    "/lab.md": HERE / "Возможности Obsidian — лаборатория.md",
                    "/demo.css": HERE / "demo.css",
                    '/lk-preview.css': HERE / 'lk-preview.css',
                    '/lk-bootstrap.js': HERE / 'lk-bootstrap.js',
                    '/md-copy.js': HERE / 'md-copy.js',
                }
                body = files[path].read_bytes()
                mime = ('text/css; charset=utf-8' if path.endswith('.css') else
                    'application/javascript; charset=utf-8' if path.endswith('.js') else 'text/plain; charset=utf-8')
            elif path in {"/fonts/inter-latin.woff2", "/fonts/inter-cyrillic.woff2"}:
                body = git_file("backend/app/static/blog" + path)
                mime = "font/woff2"
            else:
                self.send_error(404)
                return
        except Exception as exc:
            message = getattr(exc, "detail", str(exc))
            body = shell("Ошибка просмотра", f'<p role="alert">{escape(str(message))}</p>')
            mime = "text/html; charset=utf-8"
            self.send_response(422)
        else:
            self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header('Content-Security-Policy', content_policy(body, mime))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8794)
    args = parser.parse_args()
    print(f"Local-only preview: http://127.0.0.1:{args.port}/day-1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
