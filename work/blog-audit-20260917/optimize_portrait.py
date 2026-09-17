from pathlib import Path
import json
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[2]
source=ROOT/'backend/app/static/blog/assets/sergey-author.png'
target=source.with_name('sergey-author-v2.webp')
with Image.open(source) as image:
    derivative=ImageOps.contain(image,(760,760),Image.Resampling.LANCZOS)
    derivative.save(target,format='WEBP',lossless=True,method=6)
assert target.stat().st_size < source.stat().st_size
report={'original':source.name,'derivative':target.name,'before_bytes':source.stat().st_size,'after_bytes':target.stat().st_size,'width':derivative.width,'height':derivative.height,'crop':'none'}
(Path(__file__).parent/'portrait-optimization.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
