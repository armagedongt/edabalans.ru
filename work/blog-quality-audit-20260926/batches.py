"""Read-only, resumable public-version evidence; no editorial pass is inferred."""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
PRIVATE = Path('D:/CodexPrivate/blog-quality-audit-20260926')
sys.path.insert(0, str(ROOT / 'backend'))
from app.blog_content import add_heading_anchors, markdown_to_article_html, render_blog_component

class Body(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.found = False
        self.text = []
        self.images = []
        self.links = []
        self.headings = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.depth:
            if tag == 'div' and attrs.get('id') == 'article':
                self.depth = 1
                self.found = True
            return
        if tag == 'div': self.depth += 1
        if tag == 'img': self.images.append(attrs.get('src'))
        if tag == 'a': self.links.append(attrs.get('href'))
        if tag in ('h2', 'h3'): self.headings.append(tag)
    def handle_endtag(self, tag):
        if self.depth and tag == 'div': self.depth -= 1
    def handle_data(self, value):
        if self.depth: self.text.append(value)
    def value(self):
        return re.sub(r'\s+', ' ', ''.join(self.text)).strip()

def sha(data): return hashlib.sha256(data).hexdigest()
def save(path, obj):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, required=True)
    args = parser.parse_args()
    articles = json.loads((ROOT / 'content/blog/manifest.json').read_text(encoding='utf-8'))['articles']
    if not 1 <= args.batch <= (len(articles) + 4) // 5:
        parser.error('batch outside manifest range')
    PRIVATE.mkdir(parents=True, exist_ok=True)
    target = OUT / 'batches'
    target.mkdir(exist_ok=True)
    for article in articles[(args.batch-1)*5:args.batch*5]:
        identity = str(article['source_id'])
        path = target / (identity + '.snapshot.json')
        raw = (ROOT / 'content/blog/articles' / article['body_file']).read_bytes()
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            if (previous.get('git_sha256') == sha(raw)
                    and previous.get('http_status') == 200
                    and all(previous.get(key) is True for key in (
                        'rendered_text_matches', 'body_image_urls_match',
                        'body_links_match', 'heading_levels_match'))):
                print(identity, 'cached')
                continue
        evidence = {'source_id': identity, 'title': article['title'], 'batch': args.batch,
                    'git_sha256': sha(raw), 'checked_at': datetime.now(timezone.utc).isoformat(),
                    'editorial_status': 'pending', 'runtime_raw_markdown': 'not_read'}
        url = 'https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/articles/' + article['slug']
        evidence['public_url'] = url
        try:
            with urlopen(Request(url, headers={'User-Agent':'EdabalansQualityAudit/1.0'}), timeout=15) as response:
                public = response.read()
                evidence['http_status'] = response.status
            (PRIVATE / (identity + '.html')).write_bytes(public)
            live = Body(); live.feed(public.decode('utf-8'))
            local = Body()
            rendered, _ = add_heading_anchors(markdown_to_article_html(raw.decode('utf-8'), component_renderer=render_blog_component))
            local.feed('<div id="article">' + rendered + '</div>')
            evidence.update(public_html_sha256=sha(public), body_found=live.found,
                            rendered_text_matches=live.found and live.value() == local.value(),
                            body_image_urls_match=live.images == local.images,
                            body_links_match=live.links == local.links,
                            heading_levels_match=live.headings == local.headings,
                            public_body_text_sha256=sha(live.value().encode()),
                            public_body_images=live.images, public_body_links=live.links,
                            snapshot_path=str(PRIVATE / (identity + '.html')))
        except Exception as error:
            evidence['error'] = str(error)
        save(path, evidence)
        print(identity, 'saved', evidence.get('rendered_text_matches', 'network_error'))

if __name__ == '__main__': main()
