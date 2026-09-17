"""Revalidate known author URLs via public API; never change account pages."""
import concurrent.futures
import hashlib
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT.parent / 'blog-audit-private'
spec = importlib.util.spec_from_file_location('collector', ROOT/'tools/collect_telegraph.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
old = [json.loads(line) for line in Path('C:/private/edabalans-content-authoring/telegraph/pages.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]

def fetch(reference):
    try:
        page = collector.export_page('', reference, 25)
        page['checked_at'] = datetime.now(timezone.utc).isoformat()
        page['old_text_sha256'] = hashlib.sha256(reference['text_plain'].encode()).hexdigest()
        page['text_sha256'] = hashlib.sha256(page['text_plain'].encode()).hexdigest()
        page['changed_since_snapshot'] = page['old_text_sha256'] != page['text_sha256']
        page['published_at'] = None
        if len(page['text_plain']) >= 3000:
            try:
                with urlopen(Request(page['url'],headers={'User-Agent':'edabalans-library-audit/1.0'}),timeout=25) as response:
                    html = response.read().decode('utf-8')
                match = re.search(r'<time[^>]*datetime="([^"]+)"',html)
                page['published_at'] = match.group(1) if match else None
                page['date_evidence'] = 'public HTML time[datetime]' if match else 'date unavailable; path MM-DD is not chronology'
            except Exception as error:
                page['date_evidence'] = type(error).__name__
        return page
    except Exception as error:
        return {'path':reference['path'],'url':reference['url'],'error':type(error).__name__}

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
    pages = list(executor.map(fetch,old))
success = [x for x in pages if 'error' not in x]
errors = [x for x in pages if 'error' in x]
(PRIVATE/'telegraph-current.json').write_text(json.dumps(success,ensure_ascii=False,indent=2),encoding='utf-8')
report = {'checked_at':datetime.now(timezone.utc).isoformat(),'known_account_snapshot_urls':len(old),'current_full_pages':len(success),'changed_since_20260825':sum(x['changed_since_snapshot'] for x in success),'errors':errors,'account_list_fresh':False,'scope_note':'Known 211 account URLs revalidated. Account token not available to this runtime; getPageList not called. No claim that no new account pages exist.','read_only_methods':['getPage','getViews','public HTML date']}
(Path(__file__).parent/'telegraph-refresh-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
