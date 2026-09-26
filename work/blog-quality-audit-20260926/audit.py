"""Read-only evidence inventory: no edits to articles, media or runtime."""
import concurrent.futures
import hashlib
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
ORIGIN = 'https://blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai'

class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.images=[]; self.metas={}; self.canonical=None; self.scripts=[]; self.schemas=[]; self.h1=0; self.ld=False; self.buffer=''
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if tag=='img': self.images.append(d)
        if tag=='meta': self.metas[d.get('name',d.get('property',''))]=d.get('content','')
        if tag=='link' and d.get('rel')=='canonical': self.canonical=d.get('href')
        if tag=='h1': self.h1+=1
        if tag=='script':
            self.scripts.append(d.get('src','')); self.ld=d.get('type')=='application/ld+json'; self.buffer=''
    def handle_data(self, data):
        if self.ld:self.buffer+=data
    def handle_endtag(self, tag):
        if tag=='script' and self.ld:
            try:self.schemas.append(json.loads(self.buffer))
            except ValueError:pass
            self.ld=False

def digest(b):return hashlib.sha256(b).hexdigest()
manifest=json.loads((ROOT/'content/blog/manifest.json').read_text(encoding='utf-8'))
reviews=[]
for path in (ROOT/'work').rglob('*.review.json'):
    try: obj=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError):continue
    if isinstance(obj,dict):reviews.append((path,obj))

def review_checks(obj):
    checks=obj.get('checks',[])
    if isinstance(checks,dict):return [{'id':k,'result':v} for k,v in checks.items()]
    return [c for c in checks if isinstance(c,dict)]

cached={}
if '--offline' in sys.argv:
    cached={x['source_id']:x['live'] for x in json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))['articles']}

def inspect(a):
    path=ROOT/'content/blog/articles'/a['body_file']; raw=path.read_bytes(); text=raw.decode('utf-8')
    sha=digest(raw); normalized=digest(text.replace('\r\n','\n').encode())
    receipts=[(p,r) for p,r in reviews if p.name==str(a['source_id'])+'.review.json']
    current=[(p,r) for p,r in receipts if r.get('draft_sha256') in {sha,normalized}]
    matches=re.findall(r'!\[[^\]]*\]\(([^\s)]+)',text)
    active={v.split('/blog/media/',1)[1] for v in matches if '/blog/media/' in v}
    for k in ('card','hero'):
        x=a.get(k) or {}
        if x.get('file') and (k=='card' or x.get('show',True)):active.add(x['file'])
    media=[]
    for rel in sorted(active):
        p=ROOT/'content/blog/media'/rel
        row={'path':rel,'exists':p.exists()}
        if p.exists():
            row['bytes']=p.stat().st_size
            try:
                with Image.open(p) as im: row.update(width=im.width,height=im.height,format=im.format,frames=getattr(im,'n_frames',1))
            except Exception as e:row['inspection_error']=str(e)
        media.append(row)
    checks=sorted({c.get('id','') for _,r in receipts for c in review_checks(r)})
    findings=[]
    for line_num,line in enumerate(text.splitlines(),1):
        if re.search(r'\ufffd|&#\d+;|&nbsp;|\[/?(?:b|i|u|img)\]|\{\{',line):findings.append({'line':line_num,'text':line[:250],'type':'format_candidate'})
        if re.search(r'пишите.{0,25}коммент|ставьте.{0,15}(плюс|минус)|подписывайтесь.{0,25}сообщество',line,re.I):findings.append({'line':line_num,'text':line[:250],'type':'platform_tail_candidate'})
    result={'source_id':a['source_id'],'title':a['title'],'slug':a['slug'],'body_sha256':sha,
            'review_receipts':[{'path':str(p.relative_to(ROOT)),'date':r.get('reviewed_at'),'hash_matches':r.get('draft_sha256') in {sha,normalized},'checks':[c.get('id') for c in review_checks(r)]} for p,r in receipts],
            'current_review_matches':len(current),'historical_check_ids':checks,
            'remote_markdown_images':[v for v in matches if v.startswith(('http:','https:'))],
            'media':media,'active_media_bytes':sum(x.get('bytes',0) for x in media),
            'headings':len(re.findall(r'^#{2,3} ',text,re.M)),'bold_spans':len(re.findall(r'\*\*[^*]+\*\*',text)),
            'candidates':findings,'cta':a.get('cta'),'related':a.get('related_source_ids',[])}
    url=ORIGIN+'/articles/'+a['slug']
    if a['source_id'] in cached:
        result['live']=cached[a['source_id']]
        return result
    try:
        with urlopen(Request(url,headers={'User-Agent':'EdabalansQualityAudit/1.0'}),timeout=18) as response:
            html=response.read().decode('utf-8'); status=response.status
        parsed=Page();parsed.feed(html)
        result['live']={'status':status,'canonical':parsed.canonical,'h1':parsed.h1,'description':parsed.metas.get('description'),'og_image':parsed.metas.get('og:image'),
                        'schemas':parsed.schemas,'scripts':parsed.scripts,'images':parsed.images,
                        'metrika_reference':bool(re.search(r'mc\.yandex|ym\(\d|metrika/tag',html)),
                        'dates_present':bool(re.search(r'datePublished|dateModified|<time',html))}
    except Exception as e:result['live']={'error':str(e)}
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    rows=list(pool.map(inspect,manifest['articles']))
summary={'articles':len(rows),'historical_review_found':sum(bool(x['review_receipts']) for x in rows),'current_hash_match':sum(bool(x['current_review_matches']) for x in rows),
         'remote_markdown_images':sum(len(x['remote_markdown_images']) for x in rows),'missing_active_media':sum(not m['exists'] for x in rows for m in x['media']),
         'active_files_unique':len({m['path'] for x in rows for m in x['media']}),'files_over_500KiB':len({m['path'] for x in rows for m in x['media'] if m.get('bytes',0)>512000}),
         'files_over_1MiB':len({m['path'] for x in rows for m in x['media'] if m.get('bytes',0)>1048576}),
         'live_200':sum(x['live'].get('status')==200 for x in rows),'live_errors':sum('error' in x['live'] for x in rows),
         'live_metrika_in_html':sum(x['live'].get('metrika_reference',False) for x in rows),'live_dates':sum(x['live'].get('dates_present',False) for x in rows)}
