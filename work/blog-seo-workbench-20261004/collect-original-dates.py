"""Exact-source date extraction receipt, not a second article library."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
source_bytes = args.source.read_bytes()
raw = json.loads(source_bytes)
by_id = {str(item['external_id']): item for item in raw['items']}
manifest_path = ROOT / 'content/blog/manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
rows = []
changed = 0
for article in manifest['articles']:
    provenance = article.get('source_provenance', {})
    item = by_id.get(article['source_id'])
    row = {'source_id': article['source_id'], 'slug': article['slug'], 'status': 'unresolved'}
    if item and item.get('published_at') and item.get('canonical_url') in provenance.get('urls', []):
        date = datetime.fromisoformat(item['published_at'])
        if date.tzinfo is None:
            row['reason'] = 'source timestamp has no timezone'
        elif provenance.get('original_published_at') not in (None, item['published_at']):
            row['reason'] = 'existing provenance timestamp differs; not overwritten'
        else:
            row.update(status='exact', original_published_at=item['published_at'], source_url=item['canonical_url'])
            if not provenance.get('original_published_at'):
                changed += 1
                provenance['original_published_at'] = item['published_at']
                provenance['original_date_evidence'] = {'source': item['canonical_url'], 'snapshot_sha256': hashlib.sha256(source_bytes).hexdigest()}
    elif provenance.get('original_published_at'):
        row.update(status='existing_provenance', original_published_at=provenance['original_published_at'])
    else:
        row['reason'] = 'no exact primary source ID and URL timestamp in this snapshot; not inferred from other family members'
    rows.append(row)
receipt = {'date': '2026-10-04', 'source_snapshot_sha256': hashlib.sha256(source_bytes).hexdigest(), 'applied': args.apply,
           'changed': changed if args.apply else 0, 'would_change': changed,
           'exact': sum(row['status'] == 'exact' for row in rows), 'existing_provenance': sum(row['status'] == 'existing_provenance' for row in rows),
           'unresolved': sum(row['status'] == 'unresolved' for row in rows),
           'source_bodies_copied': False, 'library_written': False, 'rows': rows}
if args.apply:
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (Path(__file__).parent / 'original-date-extraction.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: value for key, value in receipt.items() if key != 'rows'}, ensure_ascii=False))
