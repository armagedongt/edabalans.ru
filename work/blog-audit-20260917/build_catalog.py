"""Read-only sources -> derived version map, never a second library database."""
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
PRIVATE = ROOT.parent / 'blog-audit-private'

class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.text = []
        self.media = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article' and 'content__blocks' in attrs.get('class', ''):
            self.inside = True
        if self.inside and tag == 'img':
            self.media.append(attrs.get('src') or attrs.get('data-src'))
        if self.inside and tag in ['p', 'h2', 'h3', 'li', 'br']:
            self.text.append('\n')
    def handle_endtag(self, tag):
        if tag == 'article':
            self.inside = False
    def handle_data(self, data):
        if self.inside:
            self.text.append(data)

VC = [
('2213930-izmerenie-protsenta-zhira-v-organizme','2025-09-14'),
('1520842-pomenyat-zhizn-za-140-dnei','2024-09-28'),
('1169131-pohudenie-nachinaetsya-ne-s-pohudeniya','2024-05-12'),
('1159178-vam-ne-nuzhen-pp-kulich','2024-05-05'),
('1137022-ostalos-42-dnya','2024-04-20'),
('1126355-vnimanie-vy-upotreblyaete-ogromnuyu-dozu-e948-kazhdyi-den-dazhe-ne-zamechaya-etogo','2024-04-14'),
('1112254-temperatura-vody-dlya-priema-vnutr','2024-04-06'),
('965046-kak-ne-nabrat-ves-etoi-zimoi','2023-12-24'),
('912323-zhiroszhigayushaya-zona-ne-rabotaet-i-vot-pochemu','2023-11-12'),
('895597-chto-vy-ne-ponimaete-o-formirovanii-privychek','2023-10-29'),
('801045-chem-otlichayutsya-plohie-horoshie-i-bystrye-zavtraki','2023-08-19'),
('793473-my-vse-edim-frukty-ne-pravilno','2023-08-13'),
('752179-8-sovetov-tem-kto-hochet-nachat-begat','2023-07-08'),
('744943-perekusy-hudet-meshayut-ili-pomogayut','2023-07-02'),
('693339-tak-mozhno-pit-vo-vremya-edy-ili-net-a-vsuhomyatku-tochno-vredno','2023-05-13')]

def read_vc(entry):
    path, date = entry
    url = 'https://vc.ru/flood/' + path
    try:
        page = urllib.request.urlopen(url, timeout=30).read().decode('utf-8')
        parser = ArticleParser()
        parser.feed(page)
        title_match = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
        title = html.unescape(re.sub('<[^>]+>', '', title_match[1])) if title_match else path
        text = '\n'.join(x.strip() for x in ''.join(parser.text).splitlines() if x.strip())
        if not text:
            raise ValueError('full article DOM missing')
        return {'source': 'vc.ru', 'external_id': path.split('-')[0], 'title': title, 'text': text, 'url': url, 'published_at': date, 'media': parser.media, 'provenance': 'public SSR article.content__blocks; owner verified profile id1426580', 'family_id': None}
    except Exception as exc:
        return {'url': url, 'error': str(exc)}

vc = json.loads((PRIVATE / 'vc-current.json').read_text(encoding='utf-8')) if (PRIVATE / 'vc-current.json').exists() else list(ThreadPoolExecutor(max_workers=5).map(read_vc, VC))
(PRIVATE / 'vc-current.json').write_text(json.dumps(vc, ensure_ascii=False, indent=2), encoding='utf-8')
library = json.loads((PRIVATE / 'library-snapshot.json').read_text(encoding='utf-8'))
rows = {}
for item in library['items']:
    if item['source'] not in ['pikabu', 'telegraph']:
        continue
    if item.get('editorial_status') == 'removed':
        continue
    if item['source'] == 'pikabu' and item.get('metadata',{}).get('catalog_provenance',{}).get('authorship') != 'own_published':
        continue
    row = {**item, 'url': item['canonical_url'], 'provenance': 'content://item/' + item['id']}
    rows[(row['source'], str(row['external_id']))] = row

