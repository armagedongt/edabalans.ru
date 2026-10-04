"""Responsive renditions are presentation derivatives, never publication sources."""
from html import escape, unescape
import json
from pathlib import Path
import re

BODY_SIZES = '(max-width: 640px) calc(100vw - 32px), (max-width: 800px) calc(100vw - 40px), 760px'
CARD_SIZES = '(max-width: 640px) calc(100vw - 32px), (max-width: 920px) calc((100vw - 62px) / 2), (max-width: 1220px) calc((100vw - 84px) / 3), 379px'

def responsive_manifest(content_dir: Path) -> dict:
    path = content_dir / 'responsive-media.json'
    return json.loads(path.read_text(encoding='utf-8'))['images'] if path.is_file() else {}

def derivative_files(content_dir: Path, originals: frozenset[str]) -> frozenset[str]:
    return frozenset(variant['file'] for name, image in responsive_manifest(content_dir).items() if name in originals for variant in image['variants'])

def apply_responsive_images(html: str, content_dir: Path, originals: frozenset[str]) -> str:
    images = responsive_manifest(content_dir)
    def replace(match):
        tag = match.group(0)
        source = re.search(r'\bsrc="/blog/media/([^"<>]+)"', tag)
        if source is None or 'srcset=' in tag:
            return tag
        name = unescape(source.group(1))
        image = images.get(name) if name in originals else None
        if image is None:
            return tag
        extra = ''
        if not re.search(r'\bwidth=', tag):
            extra += f' width="{image["width"]}"'
        if not re.search(r'\bheight=', tag):
            extra += f' height="{image["height"]}"'
        if image['variants']:
            candidates = {item['width']: '/blog/media/' + item['file'] for item in image['variants']}
            candidates.setdefault(image['width'], '/blog/media/' + name)
            srcset = ', '.join(f'{url} {width}w' for width, url in sorted(candidates.items()))
            sizes = CARD_SIZES if re.search(r'\bclass="[^"]*\bcard-image\b', tag) else BODY_SIZES
            extra += f' srcset="{escape(srcset, quote=True)}" sizes="{sizes}"'
        return tag[:-1] + extra + '>'
    return re.sub(r'<img\b[^>]*>', replace, html)
