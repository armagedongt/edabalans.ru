"""Narrow editorial pass: media URLs and one explicitly obsolete bot screenshot."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent / 'machine'
PRIVATE = ROOT.parent / 'blog-audit-private' / 'writer'
PRIVATE.mkdir(exist_ok=True)
BASE_REVISION='7c7f434'
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / 'tools'))
from author_workflow import prepare, create_review, write_json
from validate_author_draft import validate

for article in json.loads((ROOT/'content/blog/manifest.json').read_text(encoding='utf-8'))['articles']:
    sid = article['source_id']
    path = 'content/blog/articles/' + article['body_file']
    source = subprocess.check_output(['git', 'show', BASE_REVISION+':'+path], cwd=ROOT).decode('utf-8')
    draft = (ROOT/path).read_text(encoding='utf-8')
    if source == draft:
        continue
    fragments = re.findall(r'!\[[^\]]*\]\(/blog/media/[^)]+\)', source)
    scope = [{'source':f + ('\n\n\n' if 'Тест о комфорте' in f else ''), 'instruction':'Change only local media URL to versioned optimized derivative; remove only obsolete comfort-test bot screenshot and its adjacent blank lines, preserve all other images, alt text and position.'} for f in fragments if f not in draft]
    assert scope
    anchors = [line for line in source.splitlines() if len(line)>60 and not line.startswith(('!','blog_cta'))][:3]
    task = {'note':'Точечное изменение медиа без рерайта принятого текста. Удалить только скриншот старого теста о комфорте похудения в боте. Остальные изменения — адреса локальных оптимизированных изображений.', 'work_profile':'develop_existing', 'edit_mode':'targeted_edit', 'source_basis':'full_source', 'surface_context':'site_article', 'format_profile':'article', 'source_text':source, 'editable_scope':scope, 'fact_sources':[{'name':'Accepted blog article at base revision', 'fingerprint':hashlib.sha256(source.encode()).hexdigest()}]}
    task_path=PRIVATE/(sid+'.task.json');pack=PRIVATE/(sid+'.pack.json');draft_path=PRIVATE/(sid+'.md');review=PRIVATE/(sid+'.review.json')
    task['preservation_anchors'] = anchors
    write_json(task_path,task)
    draft_path.write_text(draft,encoding='utf-8')
    prepare(task_path,Path('C:/private/edabalans-content-authoring/voice/v1/voice-index.sqlite'),pack)
    initial=validate(pack,draft_path)
    if initial['status']=='needs_fix':
        raise ValueError(json.dumps(initial,ensure_ascii=False))
    notes='Сопоставлен полный diff принятого исходника: изменены только локальные адреса медиа; для 11401696 удалён скриншот старого бот-теста. Ни один абзац, медицинское утверждение, ссылка на источник или авторский баннер не переписан. Анимации проверены по кадрам и суммарной длительности; lossless производные, где меньше оригинала.'
    create_review(pack,draft_path,review,reviewer='Codex targeted source-preservation review',check_values=[c['id']+'='+notes for c in initial['pending_manual_reviews']])
    report=validate(pack,draft_path,review)
    assert report['status']=='pass', report
    summary={k:v for k,v in task.items() if k not in ['source_text','editable_scope']}
    summary.update(source_sha256=hashlib.sha256(source.encode()).hexdigest(),editable_image_count=len(scope),private_artifact_note='Executable full source/task/pack outside Git')
    for suffix,payload in [('task-summary',summary),('validation',report),('review',json.loads(review.read_text(encoding='utf-8')))]:
        (OUT/(sid+'.'+suffix+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(sid,report['status'])