local_title_keys=set()
for path in [Path('C:/private/edabalans-content-authoring/pikabu/posts.json'), Path('C:/Users/Segey/Documents/ChatGPT/edabalans.ru/outputs/pikabu-community-research-2026-08-30/raw-source/best-800-posts.json')]:
    for item in json.loads(path.read_text(encoding='utf-8'))['items']:
        if (item.get('author_name') or '').lower() != 'armagedongt':
            continue
        key = ('pikabu', str(item['external_id']))
        if key in rows:
            if key not in local_title_keys:
                rows[key]['title'] = item['title']
                local_title_keys.add(key)
            rows[key]['published_at'] = item.get('published_at') or rows[key].get('published_at')
            continue
        if key not in rows:
            rows[key] = {**item, 'source': 'pikabu', 'url': item['canonical_url'], 'family_id': None, 'provenance': str(path)}

for item in json.loads((PRIVATE / 'telegraph-current.json').read_text(encoding='utf-8')):
    key = ('telegraph', item['path'])
    old_key = next((k for k,r in rows.items() if r['source'] == 'telegraph' and r['url'].rstrip('/') == item['url'].rstrip('/')), None)
    old = rows.pop(old_key) if old_key else {}
    # Fresh public full source; accepted family identity remains authoritative.
    rows[key] = {**old, **item, 'text': item['text_plain'], 'external_id': item['path'], 'provenance': old.get('provenance', 'known account snapshot + public getPage refresh 2026-09-17'), 'family_id': old.get('family_id')}

for item in vc:
    if 'error' not in item:
        rows[('vc.ru', item['external_id'])] = item

records = [r for r in rows.values() if len(r.get('text') or '') >= 3000]
legacy_path = Path('C:/private/edabalans-content-authoring/telegraph/legacy-inventory/legacy-telegraph-inventory-2026-08-26.txt')
taxonomy = {}
for line in legacy_path.read_text(encoding='utf-8-sig').splitlines():
    parts = line.split('\t')
    if len(parts) >= 3:
        taxonomy[parts[2].rstrip('/')] = parts[0]
def normalized(text):
    return ' '.join(re.findall(r'[а-яёa-z0-9]+', text.lower()))
def tokens(row):
    words = normalized(row['text']).split()
    return set(' '.join(words[i:i+5]) for i in range(len(words)-4))

