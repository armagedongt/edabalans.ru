"""Public intensive: approved Markdown and the existing article renderer."""
from __future__ import annotations

import hashlib
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re

from app.article_markup import markdown_to_article_html, safe_href, sanitize_article_html

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'content/masterclass/editorial/weight-loss-roadmap.md'


def render_source(source: str):
    title = re.match(r'\A\ufeff?# ([^\n]+)', source).group(1).strip()
    actions = []

    def replace_actions(match):
        links = []
        for line in match.group(1).splitlines():
            if not line.strip():
                continue
            link = re.fullmatch(r'>\s*\[([^\]]+)\]\((https://[^\s)]+)?\)', line)
            if not link or (link[2] and not safe_href(link[2])):
                raise ValueError('Invalid intensive channel link')
            if not link[2] and (len(links) != 1 or link[1] not in ('MAX', 'Открыть MAX')):
                raise ValueError('Only the MAX button may have no destination')
            destination = f'href="{escape(link[2], quote=True)}"' if link[2] else 'aria-disabled="true"'
            links.append(f'<a {destination}>{escape(link[1])}</a>')
        if len(links) != 2:
            raise ValueError('Expected the two approved channel buttons')
        token = f'INTENSIVEACTIONPAIR{len(actions)}TOKEN'
        actions.append((token, '<div class="article-actions article-actions-row">'+''.join(links)+'</div>'))
        return token + '\n'

    source = re.sub(r'^> \[!LINK\] В строку\n((?:>.*\n?)+)', replace_actions, source, flags=re.M)
    source = re.sub(r'^(> \[!NOTE\])[^\n]*', r'\1', source, flags=re.M)
    body = sanitize_article_html(markdown_to_article_html(source), course_semantics=True)
    for token, html in actions:
        body = body.replace(f'<p>{token}</p>', html)
    number = 0

    def anchor(match):
        nonlocal number
        number += 1
        return f'<{match[1]} id="section-{number}">'

    return title, re.sub(r'<(h2|h3)>', anchor, body), ''


GROUPS = [
    ('block-1', 'Здоровое питание', 'intensive:block-1:start'),
    ('block-2', 'Пищевые привычки', 'intensive:block-2:start'),
    ('block-3', 'Порядок похудения', 'intensive:block-3:lead'),
    ('actions', 'Конкретные действия', 'intensive:actions:start'),
]
MARKERS = {
    **{marker: f'<span class="section-anchor" id="{key}" data-intensive-section="{key}"></span>' for key, _, marker in GROUPS},
    'intensive:comparison-unbalanced:start': '<div class="comparison comparison-unbalanced">',
    'intensive:comparison-unbalanced:end': '</div>',
    'intensive:comparison-balanced:start': '<div class="comparison comparison-balanced">',
    'intensive:comparison-balanced:end': '</div>',
    'intensive:reading:end': '<span id="reading-end" data-intensive-end></span>',
}


