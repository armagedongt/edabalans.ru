"""Prepare one exact, already inspected correction set against a saved API baseline."""
import argparse
import json
from pathlib import Path
from edit_batch import ROOT, PRIVATE, INDEX, body, run_writer, selected_articles

parser = argparse.ArgumentParser()
parser.add_argument('--source-id', required=True)
parser.add_argument('--batch', type=int, required=True)
parser.add_argument('--changes', required=True)
options = parser.parse_args()
article = next(item for item in selected_articles(options.batch) if str(item['source_id']) == options.source_id)
directory = PRIVATE/'full-review'/options.source_id
before = json.loads((directory/'runtime-before.json').read_text(encoding='utf-8'))['article']
if before['editorial_status'] != 'published':
    raise ValueError('Do not replace unpublished editor work')
source = body(before['markdown'])
config = json.loads(Path(options.changes).read_text(encoding='utf-8'))
draft = source
for change in config['replacements']:
    if source.count(change['from']) != 1 or draft.count(change['from']) != 1:
        raise ValueError('Non-unique authorized fragment')
    draft = draft.replace(change['from'], change['to'], 1)
if draft != body((ROOT/'content/blog/articles'/article['body_file']).read_text(encoding='utf-8')):
    raise ValueError('Local content differs outside the reviewed replacements')
task = {'note':config['note'],'work_profile':'develop_existing','edit_mode':'targeted_edit','source_basis':'full_source','surface_context':'site_article','delivery_platform':'website','format_profile':'article','source_text':source,'editable_scope':[change['from'] for change in config['replacements']],'preservation_anchors':config.get('anchors',[]),'required_facts':[],'forbidden_claims':[]}
for name, value in [('original.md',source),('targeted.md',draft),('targeted.task.json',json.dumps(task,ensure_ascii=False,indent=2))]:
    path=directory/name
    if path.exists() and path.read_text(encoding='utf-8') != value:
        raise ValueError('Preserve existing job: '+str(path))
    path.write_text(value,encoding='utf-8')
run_writer(['prepare','--task',str(directory/'targeted.task.json'),'--index',str(INDEX),'--output',str(directory/'targeted.pack.json')])
run_writer(['review','--pack',str(directory/'targeted.pack.json'),'--draft',str(directory/'targeted.md'),'--reviewer','root-source-media-preservation','--output',str(directory/'targeted.review.json')])
run_writer(['validate','--pack',str(directory/'targeted.pack.json'),'--draft',str(directory/'targeted.md'),'--review',str(directory/'targeted.review.json'),'--output',str(directory/'targeted.validation.json')])
report=json.loads((directory/'targeted.validation.json').read_text(encoding='utf-8'))
print(json.dumps({'source_id':options.source_id,'baseline_version':before['version'],'status':report['status'],'draft_sha256':report['draft_sha256']}))