for index, row in enumerate(sorted(records, key=lambda r:(r['source'],str(r['external_id']))), 1):
    row['key'] = f'A{index:03d}'
    row['characters'] = len(row['text'])
    row['text_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
    row['normalized_sha256'] = hashlib.sha256(normalized(row['text']).encode()).hexdigest()
    row['shingles'] = tokens(row)

pairs = []
for index, a in enumerate(records):
    for b in records[index+1:]:
        accepted = bool(a.get('family_id') and a.get('family_id') == b.get('family_id'))
        equal = a['normalized_sha256'] == b['normalized_sha256']
        coverage = len(a['shingles'] & b['shingles']) / max(1, min(len(a['shingles']),len(b['shingles'])))
        if accepted or equal or coverage >= .65:
            pairs.append({'a': a['key'], 'b': b['key'], 'basis': 'accepted_library_family' if accepted else 'equal_normalized_text' if equal else 'candidate_text_overlap', 'shorter_coverage': round(coverage, 3), 'automatic_merge': accepted or equal})

manifest = json.loads((ROOT / 'content/blog/manifest.json').read_text(encoding='utf-8'))
published = {a['source_id']:a for a in manifest['articles']}
blog_shingles = {a['source_id']:tokens({'text':(ROOT/'content/blog/articles'/a['body_file']).read_text(encoding='utf-8')}) for a in manifest['articles']}
by_key = {r['key']:r for r in records}
OUT.joinpath('cards').mkdir(exist_ok=True)
safe = []
for row in sorted(records, key=lambda r:r['key']):
    matches = [p for p in pairs if row['key'] in [p['a'],p['b']]]
    others = [by_key[p['b'] if p['a'] == row['key'] else p['a']] for p in matches]
    blog_matches=[]
    for sid, shingles in blog_shingles.items():
        coverage=len(row['shingles'] & shingles)/max(1,min(len(row['shingles']),len(shingles)))
        if coverage >= .75:
            blog_matches.append({'source_id':sid,'slug':published[sid]['slug'],'coverage':round(coverage,3)})
    already = str(row['external_id']) in published or bool(blog_matches)
    if str(row['external_id']) in published:
        row['title']=published[str(row['external_id'])]['title']
    legacy_category = taxonomy.get(row['url'].rstrip('/'), '')
    service = bool(re.search(r'^(услуги|консультац|запись на|оплата|оферта|анкета)', row['title'], re.I)) or legacy_category == 'Услуги и консультации'
    course = legacy_category in ['Мастер-класс','Новый калории','Курс калории старый']
    service = service or bool(re.search(r'оферта|политика конфиденциальности|фотографии для вашего отеля',row['title'],re.I))
    internal_or_foreign=bool(re.search(r'^(?:сценарий|промт|глобальный промт|тексты шортсы|звонок|пост чужой|алексей золотов|идеи для рекламных|оффер|VSL\b|программа мастер|empty$|ввв$|ууу)|медиакит',row['title'],re.I))
    course=course or bool(re.search(r'^(?:Курс\b|Урок\b|День\b|Дополнительные материалы|Часть\s*#)',row['title'],re.I))
    service=service or internal_or_foreign
    reserve = row['characters'] < 4000
    decision = 'Уже в блоге: новая публикация не нужна' if already else 'Не публиковать автоматически: учебный материал курса' if course else 'Не публиковать как статью: служебный/продающий или посторонний формат' if service else 'Резерв 3000–3999: сначала оценить самостоятельную пользу' if reserve else 'Кандидат: нужна редакторская подготовка и фактчек'
    if row['title'].strip().lower() in ['empty','ууууууу','уууууууу','блиц запасной'] or legacy_category in ['Заметки','empty']:
        decision += '; черновик/заметка, требуется оценка законченности'
    if any(p['basis'] == 'candidate_text_overlap' for p in matches):
        decision += '; пересечение версий требует проверки'
    if row['source'] == 'telegraph' and re.search(r'мастер.класс|день\s*\d|МК\s*\d|введение в', row['title'], re.I):
        decision += '; проверить границу учебного материала'
    record = {k:row.get(k) for k in ['key','source','external_id','url','title','published_at','characters','text_sha256','normalized_sha256','family_id','provenance']}
    record.update(decision=decision, core=not reserve, matching_candidates=[r['key'] for r in others], published=already, legacy_category=legacy_category, exclude_automatic_blog=service or course, blog_matches=blog_matches)
    safe.append(record)
    lines = [f'# {row["key"]} — {row["title"]}', '', f'Статус: ❓ {decision}.', '', f'Полный исходник: [{row["source"]}]({row["url"]}).', '', f'Дата: {row.get("published_at") or "не установлена"}. Объём: {row["characters"]} знаков.', '', f'Provenance: `{row["provenance"]}`. SHA-256 полного текста: `{row["text_sha256"]}`.', '', '## Версии и пересечения', '']
    if not others:
        lines.append('В проверенном корпусе уверенного текстового соответствия не найдено. Это не доказательство отсутствия версии на другой площадке.')
    for match in blog_matches:
        current=published[match['source_id']]
        lines.append(f'- Уже опубликованный блоговый текст: [{current["title"]}](https://blog.похудение-это-есть.рф/articles/{current["slug"]}); покрытие короткой версии {match["coverage"]:.0%}. Это связь с принятым текстом, не новая статья.')
    for p,other in zip(matches,others):
        lines.append(f'- [{other["key"]} — {other["title"]}]({other["key"]}.md): {other["source"]}, {other.get("published_at") or "дата неизвестна"}; {p["basis"]}, покрытие короткой версии {p["shorter_coverage"]:.0%}.')
    lines += ['', '## Основа для подготовки', '', 'Сначала сравнить полный текст и медиа перечисленных версий. Более поздняя дата сама по себе не доказывает лучшую редакцию. Для уже опубликованных девяти материалов приоритет остаётся у согласованного текущего текста блога/мастер-класса.', '', 'Новые статьи этим аудитом не подготовлены к публикации. Здесь нет статуса writer validation/review pass.', '']
    OUT.joinpath('cards',row['key']+'.md').write_text('\n'.join(lines),encoding='utf-8')

summary = {'long_documents':sum(r['core'] for r in safe),'reserve_documents':sum(not r['core'] for r in safe),'by_source':dict(Counter(r['source'] for r in safe)), 'vc_checked':len(vc),'vc_errors':[r for r in vc if 'error' in r], 'duplicate_pairs':len(pairs), 'accepted_or_normalized_equal_pairs':sum(p['automatic_merge'] for p in pairs), 'telegraph_no_matched_pikabu':[r['key'] for r in safe if r['source']=='telegraph' and not any(by_key[k]['source']=='pikabu' for k in r['matching_candidates'])], 'account_list_fresh':False, 'original_article_count':'not yet established: unreviewed semantic overlap and course boundaries'}
OUT.joinpath('catalog.json').write_text(json.dumps({'summary':summary,'articles':safe,'version_pairs':pairs},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines = ['# Карта длинных материалов Сергея — 17.09.2026', '', f'Полные тексты доступны для {summary["long_documents"]} документов от 4000 знаков; ещё {summary["reserve_documents"]} в резерве 3000–3999. Это число документов, **не число оригинальных готовых статей**.', '', 'Проверены все 211 известных страниц Telegraph: изменений относительно локального снимка не найдено. Свежий account getPageList недоступен без токена; новые неизвестные страницы не исключены. Pikabu: серверная библиотека и два локальных корпуса, только автор armagedongt; свежая полнота профиля не подтверждена. vc.ru: 15 ссылок из проверенного публичного профиля.', '', 'Связи accepted_library_family уже приняты Библиотекарем. equal_normalized_text означает одинаковый нормализованный текст, не побайтовое равенство. candidate_text_overlap — **предложение для проверки**, не разрешение склеить статьи.', '', '## Основной корпус (от 4000 знаков)', '', '| Статус | Материал | Условие |', '|---|---|---|']
for row in safe:
    if row['core']:
        lines.append(f'| {"❌ не переносить автоматически" if row["exclude_automatic_blog"] else "✅ версия уже в блоге" if row["published"] else "❓ кандидат"} | [{row["key"]} — {row["title"].replace("|", "/") }](cards/{row["key"]}.md) | {row["source"]}; {row["decision"]} |')
lines += ['', '## Резерв 3000–3999', '', '| Статус | Материал | Условие |','|---|---|---|']
for row in safe:
    if not row['core']:
        lines.append(f'| ❓ резерв | [{row["key"]} — {row["title"].replace("|", "/")}](cards/{row["key"]}.md) | {row["source"]}; {row["characters"]} знаков |')
lines += ['', '## Telegraph без найденного соответствия на Pikabu', '', 'Это «соответствие не найдено в проверенном корпусе», а не безусловное «опубликовано только в Telegraph».', '', ', '.join(f'[{k}](cards/{k}.md)' for k in summary['telegraph_no_matched_pikabu']), '', '## Как дать следующее задание', '', 'Например: «Подготовь A012 и A043; A057 пропускаем; для A086 возьми позднюю версию, но сохрани таблицу из ранней». Каждая новая статья затем проходит full_source, адаптацию, актуальный фактчек и writer validation/review pass.', '']
OUT.joinpath('catalog.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