if '--verify-media' in sys.argv:
    urls=sorted({urljoin(ORIGIN,i['src']) for x in rows for i in x['live'].get('images',[]) if i.get('src','').startswith('/blog/media/')})
    def verify(url):
        try:
            with urlopen(Request(url,headers={'Range':'bytes=0-0','User-Agent':'EdabalansQualityAudit/1.0'}),timeout=12) as response:
                response.read(1)
                return {'url':url,'status':response.status,'type':response.headers.get('Content-Type'),'length':response.headers.get('Content-Length'),'content_range':response.headers.get('Content-Range')}
        except Exception as e:return {'url':url,'error':str(e)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: checks=list(pool.map(verify,urls))
    (OUT/'media-http.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    summary['media_http_checked']=len(checks)
    summary['media_http_ok']=sum(c.get('status') in (200,206) and c.get('type','').startswith('image/') for c in checks)
(OUT/'inventory.json').write_text(json.dumps({'scope':'manifest Markdown + current HTTP HTML; no admin/runtime raw Markdown access; no full proofreading or neuroslop audit','summary':summary,'articles':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# Поартикульная техническая и архивная проверка — 26.09.2026','','Не является новым writer pass, проверкой орфографии или полной проверкой нейрослопа. Нет доступа к закрытым runtime-версиям Markdown; проверены файлы Git и публичный HTML. Совпадение SHA допускает только техническую нормализацию CRLF→LF. Отсутствие совпадения не доказывает смысловую правку.','','| Материал | Старых review | SHA совпал | H2/H3 | Выделения ** | Активные медиа, КБ | HTTP |','|---|---:|---:|---:|---:|---:|---:|']
for x in rows:
    lines.append(f"| [{x['title']}]({ORIGIN}/articles/{x['slug']}) | {len(x['review_receipts'])} | {x['current_review_matches']} | {x['headings']} | {x['bold_spans']} | {x['active_media_bytes']/1024:.0f} | {x['live'].get('status','ошибка')} |")
lines+=['','## Крупнейшие используемые файлы','']
media={m['path']:m for x in rows for m in x['media']}
for m in sorted(media.values(),key=lambda x:x.get('bytes',0),reverse=True)[:25]:lines.append(f"- `{m['path']}` — {m.get('bytes',0)/1024:.0f} КБ, {m.get('width')}×{m.get('height')}, {m.get('format')}.")
lines+=['','## Архивные доказательства по каждой статье','']
for x in rows:
    lines += [f"### {x['title']}",'',f"Текущий SHA: `{x['body_sha256']}`.",f"Исторические check IDs: {', '.join(x['historical_check_ids']) or 'не найдены'}.",'']
    for r in x['review_receipts']:lines.append(f"- `{r['path']}`; дата {r['date']}; SHA текущего тела совпал: {r['hash_matches']}.")
    for f in x['candidates']:lines.append(f"- Кандидат, требует контекста, строка {f['line']}: {f['text']}")
    lines.append('')
(OUT/'ARTICLE_CHECKS.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
