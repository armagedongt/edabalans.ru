"""Derived audit of existing sources; never replaces the library."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import sqlite3
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT.parent / 'blog-audit-private'
OUT = Path(__file__).parent
snapshot = json.loads((PRIVATE / 'library-snapshot.json').read_text(encoding='utf-8'))
manifest = json.loads((ROOT / 'content/blog/manifest.json').read_text(encoding='utf-8'))
connection = sqlite3.connect('file:C:/private/edabalans-content-authoring/author-catalog.sqlite?mode=ro',uri=True)
print('SQLITE',connection.execute('select name from sqlite_master where type=?',('table',)).fetchall())
blog = []
all_media = {}
for article in manifest['articles']:
    text = (ROOT/'content/blog/articles'/article['body_file']).read_text(encoding='utf-8')
    names = sorted(set(re.findall(r'/blog/media/([^)]+)',text)+[article['hero']['file'],article['card']['file']]))
    images = []
    for name in names:
        path = ROOT/'content/blog/media'/name
        with Image.open(path) as image:
            row = {'file':name,'bytes':path.stat().st_size,'width':image.width,'height':image.height,'frames':getattr(image,'n_frames',1),'format':image.format,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            images.append(row)
            all_media[name] = row
    sheet = Image.new('RGB',(900,300*((len(names)+2)//3)), 'white')
    draw = ImageDraw.Draw(sheet)
    for index,name in enumerate(names):
        with Image.open(ROOT/'content/blog/media'/name) as image:
            thumb = ImageOps.contain(image.convert('RGB'),(280,265))
            left=(index%3)*300+(300-thumb.width)//2
            top=(index//3)*300
            sheet.paste(thumb,(left,top))
            draw.text(((index%3)*300+10,top+270),f'{index+1}: {Path(name).name}',fill='black')
    sheet.save(PRIVATE/f"media-optimized-{article['source_id']}.jpg",quality=95)
    blog.append({'source_id':article['source_id'],'title':article['title'],'slug':article['slug'],'characters':len(text),'media':images,'bytes':sum(x['bytes'] for x in images),'external_links':re.findall(r'(?<!!)\[[^\]]+\]\((https?://[^)]+)\)',text),'ending':text[-2500:],'related_source_ids':article['related_source_ids'],'cta':article['cta']})
(OUT/'published-audit.json').write_text(json.dumps(blog,ensure_ascii=False,indent=2),encoding='utf-8')
print('BLOG',len(blog),'MEDIA',len(all_media),'BYTES',sum(x['bytes'] for x in all_media.values()))
print('LARGEST',json.dumps(sorted(all_media.values(),key=lambda x:x['bytes'],reverse=True)[:12],ensure_ascii=False))
print('SERVER',Counter(x['source'] for x in snapshot['items']))
print('FULL_LONG',Counter(x['source'] for x in snapshot['items'] if len(x['text'] or '')>=4000))
print('TELEGRAPH_KEYS',snapshot['items'][-1].keys())
