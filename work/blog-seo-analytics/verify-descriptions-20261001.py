"""Read-only, sequential verification of each production article description."""
import argparse
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import subprocess
from urllib.request import urlopen


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.description = None
        self.og = None
        self.canonical = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name') == 'description':
            self.description = attrs.get('content')
        if tag == 'meta' and attrs.get('property') == 'og:description':
            self.og = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.run(
        ['ssh', 'edabalans-prod', 'cd /opt/edabalans && git rev-parse HEAD'],
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    remote = '''import json
from app.blog_content import load_blog_catalog, BLOG_PUBLIC_ORIGIN, blog_description, split_blog_metadata
from app.blog_draft_service import public_payload
from app.database import SessionLocal
catalog = load_blog_catalog()
with SessionLocal() as db:
    for article in catalog.published:
        payload = public_payload(db, article.slug)
        md = payload['markdown'] if payload else (catalog.content_dir / 'articles' / article.body_file).read_text(encoding='utf-8')
        explicit, _ = split_blog_metadata(md)
        print(json.dumps({'source_id': article.source_id, 'title': article.title, 'url': BLOG_PUBLIC_ORIGIN + '/articles/' + article.slug, 'description': blog_description(md), 'mode': 'explicit' if explicit is not None else 'opening_sentences'}, ensure_ascii=True))
'''
    result = subprocess.run(
        ['ssh', 'edabalans-prod', 'cd /opt/edabalans && docker compose exec -T backend python -'],
        input=remote, text=True, capture_output=True, check=True,
    )
    articles = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    previous = json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {}
    completed = {
        row['source_id']: row for row in previous.get('articles', [])
        if previous.get('revision') == revision and row.get('pass')
    }
    ledger = {'checked_at': datetime.now(timezone.utc).isoformat(), 'revision': revision, 'scope': 'description_only', 'articles': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for article in articles:
        saved = completed.get(article['source_id'])
        if saved and saved['description'] == article['description'] and saved['url'] == article['url']:
            ledger['articles'].append(saved)
            print(article['source_id'], 'REUSE VERIFIED', flush=True)
            continue
        try:
            with urlopen(article['url'], timeout=40) as response:
                html = response.read().decode('utf-8')
                metadata = Metadata()
                metadata.feed(html)
                article['http_status'] = response.status
                article['pass'] = (
                    metadata.description == article['description']
                    and metadata.og == article['description']
                    and metadata.canonical == article['url']
                    and bool(article['description'])
                )
                article['observed_description'] = metadata.description
                article['observed_og_description'] = metadata.og
        except Exception as exc:
            article['pass'] = False
            article['error'] = str(exc)
        ledger['articles'].append(article)
        args.output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(article['source_id'], 'PASS' if article['pass'] else 'FAIL', flush=True)
    args.output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not articles or not all(article['pass'] for article in ledger['articles']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
