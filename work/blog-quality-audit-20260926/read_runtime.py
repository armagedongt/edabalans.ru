"""Read existing admin API through SSH; credentials stay inside backend container."""
import json
import argparse
import subprocess
from pathlib import Path
from edit_batch import selected_articles

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('D:/CodexPrivate/blog-quality-corrections-20260926')
parser = argparse.ArgumentParser()
parser.add_argument('--batch', type=int)
articles = selected_articles(parser.parse_args().batch)
for article in articles:
    target = OUT/str(article['source_id'])/'runtime-before.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        print(article['source_id'], 'snapshot exists; refresh required before mutation')
        continue
    remote = '''import base64,json
from urllib.request import Request,urlopen
from app.config import get_settings
settings=get_settings()
token=base64.b64encode((settings.admin_username+':'+settings.admin_password).encode()).decode()
request=Request('http://127.0.0.1:8000/admin/api/blog/articles/'+SLUG,headers={'Authorization':'Basic '+token,'Host':'edabalans.ru'})
with urlopen(request,timeout=20) as response: print(response.read().decode())
'''.replace('SLUG', repr(article['slug']))
    result = subprocess.run(['ssh','-o','ConnectTimeout=15','edabalans-prod',
                             'cd /opt/edabalans && docker compose exec -T backend python -'],
                            input=remote, capture_output=True, text=True, encoding='utf-8', timeout=45)
    if result.returncode:
        print(article['source_id'], 'read failed', result.stderr[-250:])
        continue
    payload = json.loads(result.stdout)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    item=payload['article']
    print(article['source_id'], 'version',item['version'],'status',item['editorial_status'])
