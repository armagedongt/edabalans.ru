"""Read-only library snapshot. No credentials or raw content enter Git."""
import base64
import json
import subprocess
from pathlib import Path

remote = '''import json,base64
from urllib.request import Request,urlopen
from app.config import get_settings
from app.database import SessionLocal
from app.models import ContentItem,ContentSource,ContentItemVersion,ContentFamilyMembership
from app.content_authoring_service import _item_payload,authoring_summary
from sqlalchemy import select
s=get_settings()
auth=base64.b64encode((s.admin_username+":"+s.admin_password).encode()).decode()
def api(path):
 return json.load(urlopen(Request("http://127.0.0.1:8000"+path,headers={"Authorization":"Basic "+auth})))
context=api("/admin/api/library/task-context?topic=blog&task_type=publication_catalog_audit&surface=open&limit=50")
reviews=api("/admin/api/library/reviews?status=all&limit=500")
with SessionLocal() as db:
 rows=db.execute(select(ContentItem,ContentSource,ContentFamilyMembership).join(ContentSource,ContentSource.id==ContentItem.source_id).outerjoin(ContentFamilyMembership,ContentFamilyMembership.item_id==ContentItem.id).where(ContentSource.platform.in_(["pikabu","telegraph","vc","vc.ru","tilda"]))).all()
 items=[]
 for item,source,membership in rows:
  payload=_item_payload(db,item,source)
  payload["family_id"]=str(membership.family_id) if membership else None
  items.append(payload)
 summary=authoring_summary(db)
print(json.dumps({"context":context,"reviews":reviews,"summary":summary,"items":items},ensure_ascii=False,default=str))'''
payload = base64.b64encode(remote.encode()).decode()
command = 'cd /opt/edabalans && docker compose exec -T backend python -c "import base64;exec(base64.b64decode(\'' + payload + '\'))"'
result = subprocess.run(['ssh','-o','BatchMode=yes','edabalans-prod',command],capture_output=True,text=True,encoding='utf-8',check=True)
data = json.loads(result.stdout)
target = Path(__file__).parents[3] / 'blog-audit-private' / 'library-snapshot.json'
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'snapshot':str(target),'summary':data['summary'],'full_items':len(data['items']),'sources':sorted(set(x['source'] for x in data['items'])),'context_keys':list(data['context']),'review_count':len(data['reviews'])},ensure_ascii=False))
