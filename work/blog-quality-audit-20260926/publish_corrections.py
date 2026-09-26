"""Publish only reviewed corrections; restart safely after a lost SSH response."""
import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

from edit_batch import PRIVATE, ROOT, body, run_writer

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    articles = json.loads((ROOT/'content/blog/manifest.json').read_text(encoding='utf-8'))['articles'][:10]
    for item in articles:
        identity = str(item['source_id'])
        directory = PRIVATE/identity
        snapshot = directory/'runtime-before.json'
        if not snapshot.exists():
            print(identity, 'SKIP: no runtime baseline', flush=True)
            continue
        original = body((directory/'original.md').read_text(encoding='utf-8'))
        before = json.loads(snapshot.read_text(encoding='utf-8'))['article']
        if body(before['markdown']) != original or before['editorial_status'] != 'published':
            print(identity, 'SKIP: baseline differs or contains unpublished changes', flush=True)
            continue
        draft = directory/'proofread.md'
        report = directory/'proofread.validation.json'
        run_writer(['validate', '--pack', str(directory/'proofread.pack.json'), '--draft', str(draft),
                    '--review', str(directory/'proofread.review.json'), '--output', str(report)])
        validation = json.loads(report.read_text(encoding='utf-8'))
        if validation['status'] != 'pass' or validation['draft_sha256'] != sha(draft.read_bytes()):
            raise ValueError(identity + ': writer gate is not pass')
        markdown = draft.read_text(encoding='utf-8')
        if body((ROOT/'content/blog/articles'/item['body_file']).read_text(encoding='utf-8')) != markdown:
            raise ValueError(identity + ': local content differs from reviewed draft')
        payload = {'slug': item['slug'], 'before': before, 'markdown': markdown, 'apply': options.apply}
        encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
        remote = '''import base64,json
from urllib.request import Request,urlopen
from app.config import get_settings
settings=get_settings()
token=base64.b64encode((settings.admin_username+':'+settings.admin_password).encode()).decode()
p=json.loads(base64.b64decode(PAYLOAD))
base='http://127.0.0.1:8000/admin/api/blog/articles/'+p['slug']
def call(suffix='',method='GET',data=None):
    raw=None if data is None else json.dumps(data).encode()
    req=Request(base+suffix,data=raw,method=method,headers={'Authorization':'Basic '+token,'Host':'edabalans.ru','Content-Type':'application/json'})
    with urlopen(req,timeout=25) as response: return json.load(response)
current=call()['article']
before=p['before']
target=p['markdown']
if current['markdown']==target and current['editorial_status']=='published':
    result={'status':'already_published','version':current['version']}
elif not p['apply']:
    result={'status':'dry_run','version':current['version'],'baseline_matches':current['version']==before['version'] and current['markdown']==before['markdown']}
else:
    if current['version']==before['version'] and current['markdown']==before['markdown'] and current['editorial_status']=='published':
        current=call('/text','PATCH',{'expected_version':current['version'],'markdown':target,'card':current['card'],'card_fit':current['card_fit']})['article']
    elif not (current['version']==before['version']+1 and current['markdown']==target and current['card']==before['card'] and current['card_fit']==before['card_fit']):
        raise RuntimeError('Concurrent editor change: no overwrite')
    published=call('/publish','POST',{'expected_version':current['version'],'confirm':True})
    final=call()['article']
    if final['markdown']!=target or final['editorial_status']!='published':
        raise RuntimeError('Published verification mismatch')
    result={'status':'published','version':final['version'],'published_version':published['published_version'],'public_url':published['public_url']}
print(json.dumps(result))
'''.replace('PAYLOAD', repr(encoded))
        try:
            result = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','edabalans-prod',
                                     'cd /opt/edabalans && docker compose exec -T backend python -'],
                                    input=remote, capture_output=True, text=True, encoding='utf-8', timeout=100)
        except subprocess.TimeoutExpired:
            print(identity, 'UNKNOWN: timeout, rerun to reconcile', flush=True)
            continue
        if result.returncode:
            print(identity, 'FAILED', result.stderr[-350:], flush=True)
            continue
        receipt = json.loads(result.stdout)
        receipt.update(source_id=identity, markdown_sha256=sha(draft.read_bytes()))
        (directory/('publish-receipt.json' if options.apply else 'dry-run.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print(identity, receipt, flush=True)

if __name__ == '__main__':
    main()
