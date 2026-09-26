"""Prepare private, version-bound writer jobs for the first correction batches."""
import json
import argparse
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

EXTRA_ANCHORS = {
    '11875492': 'нимбом над одной банкой',
    'tilda-49734795': 'На ваши бока отложатся только лишние калории',
    'tilda-49745867': 'ногти колосятся',
    'tilda-67280331': 'Не перепутайте',
    '13277231': 'Совпадение? Ну хз.',
    '11401696': 'не расплескать на бесполезные телодвижения',
    '11927800': 'бессердечная ты тварь',
    '11269472': 'героической тренировки пищевода',
    '12237133': 'На фундаменте из мазохизма',
    'Sahar-09-18': 'В сухом остатке',
    '11207593': 'ай, страшана',
    '10999474': '...а вторая — все твои мечты.',
    'training-combined-2023': 'сразу +20 к скорости',
    '12922345': 'Алё?!?',
    '14021584': 'судьба вашей ипотеки',
    '14102926': 'Всех обнял',
    '14183275': 'Александр Григорьевич вам судья',
    '12857458': 'Пу-пу-пу...',
    '693339': 'подлива от доширака',
    '11522121': 'воображаемые подойдут',
    '11762932': 'кошка родила',
    '12296286': 'вызывать кракена калории',
    '13436070': 'ни-ко-гда',
    '13785403': 'Добавляй, а не исключай!',
    '2e269fdc52d600a64753': 'две плюшевые проблемы',
    '0d583f6ad1cea0eef750': 'Зачем я это сделал',
    '13327360': 'ну штош, делайте, что хотите',
    '11277666': 'Неделю, Карл!',
    '11494317': 'сгорел сарай — гори и хата',
    '11833079': 'Ууууъъъ!!!',
    '11857250': 'Нет, шаги — это тема!',
    '13355824': 'тооооолстыми кусками',
    'd1baceb9e2b6b72013b6': 'оооооченьььь медлеееенннооо...',
    '30e4d208f2cbd8e57201': 'Вот вес и возвращается.',
}

def selected_articles(batch=None):
    articles = json.loads((ROOT/'content/blog/manifest.json').read_text(encoding='utf-8'))['articles']
    if batch is None:
        return articles[:10]
    if batch < 1 or (batch - 1) * 5 >= len(articles):
        raise ValueError('batch outside manifest')
    return articles[(batch-1)*5:batch*5]

def body(text):
    return re.sub(r'\n*blog_cta\(\s*\w+\s*\)\s*$', '', text).strip() + '\n'

def run_writer(args):
    result = subprocess.run([sys.executable, str(WRITER), *args], capture_output=True, text=True, encoding='utf-8')
    if result.returncode and not (args[0] == 'validate' and Path(args[args.index('--output') + 1]).exists() and json.loads(Path(args[args.index('--output') + 1]).read_text(encoding='utf-8')).get('status') == 'manual_review_required'):
        raise RuntimeError(result.stdout + result.stderr)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int)
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    articles = selected_articles(options.batch)
    anchors = {str(article['source_id']): anchor for article, anchor in zip(selected_articles(), ANCHORS)}
    anchors.update(EXTRA_ANCHORS)
    corrections = json.loads((Path(__file__).parent/'corrections.json').read_text(encoding='utf-8'))
    for article in articles:
        identity = str(article['source_id'])
        anchor = anchors[identity]
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
