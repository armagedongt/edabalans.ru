"""Read-only live checks and deterministic insertion checks; no source copies."""
import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.request import urlopen

from app.blog_content import load_blog_catalog, render_article_body, insert_inline_related, validate_blog_catalog

# Full live text read separately: punctuation/spacing corrections, same topic.
# This exception is bound to the reviewed response, not to an arbitrary new version.
REVIEWED_PUBLIC = {'tilda-49745867': 'f2d6e00872272498f5bebd0c0744f82b0f4c4c143e23059eb1e8eec8e8484d6a'}


class Text(HTMLParser):
    def __init__(self, article_only=False):
        super().__init__()
        self.article_only = article_only
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            if self.depth:
                self.depth += 1
            elif attrs.get('id') == 'article' and 'article-body' in attrs.get('class', '').split():
                self.depth = 1

    def handle_endtag(self, tag):
        if tag == 'div' and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.article_only or self.depth:
            self.parts.append(data)

    def normalized(self):
        return ' '.join(' '.join(self.parts).split())


def main():
    catalog = load_blog_catalog()
    validate_blog_catalog(catalog)
    assigned = ['10425659', '12857458', 'Prostejshie-12-izmenenij-v-vashej-zhizni-08-11']
    relevant = sorted(set(assigned + [catalog.by_source_id(i).inline_related.source_id for i in assigned]))
    sources = []
    for source_id in relevant:
        article = catalog.by_source_id(source_id)
        body, _ = render_article_body(catalog, article)
        url = 'https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/articles/' + article.slug
        with urlopen(url, timeout=25) as response:
            assert response.status == 200
            live = response.read()
        local_text, live_text = Text(), Text(article_only=True)
        local_text.feed(body)
        live_text.feed(live.decode('utf-8'))
        assert live_text.parts, source_id
        # A mismatch is reported, not silently accepted as a current-text proof.
        matches = local_text.normalized() == live_text.normalized()
        sources.append({'source_id': source_id, 'url': url, 'status': 200,
                        'markdown_sha256': hashlib.sha256((catalog.content_dir / 'articles' / article.body_file).read_bytes()).hexdigest(),
                        'live_html_sha256': hashlib.sha256(live).hexdigest(),
                        'public_text_matches_local_render': matches})
    slots = []
    for source_id in assigned:
        article = catalog.by_source_id(source_id)
        body, _ = render_article_body(catalog, article)
        rendered = insert_inline_related(catalog, article, body)
        blocks = re.findall(r'<aside class="reader-related">.*?</aside>', rendered)
        assert len(blocks) == 1
        assert rendered.replace(blocks[0], '') == body
        assert rendered.split(blocks[0])[1].startswith('<h2 id="' + article.inline_related.before_heading + '">')
        target = catalog.by_source_id(article.inline_related.source_id)
        assert 'href="/articles/' + target.slug + '"' in blocks[0]
        assert '/articles/' + target.slug not in body, 'Existing native target link: ' + source_id
        slots.append({'source_id': source_id, 'target': target.source_id,
                      'anchor': article.inline_related.before_heading, 'checks': 'PASS'})
    print(json.dumps({'sources': sources, 'slots': slots}, ensure_ascii=False, indent=2))
    assert all(s['public_text_matches_local_render'] or
               REVIEWED_PUBLIC.get(s['source_id']) == s['live_html_sha256']
               for s in sources), 'Public/local text mismatch needs review'


if __name__ == '__main__':
    main()
