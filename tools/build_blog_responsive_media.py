"""Build immutable static-image variants; preserve original media and Markdown."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (480, 960, 1600)

def build(root: Path) -> dict:
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    names = set()
    for article in manifest['articles']:
        if article['status'] != 'published':
            continue
        names.update(article['media'])
        names.add(article['card']['file'])
        if article['hero'].get('show', True):
            names.add(article['hero']['file'])
        body = (root / 'articles' / article['body_file']).read_text(encoding='utf-8')
        names.update(re.findall(r'!\[[^\]]*\]\(/blog/media/([^)]+)\)', body))
    entries = {}
    skipped = []
    for name in sorted(names):
        path = root / 'media' / name
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if path.suffix.lower() in {'.mp4', '.webm', '.mov'}:
            skipped.append({'file': name, 'reason': 'video retained without transcoding'})
            continue
        with Image.open(path) as original:
            if getattr(original, 'n_frames', 1) > 1:
                skipped.append({'file': name, 'reason': 'animation retained without frame loss'})
                continue
            image = ImageOps.exif_transpose(original)
            width, height = image.size
            entry = {'sha256': digest, 'width': width, 'height': height, 'variants': []}
            if width > WIDTHS[0] or len(raw) > 120_000:
                image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
                for target_width in sorted({min(width, target) for target in WIDTHS}):
                    target_height = max(1, round(height * target_width / width))
                    # The recipe is part of the path: changing quality requires a new version.
                    relative = f'responsive/{digest[:24]}-q90-v1/{target_width}w.webp'
                    target = root / 'media' / relative
                    if not target.exists():
                        output = BytesIO()
                        image.resize((target_width, target_height), Image.Resampling.LANCZOS).save(output, 'WEBP', quality=90, method=6, icc_profile=original.info.get('icc_profile', b''))
                        encoded = output.getvalue()
                    else:
                        encoded = target.read_bytes()
                    if len(encoded) >= len(raw):
                        continue
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(encoded)
                    entry['variants'].append({'file': relative, 'width': target_width, 'height': target_height, 'bytes': len(encoded)})
            entries[name] = entry
    return {'version': 1, 'recipe': 'webp-q90-v1; no crop; no upscale; original retained', 'images': entries, 'skipped': skipped}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--content-dir', type=Path, default=ROOT / 'content/blog')
    args = parser.parse_args()
    result = build(args.content_dir)
    (args.content_dir / 'responsive-media.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'static_images': len(result['images']), 'variants': sum(len(item['variants']) for item in result['images'].values()), 'skipped': len(result['skipped'])}))
