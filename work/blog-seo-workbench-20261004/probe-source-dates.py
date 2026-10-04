"""Read primary publication timestamps; save only public provenance, not page bodies."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]

class StructuredData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.buffer = []
        self.items = []
        self.canonical = None
        self.header_dates = []
        self.in_header = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('property') == 'og:url':
            self.canonical = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'header':
            self.in_header = True
        if tag == 'time' and self.in_header and attrs.get('datetime'):
            self.header_dates.append(attrs['datetime'])
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.active = True
            self.buffer = []

    def handle_data(self, data):
        if self.active:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == 'header':
            self.in_header = False
        if tag == 'script' and self.active:
            self.active = False
            try:
                value = json.loads(''.join(self.buffer))
                self.items.extend(value if isinstance(value, list) else [value])
            except ValueError:
                pass

def probe(article):
    source_id = article['source_id']
    url = next(url for url in article['source_provenance']['urls'] if url.startswith('https://pikabu.ru/story/') and url.endswith('_' + source_id))
    result = {'source_id': source_id, 'slug': article['slug'], 'source_url': url, 'status': 'unresolved'}
    try:
        with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'}), timeout=25) as response:
            raw = response.read()
            result['resolved_url'] = response.url
            charset = response.headers.get_content_charset() or 'utf-8'
        parser = StructuredData()
        parser.feed(raw.decode(charset))
        candidates = [item for item in parser.items if isinstance(item, dict) and item.get('datePublished')]
        result['candidates'] = [{key: item.get(key) for key in ('@type', 'url', '@id', 'mainEntityOfPage', 'datePublished', 'author')} for item in candidates]
        matching = [item for item in candidates if item.get('url') == url]
        if len(matching) != 1:
            result['reason'] = 'not exactly one primary structured publication with matching URL'
            return result
        selected = matching[0]
        if result['resolved_url'] != url or selected.get('@type') != 'Article' or selected.get('author', {}).get('url') != 'https://pikabu.ru/@armagedongt':
            result['reason'] = 'primary URL, Article type or author provenance mismatch'
            return result
        date = datetime.fromisoformat(selected['datePublished'])
        if date.tzinfo is None:
            result['reason'] = 'publication timestamp has no timezone'
            return result
        result.update(status='exact', original_published_at=date.isoformat(), html_sha256=hashlib.sha256(raw).hexdigest(), field='datePublished')
    except Exception as error:
        result['reason'] = str(error)
    return result

def probe_telegraph(article):
    url = article['source_provenance']['urls'][0]
    result = {'source_id': article['source_id'], 'slug': article['slug'], 'source_url': url, 'status': 'unresolved'}
    try:
        with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25) as response:
            raw = response.read()
            result['resolved_url'] = response.url
            charset = response.headers.get_content_charset() or 'utf-8'
        parser = StructuredData()
        parser.feed(raw.decode(charset))
        result.update(canonical=parser.canonical, header_dates=parser.header_dates)
        if result['resolved_url'] != url or parser.canonical != url or len(parser.header_dates) != 1:
            result['reason'] = 'primary URL/canonical or unique header publication time missing'
            return result
        date = datetime.fromisoformat(parser.header_dates[0])
        if date.tzinfo is None:
            result['reason'] = 'header publication timestamp has no timezone'
            return result
        result.update(status='exact', original_published_at=date.isoformat(), html_sha256=hashlib.sha256(raw).hexdigest(), field='header.time[datetime]')
    except Exception as error:
        result['reason'] = str(error)
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--id')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--platform', choices=['pikabu', 'telegraph'], default='pikabu')
    args = parser.parse_args()
    articles = json.loads((ROOT / 'content/blog/manifest.json').read_text(encoding='utf-8'))['articles']
    selected = [a for a in articles if not a.get('source_provenance', {}).get('original_published_at') and (not args.id or a['source_id'] == args.id)]
    if args.platform == 'pikabu':
        selected = [a for a in selected if a['source_id'].isdigit() and any(url.startswith('https://pikabu.ru/story/') and url.endswith('_' + a['source_id']) for url in a.get('source_provenance', {}).get('urls', []))]
    else:
        selected = [a for a in selected if len(a.get('source_provenance', {}).get('urls', [])) == 1 and a['source_provenance']['urls'][0].startswith('https://telegra.ph/')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(probe if args.platform == 'pikabu' else probe_telegraph, selected))
    receipt = {'checked_at': datetime.now().astimezone().isoformat(), 'mode': 'read_only_primary_dates', 'exact': sum(row['status'] == 'exact' for row in rows), 'unresolved': sum(row['status'] != 'exact' for row in rows), 'rows': rows}
    if args.output:
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
