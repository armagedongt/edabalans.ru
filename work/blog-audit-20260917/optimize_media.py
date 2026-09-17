"""Versioned derivatives; original public URLs and source images remain intact."""
from pathlib import Path
import io
import json
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
manifest_path = ROOT / 'content/blog/manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
report = []

def derivative(name, width, role):
    source = ROOT / 'content/blog/media' / name
    target_name = str(Path(name).with_name(Path(name).stem + f'-v2-{role}.webp')).replace('\\', '/')
    target = ROOT / 'content/blog/media' / target_name
    with Image.open(source) as original:
        frames, durations = [], []
        for index in range(getattr(original, 'n_frames', 1)):
            original.seek(index)
            frame = ImageOps.exif_transpose(original).convert('RGBA' if 'A' in original.getbands() else 'RGB')
            if frame.width > width:
                frame = ImageOps.contain(frame, (width, round(frame.height * width / frame.width)), Image.Resampling.LANCZOS)
            frames.append(frame.copy())
            durations.append(original.info.get('duration', 0))
        # Lossless preserves captions, diagrams, screenshots and memes without guessing their type.
        buffer = io.BytesIO()
        options = {'format': 'WEBP', 'lossless': True, 'method': 6}
        if len(frames) > 1:
            options.update(save_all=True, append_images=frames[1:], duration=durations, loop=original.info.get('loop', 0))
        frames[0].save(buffer, **options)
        data = buffer.getvalue()
        if len(data) >= source.stat().st_size:
            return name
        target.write_bytes(data)
        with Image.open(target) as check:
            assert check.width == frames[0].width and check.height == frames[0].height
            if len(frames) > 1:
                assert check.n_frames == len(frames)
                actual = []
                for index in range(check.n_frames):
                    check.seek(index)
                    check.load()
                    actual.append(check.info.get('duration', 0))
                assert sum(actual) == sum(durations)
        report.append({'original': name, 'derivative': target_name, 'role': role, 'before_bytes': source.stat().st_size, 'after_bytes': len(data), 'frames': len(frames), 'duration_ms': sum(durations), 'width': frames[0].width, 'height': frames[0].height})
        return target_name

for article in manifest['articles']:
    body_path = ROOT / 'content/blog/articles' / article['body_file']
    text = body_path.read_text(encoding='utf-8')
    names = sorted(set(article['media'] + [article['hero']['file'], article['card']['file']]))
    mapping = {name: derivative(name, 1520, 'body') for name in names}
    for name, replacement in mapping.items():
        text = text.replace('/blog/media/' + name + ')', '/blog/media/' + replacement + ')')
    article['hero']['file'] = mapping[article['hero']['file']]
    article['card']['file'] = derivative(article['card']['file'], 760, 'card')
    # Preserve originals in the whitelist: older immutable cached pages must still resolve them.
    article['media'] = sorted(set(names + list(mapping.values()) + [article['card']['file'], article['hero']['file']]))
    body_path.write_text(text, encoding='utf-8')

manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(Path(__file__).parent / 'media-optimization.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'derivatives': len(report), 'before_bytes': sum(x['before_bytes'] for x in report), 'after_bytes': sum(x['after_bytes'] for x in report)}, ensure_ascii=False))
