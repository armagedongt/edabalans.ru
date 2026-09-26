"""Prepare private, version-bound writer jobs for the first correction batches."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = Path('D:/CodexPrivate/blog-quality-corrections-20260926')
WRITER = Path('D:/CodexWork/calorie-publication-ready-20260925/tools/author_workflow.py')
INDEX = Path('C:/private/edabalans-content-authoring/voice/v1/voice-index.sqlite')
ANCHORS = ['«Правило 1%»', 'Спасибо за внимание.', 'Переходим к живым примерам 👇',
           'АГА!!! (нет).', 'Не сходите с дистанции!', 'Фотографии на живых:',
           'Кушайте белок, не занимайтесь чревоугодием, носите шапку!', 'И баеньки...',
           'Учился 6 лет, а может и больше.', 'Скучно, зато эффективно 👇']

def body(text):
    return re.sub(r'\n*blog_cta\(\s*\w+\s*\)\s*$', '', text).strip() + '\n'

def run_writer(args):
    result = subprocess.run([sys.executable, str(WRITER), *args], capture_output=True, text=True, encoding='utf-8')
    if result.returncode and not (args[0] == 'validate' and Path(args[args.index('--output') + 1]).exists() and json.loads(Path(args[args.index('--output') + 1]).read_text(encoding='utf-8')).get('status') == 'manual_review_required'):
        raise RuntimeError(result.stdout + result.stderr)

def main():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    articles = json.loads((ROOT/'content/blog/manifest.json').read_text(encoding='utf-8'))['articles'][:10]
    corrections = json.loads((Path(__file__).parent/'corrections.json').read_text(encoding='utf-8'))
    for article, anchor in zip(articles, ANCHORS):
        identity = str(article['source_id'])
        directory = PRIVATE/identity
        directory.mkdir(exist_ok=True)
        original = directory/'original.md'
        if not original.exists():
            original.write_bytes((ROOT/'content/blog/articles'/article['body_file']).read_bytes())
        if '--apply' in sys.argv:
            source = original.read_text(encoding='utf-8')
            edited = source
            for old, new in corrections[identity]:
                if edited.count(old) != 1:
                    raise ValueError(f'{identity}: replacement must be unique: {old!r}')
                edited = edited.replace(old, new, 1)
            destination = ROOT/'content/blog/articles'/article['body_file']
            if destination.read_text(encoding='utf-8') not in (source, edited):
                raise ValueError(f'{identity}: concurrent local change')
            destination.write_text(edited, encoding='utf-8')
            draft = directory/'proofread.md'
            draft.write_text(body(edited), encoding='utf-8')
            run_writer(['validate','--pack',str(directory/'proofread.pack.json'),
                        '--draft',str(draft),'--output',str(directory/'proofread.validation.json')])
            print(identity, 'corrected and validated')
            continue
        task = {
            'note': 'Разрешённая корректура опубликованной статьи: только опечатки, орфография, пунктуация и явное согласование. Без идейных, численных и фактических изменений. Не затирать шутки, намеренную разговорность и прямые цитаты.',
            'work_profile': 'develop_existing', 'edit_mode': 'proofread', 'source_basis': 'full_source',
            'surface_context': 'site_article', 'delivery_platform': 'website', 'format_profile': 'article',
            'source_text': body(original.read_text(encoding='utf-8')),
            'required_facts': [], 'forbidden_claims': [],
            'preservation_anchors': [anchor],
        }
        task_path = directory/'proofread.task.json'
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')
        run_writer(['prepare','--task',str(task_path),'--index',str(INDEX),'--output',str(directory/'proofread.pack.json')])
        print(identity, 'prepared')

if __name__ == '__main__': main()
