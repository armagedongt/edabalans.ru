"""Public intensive: approved Markdown and the existing article renderer."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re

from app.site_menu import render_site_menu
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
        # New group titles do not renumber the existing public section links.
        if match[1] == 'h2' and match[2] in {label for _, label, _ in GROUPS[:-1]}:
            return match[0]
        number += 1
        return f'<{match[1]} id="section-{number}">{match[2]}</{match[1]}>'

    return title, re.sub(r'<(h2|h3)>(.*?)</\1>', anchor, body, flags=re.S), ''


GROUPS = [
    ('block-1', 'Здоровое питание', 'intensive:block-1:start'),
    ('block-2', 'Пищевые привычки', 'intensive:block-2:start'),
    ('block-3', 'Порядок похудения', 'intensive:block-3:start'),
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
        match = re.match(r'^(#{2,3}) (.+)', line)
        if match:
            text = match.group(2).strip()
            group_title = match.group(1) == '##' and text in {label for _, label, _ in GROUPS}
            if group_title and text != GROUPS[-1][1]:
                continue
            heading_number += 1
            if current and not group_title:
                contents[current].append((f'section-{heading_number}', text))
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
        f'<section><a class="toc-group" href="#{key}">{escape(label)}</a>' +
        ('<ul>' + ''.join(f'<li><a href="#{anchor}">{escape(text)}</a></li>' for anchor, text in contents[key]) + '</ul>' if contents[key] else '') +
        '</section>' for key, label, _ in GROUPS
    )
    return title, ''.join(decorated.parts), toc


@lru_cache(maxsize=4)
def reading_outline(source: str) -> tuple[str, dict[str, str]]:
    """Resolve telemetry labels from the same article that the server renders."""
    _, body, _ = render_article(source)
    headings = {}
    group_ids = {label: key for key, label, _ in GROUPS}
    for level, attrs, text in re.findall(r'<(h2|h3)([^>]*)>(.*?)</\1>', body, re.S):
        label = unescape(re.sub(r'<[^>]+>', '', text)).strip()
        anchor = re.search(r' id="([^"]+)"', attrs)
        key = anchor[1] if anchor else group_ids.get(label)
        if key:
            headings[key] = label
    return hashlib.sha256(source.encode('utf-8')).hexdigest()[:12], headings


def hero_title(title: str) -> str:
    if title == 'Как сделать похудение проще!?':
        return '<span>Как сделать</span><span class="intensive-title__accent">похудение проще!?</span>'
    return escape(title)


def page(*, identified: bool = False):
    source = SOURCE.read_text(encoding='utf-8')
    revision = hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]
    title, body, toc = render_article(source)
    tabs = ''.join(
        f'<a href="#{key}" data-section="{key}"><span>{escape(label).replace(" ", "<br class=\"reading-label-break\"> ", 1)}</span></a>'
        for key, label, _ in GROUPS
    )
    menu = render_site_menu('<a href="https://похудение-это-есть.рф/#masterclass-title">Мастер-класс</a>', toc, article=True)
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>{escape(title)} — Бесплатный интенсив</title>
<link rel="icon" type="image/png" href="/favicon.png?v=20260910a">
<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=20260910a">
<link rel="stylesheet" href="/intensive/onepage-components.css?v=20261018-typography">
<link rel="preload" href="/assets/fonts/manrope-cyrillic-v1.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/fonts/manrope-latin-v1.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/site-typography.css?v=20261018-typography">
<link rel="stylesheet" href="/assets/article-typography.css?v=20261018-typography">
<link rel="stylesheet" href="/intensive/onepage.css?v=20261018-typography">
<link rel="stylesheet" href="/public-site-assets/site-menu.css?v=20261018-menu-icons"><script defer src="/public-site-assets/site-menu.js?v=20261018"></script><script defer src="/intensive/onepage.js?v=20261018"></script>
<script defer src="/intensive/onepage-tracking.js?v=20261018-menu"></script></head><body>
<header class="reading-header"><nav aria-label="Разделы интенсива">{tabs}</nav>
<div class="reading-track" role="progressbar" aria-label="Прогресс чтения" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="reading-fill"></div></div></header>
<main id="article" data-intensive-onepage data-intensive-revision="{revision}" data-intensive-identified="{str(identified).lower()}"><h1 class="intensive-title">{hero_title(title)}</h1>{body}</main>
{menu}
<div data-edabalans-site-footer></div><script defer src="/site-footer.js"></script>
<script src="/cookie-notice.js" defer></script></body></html>'''.encode('utf-8')

