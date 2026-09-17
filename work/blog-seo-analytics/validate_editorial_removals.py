"""Validate only the two owner-selected historical ending removals."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT.parent / 'blog-audit-private' / 'writer-seo-removals'
PRIVATE.mkdir(exist_ok=True)
OUT = Path(__file__).parent / 'machine'
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / 'tools'))
from author_workflow import prepare, create_review, write_json
from validate_author_draft import validate

# Independent owner-approved boundaries in the fixed accepted source, never inferred
# from the proposed draft. Any other deletion/change must fail before writer review.
APPROVED_REMOVALS = {
    '11927800': ('## Актуально 365 дней в году!\n', 'blog_cta(\n'),
    'tilda-49734795': ('### Совет №16\n', '![Сергей Воронцов: похудеть быстро или навсегда]'),
}

def approved_fragment(sid, source):
    start_marker, end_marker = APPROVED_REMOVALS[sid]
    assert source.count(start_marker) == 1
    start = source.index(start_marker)
    assert source.count(end_marker) == 1
    end = source.index(end_marker, start)
    return source[start:end]

def assert_approved_draft(sid, source, draft):
    fragment = approved_fragment(sid, source)
    assert draft == source.replace(fragment, '', 1), 'Change outside owner-approved removal'
    return fragment

def safe_artifact(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

for sid in ['11927800', 'tilda-49734795']:
    rel = 'content/blog/articles/' + sid + '.md'
    source = subprocess.check_output(['git', 'show', 'f458798:'+rel], cwd=ROOT).decode()
    draft = (ROOT/rel).read_text(encoding='utf-8')
    fragments = [assert_approved_draft(sid, source, draft)]
    assert all(source.count(fragment)==1 for fragment in fragments)
    task = {
        'note':'Удалить только согласованный исторический хвост; фактура, аргументы, остальные медиа и CTA сохраняются.',
        'work_profile':'develop_existing','edit_mode':'targeted_edit','source_basis':'full_source',
        'surface_context':'site_article','delivery_platform':'website','format_profile':'article',
        'source_text':source,
        'editable_scope':[{'source':fragment,'instruction':'Remove exactly this owner-approved historical ending; introduce no replacement text.'} for fragment in fragments],
        'preservation_anchors':[line for line in source.splitlines() if len(line)>70 and not line.startswith(('!','blog_cta','### Совет №16'))][:3],
        'fact_sources':[{'name':'Accepted article f458798','fingerprint':hashlib.sha256(source.encode()).hexdigest()}],
        'forbidden_claims':['Не обновлять медицинские и численные утверждения. Не переписывать остальные абзацы.'],
    }
    task_path=PRIVATE/(sid+'.task.json')
    pack=PRIVATE/(sid+'.pack.json')
    draft_path=PRIVATE/(sid+'.md')
    review=PRIVATE/(sid+'.review.json')
    write_json(task_path,task)
    draft_path.write_text(draft,encoding='utf-8')
    prepare(task_path,Path('C:/private/edabalans-content-authoring/voice/v1/voice-index.sqlite'),pack)
    initial=validate(pack,draft_path)
    assert initial['status']!='needs_fix', initial
    note='Полный исходник и защищённый diff проверены: удаление только согласованного блока. Новых фраз нет, антинейрослоп новых связок не применим; фактура и прочие медиа сохранены.'
    create_review(pack,draft_path,review,reviewer='Codex source-preservation editorial review',check_values=[c['id']+'='+note for c in initial['pending_manual_reviews']])
    report=validate(pack,draft_path,review)
    assert report['status']=='pass', report
    safe_artifact(OUT/(sid+'.validation.json'),report)
    safe_artifact(OUT/(sid+'.review.json'),json.loads(review.read_text(encoding='utf-8')))
    summary={k:v for k,v in task.items() if k not in ['source_text','editable_scope']}
    summary.update(source_sha256=hashlib.sha256(source.encode()).hexdigest(),removed_fragment_count=len(fragments),private_full_source_pack=True)
    safe_artifact(OUT/(sid+'.task-summary.json'),summary)
    print(sid,report['status'])