class ArticleLinks(HTMLParser):
    """Decorate only the existing LINK pair; destinations stay owned by MD."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.action_depth = 0
        self.action_link_count = 0
        self.in_action_link = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'div':
            if self.action_depth:
                self.action_depth += 1
            elif 'article-actions' in values.get('class', '').split():
                self.action_depth = 1
        if tag == 'a' and self.action_depth:
            if self.action_link_count >= 2:
                raise ValueError('Expected exactly two channel links')
            brand = ('telegram', 'max')[self.action_link_count]
            self.action_link_count += 1
            self.in_action_link = True
            attrs.append(('class', 'social-' + brand))
            if values.get('href'):
                attrs.append(('data-intensive-channel', brand))
            self.parts.append('<a' + ''.join(f' {k}="{escape(v or "", quote=True)}"' for k, v in attrs) + '>')
            icon = 'assets/roadmap/telegram-plane.svg' if brand == 'telegram' else 'max-full-colored-official.png'
            self.parts.append(f'<img src="/intensive/{icon}" class="social-logo" alt="" aria-hidden="true">')
            return
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        self.parts.append(f'</{tag}>')
        if tag == 'a':
            self.in_action_link = False
        if tag == 'div' and self.action_depth:
            self.action_depth -= 1

    def handle_data(self, data):
        self.parts.append('<span class="social-label">' + data + '</span>' if self.in_action_link else data)

    def handle_entityref(self, name):
        self.parts.append('&' + name + ';')

    def handle_charref(self, name):
        self.parts.append('&#' + name + ';')


def render_article(source: str):
    # Parse structural comments before the shared renderer removes editorial comments.
    contents = {key: [] for key, _, _ in GROUPS}
    current = None
    heading_number = 0
    visible = re.sub(r'<!--(?!(?:\s*intensive:))[\s\S]*?-->', '', source)
    for line in visible.splitlines():
        for key, _, marker in GROUPS:
            if line.strip() == f'<!-- {marker} -->':
                current = key
        match = re.match(r'^#{2,3} (.+)', line)
        if match:
            heading_number += 1
            if current:
                contents[current].append((f'section-{heading_number}', match.group(1).strip()))
    placeholders = {}
    for number, (marker, html) in enumerate(MARKERS.items()):
        comment = f'<!-- {marker} -->'
        if source.count(comment) != 1:
            raise ValueError(f'Expected exactly one structural marker: {marker}')
        token = f'INTENSIVEBOUNDARY{number}PLACEHOLDER'
        if token in source:
            raise ValueError('Reserved preview marker in source')
        source = source.replace(comment, '\n\n' + token + '\n\n')
        placeholders[token] = html
    title, body, _ = render_source(source)
    for token, html in placeholders.items():
        paragraph = f'<p>{token}</p>'
        if body.count(paragraph) != 1:
            raise ValueError('Structural marker was not preserved by renderer')
        body = body.replace(paragraph, html)
    decorated = ArticleLinks()
    decorated.feed(body)
    decorated.close()
    if decorated.action_link_count != 2:
        raise ValueError('Expected exactly two channel links')
    toc = ''.join(
        f'<section><a class="toc-group" href="#{key}">{escape(label)}</a><ul>' +
        ''.join(f'<li><a href="#{anchor}">{escape(text)}</a></li>' for anchor, text in contents[key]) +
        '</ul></section>' for key, label, _ in GROUPS
    )
    return title, ''.join(decorated.parts), toc


def hero_title(title: str) -> str:
    if title == 'Как сделать похудение проще!?':
        return '<span>Как сделать</span><span class="intensive-title__accent">похудение проще!?</span>'
    return escape(title)


def page(*, identified: bool = False):
    source = SOURCE.read_text(encoding='utf-8')
    revision = hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]
    title, body, toc = render_article(source)
    tabs = ''.join(f'<a href="#{key}" data-section="{key}">{escape(label)}</a>' for key, label, _ in GROUPS)
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>{escape(title)} — Бесплатный интенсив</title>
<link rel="icon" type="image/png" href="/favicon.png?v=20260910a">
<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=20260910a">
<link rel="stylesheet" href="/intensive/onepage-components.css?v=20261005">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@800&display=swap" rel="stylesheet" media="print" onload="this.media='all'">
<link rel="stylesheet" href="/intensive/onepage.css?v=20261005-menu-refinement"><script defer src="/intensive/onepage.js?v=20261005"></script>
<script defer src="/intensive/onepage-tracking.js?v=20261005"></script></head><body>
<header class="reading-header"><nav aria-label="Разделы интенсива">{tabs}</nav>
<div class="reading-track" role="progressbar" aria-label="Прогресс чтения" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="reading-fill"></div></div></header>
<main id="article" data-intensive-onepage data-intensive-revision="{revision}" data-intensive-identified="{str(identified).lower()}"><h1 class="intensive-title">{hero_title(title)}</h1>{body}</main>
<button class="toc-trigger" type="button" aria-label="Открыть содержание" aria-haspopup="dialog" aria-controls="contents"><span class="toc-trigger__icon" aria-hidden="true"><span></span><span></span><span></span></span></button>
<dialog id="contents" aria-labelledby="contents-title"><div class="toc-top"><h2 id="contents-title">В этом материале</h2>
<button type="button" class="toc-close" aria-label="Закрыть содержание">×</button></div><nav aria-label="Все темы интенсива">{toc}</nav></dialog>
<div data-edabalans-site-footer></div><script defer src="/site-footer.js"></script>
<script src="/cookie-notice.js" defer></script></body></html>'''.encode('utf-8')

