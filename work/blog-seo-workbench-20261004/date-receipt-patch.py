"""Produce a focused apply_patch input from a reviewed public date receipt."""
import copy
import argparse
from datetime import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source_text = (ROOT / 'content/blog/manifest.json').read_text(encoding='utf-8')
manifest = json.loads(source_text)
parser = argparse.ArgumentParser()
parser.add_argument('--receipt', type=Path, default=Path(__file__).parent / 'original-dates-primary-probe.json')
receipt = json.loads(parser.parse_args().receipt.read_text(encoding='utf-8'))
articles = {article['source_id']: article for article in manifest['articles']}
patch = ['*** Begin Patch', '*** Update File: ' + str(ROOT / 'content/blog/manifest.json')]
for row in receipt['rows']:
    if row['status'] != 'exact':
        continue
    article = articles[row['source_id']]
    before = article['source_provenance']
    assert row['slug'] == article['slug'] and row['source_url'] in before['urls']
    assert datetime.fromisoformat(row['original_published_at']).tzinfo is not None
    if before.get('original_published_at'):
        assert before['original_published_at'] == row['original_published_at']
        continue
    after = copy.deepcopy(before)
    after['original_published_at'] = row['original_published_at']
    after['original_date_evidence'] = {'source': row['source_url'], 'page_sha256': row['html_sha256'], 'field': row['field'], 'checked_at': receipt['checked_at']}
    def block(value):
        return '      "source_provenance": ' + json.dumps(value, ensure_ascii=False, indent=2).replace('\n', '\n      ')
    old_block = block(before)
    offset = source_text.index(old_block) + len(old_block)
    suffix = ',' if source_text[offset:offset + 1] == ',' else ''
    patch += ['@@'] + ['-' + line for line in (old_block + suffix).splitlines()] + ['+' + line for line in (block(after) + suffix).splitlines()]
patch.append('*** End Patch')
print('\n'.join(patch))
