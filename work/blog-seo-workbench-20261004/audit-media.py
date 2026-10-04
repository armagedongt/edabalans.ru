"""Measure manifest-owned images without changing originals or article text."""
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
manifest = json.loads((ROOT / 'content/blog/manifest.json').read_text(encoding='utf-8'))
names = set()
displayed = set()
for article in manifest['articles']:
    if article['status'] == 'published':
        names.update(article['media'])
        names.update((article['hero']['file'], article['card']['file']))
        displayed.add(article['card']['file'])
        if article['hero'].get('show', True):
            displayed.add(article['hero']['file'])
        body = (ROOT / 'content/blog/articles' / article['body_file']).read_text(encoding='utf-8')
        displayed.update(re.findall(r'!\[[^\]]*\]\(/blog/media/([^)]+)\)', body))
rows = []
for name in sorted(names):
    path = ROOT / 'content/blog/media' / name
    raw = path.read_bytes()
    row = {'file': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    row['displayed_image'] = name in displayed
    if path.suffix.lower() in {'.mp4', '.webm', '.mov'}:
        row['kind'] = 'video'
        rows.append(row)
        continue
    try:
        with Image.open(path) as image:
            row.update(width=image.width, height=image.height, format=image.format, frames=getattr(image, 'n_frames', 1))
            row['kind'] = 'animation' if row['frames'] > 1 else 'static'
    except Exception as error:
        row.update(kind='unreadable', error=str(error))
    rows.append(row)
receipt = {'scope': 'manifest published media only; no original file changes', 'files': len(rows), 'total_bytes': sum(row['bytes'] for row in rows), 'kinds': dict(Counter(row['kind'] for row in rows)), 'over_500kb': sum(row['bytes'] > 500_000 for row in rows), 'displayed_images': len(displayed), 'displayed_image_bytes': sum(row['bytes'] for row in rows if row['displayed_image']), 'rows': rows}
(Path(__file__).parent / 'media-audit.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: value for key, value in receipt.items() if key != 'rows'}, ensure_ascii=False))
print(json.dumps(sorted(rows, key=lambda row: row['bytes'], reverse=True)[:8], ensure_ascii=False, indent=2))
