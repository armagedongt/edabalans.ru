"""Version-bound, single-character follow-up discovered in rendered review."""
import json
import subprocess
from pathlib import Path
from edit_batch import ROOT, INDEX, body, run_writer
from publish_corrections import sha

directory = Path('D:/CodexPrivate/blog-quality-corrections-20260926/format-followup/11401696')
directory.mkdir(parents=True, exist_ok=True)
remote = """import base64,json
from urllib.request import Request,urlopen
from app.config import get_settings
s=get_settings()
t=base64.b64encode((s.admin_username+':'+s.admin_password).encode()).decode()
r=Request('http://127.0.0.1:8000/admin/api/blog/articles/pohudenie-nachinaetsya-ne-s-pohudeniya',headers={'Authorization':'Basic '+t,'Host':'edabalans.ru'})
with urlopen(r,timeout=25) as response: print(response.read().decode())
"""
snapshot = directory/'runtime-before.json'
if not snapshot.exists():
    result = subprocess.run(['ssh','edabalans-prod','cd /opt/edabalans && docker compose exec -T backend python -'], input=remote, text=True, capture_output=True, encoding='utf-8', check=True, timeout=60)
    snapshot.write_text(json.dumps(json.loads(result.stdout), ensure_ascii=False, indent=2), encoding='utf-8')
before = json.loads(snapshot.read_text(encoding='utf-8'))['article']
source = body(before['markdown'])
old = '**Девушка 28 лет**, * 66 кг'
new = '**Девушка 28 лет**, *66 кг'
if source.count(old) != 1:
    raise ValueError('Expected exact one formatting fragment')
draft = source.replace(old, new)
if body((ROOT/'content/blog/articles/11401696.md').read_text(encoding='utf-8')) != draft:
    raise ValueError('Local text differs outside authorized one space')
(directory/'original.md').write_text(source, encoding='utf-8')
(directory/'targeted.md').write_text(draft, encoding='utf-8')
task = {'note':'Удаление одного пробела после открывающей звёздочки: иначе CommonMark не открывает курсив. Все слова и остальные символы защищены.', 'work_profile':'develop_existing','edit_mode':'targeted_edit','source_basis':'full_source','surface_context':'site_article','delivery_platform':'website','format_profile':'article','source_text':source,'editable_scope':[old],'preservation_anchors':['не расплескать на бесполезные телодвижения'],'required_facts':[],'forbidden_claims':[]}
(directory/'targeted.task.json').write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')
run_writer(['prepare','--task',str(directory/'targeted.task.json'),'--index',str(INDEX),'--output',str(directory/'targeted.pack.json')])
run_writer(['review','--pack',str(directory/'targeted.pack.json'),'--draft',str(directory/'targeted.md'),'--reviewer','root-commonmark-one-space','--output',str(directory/'targeted.review.json')])
run_writer(['validate','--pack',str(directory/'targeted.pack.json'),'--draft',str(directory/'targeted.md'),'--review',str(directory/'targeted.review.json'),'--output',str(directory/'targeted.validation.json')])
print(json.dumps({'source_id':'11401696','before_version':before['version'],'draft_sha256':sha((directory/'targeted.md').read_bytes()),'validation':json.loads((directory/'targeted.validation.json').read_text(encoding='utf-8'))['status']}))
