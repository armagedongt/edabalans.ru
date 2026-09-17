from pathlib import Path
from collections import Counter
import json
import re
import subprocess
import hashlib

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
manifest=json.loads((ROOT/'content/blog/manifest.json').read_text(encoding='utf-8'))
original=json.loads(subprocess.check_output(['git','show','7c7f434:content/blog/manifest.json'],cwd=ROOT).decode())
active=set();before=set();rows=[]
for old,new in zip(original['articles'],manifest['articles']):
    body=(ROOT/'content/blog/articles'/new['body_file']).read_text(encoding='utf-8')
    old_names=set(old['media']+[old['hero']['file'],old['card']['file']])
    new_names=set(re.findall(r'/blog/media/([^)]+)',body)+[new['hero']['file'],new['card']['file']])
    before.update(old_names);active.update(new_names)
    rows.append({'source_id':new['source_id'],'title':new['title'],'cta':new['cta'],'related':new['related_source_ids'],'before_bytes':sum((ROOT/'content/blog/media'/x).stat().st_size for x in old_names),'after_bytes':sum((ROOT/'content/blog/media'/x).stat().st_size for x in new_names),'active_media':sorted(new_names),'body_sha256':hashlib.sha256(body.encode()).hexdigest()})
report={'before_bytes':sum((ROOT/'content/blog/media'/x).stat().st_size for x in before),'after_bytes':sum((ROOT/'content/blog/media'/x).stat().st_size for x in active),'articles':rows,'unchanged_original_urls':True,'tilda_image_hotlinks':0,'external_video':'Dropbox link remains in Japanese article; not downloaded or changed'}
(OUT/'active-media-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
catalog=json.loads((OUT/'catalog.json').read_text(encoding='utf-8'))
eligible={r['key']:r for r in catalog['articles'] if r['core'] and not r['exclude_automatic_blog']}
parent={k:k for k in eligible}
def root(k):
    while parent[k]!=k:
        k=parent[k]
    return k
for pair in catalog['version_pairs']:
    a,b=pair['a'],pair['b']
    if pair['shorter_coverage']>=.9 and a in eligible and b in eligible:
        parent[root(b)]=root(a)
groups={}
for k,row in eligible.items():
    groups.setdefault(root(k),[]).append(row)
lines=['# Рабочие группы версий и выбор основы','','Высокое текстовое покрытие (≥90%) объединено **только для редакционного просмотра**. Это не новые accepted families Библиотекаря и не доказанное число оригинальных статей. Пересечения 65–89% остаются отдельно в catalog.json.','',f'Основной корпус: {len(eligible)} документов после исключения учебных, служебных и посторонних материалов; рабочий список — {len(groups)} групп/одиночных кандидатов. Уже опубликованные статьи не следует публиковать повторно.','','| Группа | Версии в хронологическом порядке | Предлагаемая основа / решение |','|---|---|---|']
for index,group in enumerate(sorted(groups.values(),key=lambda g:min(x['key'] for x in g)),1):
    ordered=sorted(group,key=lambda r:str(r.get('published_at') or ''))
    known=any(r['published'] for r in group)
    links=' → '.join(f'[{r["key"]} {r["source"]} {str(r.get("published_at") or "дата неизвестна")[:10]}](cards/{r["key"]}.md)' for r in ordered)
    latest=ordered[-1]
    basis='Сохранить принятую текущую версию блога; повторная публикация не нужна' if known else f'[{latest["key"]} — {latest["title"].replace("|","/")}](cards/{latest["key"]}.md): поздняя версия — первая для сравнения, не автоматически лучшая'
    if len(group)==1:
        basis=f'[{latest["title"].replace("|","/")}](cards/{latest["key"]}.md): один найденный полный исходник; проверить пользу, актуальность и отсутствие незамеченного дубля'
        if known:
            basis='Уже опубликован: повторно не готовить'
    lines.append(f'| V{index:03d} | {links} | {basis} |')
lines+=['','## Что можно решить без владельца','','Дата устанавливает порядок публикаций. Высокое совпадение показывает вероятные версии одного текста. Текущий принятый блоговый текст защищён. Оферты, политика, старые услуги, материалы про отель не входят в питательный блог.','','## Где требуется решение Сергея','','Публиковать ли учебные главы отдельно и насколько раскрывать платный материал; выбирать ли обновлённый тезис, если версии содержательно расходятся; оставлять ли личные истории/старые новости и сезонные поводы. Для кандидатов со скрытым title «empty» или черновыми названиями нужны законченный авторский исходник и явный выбор.','','Материал не становится publish-ready от объёма или даты: нужен отдельный writer pass.','']
(OUT/'version-groups.md').write_text('\n'.join(lines),encoding='utf-8')
stats={'core_documents':catalog['summary']['long_documents'],'reserve_documents':catalog['summary']['reserve_documents'],'core_by_source':dict(Counter(r['source'] for r in catalog['articles'] if r['core'])),'excluded_core_documents':sum(r['core'] and r['exclude_automatic_blog'] for r in catalog['articles']),'eligible_documents_before_semantic_review':len(eligible),'provisional_groups':len(groups),'provisional_not_publish_ready':True,'active_media_before_bytes':report['before_bytes'],'active_media_after_bytes':report['after_bytes']}
stats['provisional_groups_with_existing_blog_version']=sum(any(r['published'] for r in g) for g in groups.values())
stats['provisional_new_groups']=sum(not any(r['published'] for r in g) for g in groups.values())
(OUT/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False))
