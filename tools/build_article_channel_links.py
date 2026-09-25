"""Read existing private author sources; derive article links without editing channels.

Private outputs contain Telegram identifiers and must never be committed. Public
metadata is written only by the registry builder from reviewed supplements.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = re.compile(r'https?://[^\s<>"\[\]]+')


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def url_key(url):
    parts = urlsplit(html.unescape(url).rstrip('.,);'))
    host = (parts.hostname or '').lower().removeprefix('www.').encode('idna').decode()
    path = unquote(parts.path).rstrip('/')
    if host == 'pikabu.ru' and re.search(r'_\d+$', path):
        return 'pikabu:' + path.rsplit('_', 1)[1]
    if host == 'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai':
        path = path.replace('/intensiv_old/tpost/', '/intensiv/tpost/')
    # Only known publication hosts have non-identity query parameters.
    query = '' if host in {'pikabu.ru', 'telegra.ph', 'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai', 'blog.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai'} else parts.query
    return host + path + ('?' + query if query else '')


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value))).strip()


def shingles(text):
    words = re.findall(r'[а-яёa-z0-9]+', plain(text).lower())
    return {' '.join(words[i:i+5]) for i in range(max(0, len(words)-4))}


class PostParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.title = []
        self.body = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        classes = attr.get('class', '').split()
        active = self.stack[-1][1] if self.stack else None
        if 'js-feed-post-title' in classes:
            active = 'title'
        if 'js-feed-post-text' in classes:
            active = 'body'
        if active == 'body' and tag == 'a' and attr.get('href'):
            self.links.append(attr['href'])
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append((tag, active))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1][1] in {'title','body'}:
            getattr(self, self.stack[-1][1]).append(data)


def fetch_post(url):
    try:
        with urlopen(url, timeout=25) as response:
            raw = response.read()
            final = response.url
        parser = PostParser()
        parser.feed(raw.decode('utf-8'))
        body = plain(' '.join(parser.body))
        if not body:
            raise ValueError('No js-feed-post-text content')
        return {'source':'tilda_intensive', 'catalog_id':'tilda-post:'+url.split('/tpost/')[1].split('-')[0],
                'headline':plain(' '.join(parser.title)), 'source_url':url, 'resolved_url':final,
                'text_plain':body, 'links':parser.links, 'html_sha256':hashlib.sha256(raw).hexdigest(),
                'snapshot_status':'full_text_read', 'raw_html':raw.decode('utf-8')}
    except Exception as error:
        return {'source_url':url, 'snapshot_status':'unavailable', 'error':str(error)}


def library_call(name, arguments):
    token = os.environ['EDABALANS_KNOWLEDGE_TOKEN']
    request = Request('https://edabalans.ru/mcp/',
        data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call',
                         'params':{'name':name,'arguments':arguments}}).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
                 'Accept':'application/json, text/event-stream'})
    with urlopen(request,timeout=45) as response:
        payload = json.loads(response.read())
    if 'error' in payload:
        raise RuntimeError('Knowledge API error: '+str(payload['error']))
    result = payload['result']
    if result.get('isError'):
        raise RuntimeError('Knowledge tool error: '+str(result.get('content')))
    if 'structuredContent' in result:
        return result['structuredContent']
    return json.loads(next(x['text'] for x in result['content'] if x['type']=='text'))


def sync_navigation(result, registry, output):
    key = 'article-family-routing'
    search = library_call('search_knowledge', {'query':key,'limit':100})
    found = [x for x in search.get('results',[]) if x.get('uri')=='knowledge://resource/'+key]
    version = 0
    if found:
        current = library_call('read_knowledge', {'uri':'knowledge://resource/'+key})
        version = current.get('version', 0)
    snapshot = {**result,'article_families':registry['canonical_blog']+registry['deferred'],
                'authority':'Derived navigation snapshot; Git registry owns article decisions. Source bodies are not copied.'}
    text = json.dumps(snapshot,ensure_ascii=False,sort_keys=True)
    saved = library_call('register_knowledge_resource', {
        'resource_key':key,'title':'Статьи: каноны блога, канал, старый интенсив и рассылки',
        'contour':'editorial','resource_kind':'article_navigation','role':'derived','state':'current',
        'storage_kind':'database','canonical_uri':'repo://content/author-voice/source-selection/article-source-registry.json',
        'owner_module':'platform.content','access_level':'internal','text':text,
        'provenance':{'inputs':result['inputs'],'collection':'2026-09-25','generator':'tools/build_article_channel_links.py'},
        'created_by':'codex-article-library','expected_version':version,
        'metadata':{'summary':result['summary'],'source_bodies_copied':False,'automatic_channel_edits':False}})
    readback = library_call('read_knowledge', {'uri':'knowledge://resource/'+key})
    # Server payload uses text in the latest version; verify the returned body,
    # not just a successful HTTP response.
    actual = readback.get('text')
    if actual != text:
        raise RuntimeError('Knowledge readback did not match navigation snapshot')
    receipt = {'uri':'knowledge://resource/'+key,'status':'navigation_registered',
               'version':saved.get('version'),'sha256':hashlib.sha256(text.encode()).hexdigest(),
               'family_relations':'candidates_preserved_not_promoted','channel_edits':0}
    (output/'library-sync-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refresh-tilda', action='store_true')
    parser.add_argument('--sync-library', action='store_true', help='Register internal navigation metadata; never edits messages')
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Telegram outputs must be outside the repository')
    output.mkdir(parents=True, exist_ok=True)
    cards_path = args.private_root / 'working/author-content-cards.jsonl'
    channel_path = args.private_root / 'working/telegram-channel.jsonl'
    bot_path = args.private_root / 'originals/production/bot-constructor.jsonl'
    post_catalog_path = args.private_root / 'working/unified-post-catalog/catalog.jsonl'
    cards = read_rows(cards_path)
    channel = read_rows(channel_path)
    bots = read_rows(bot_path)
    post_catalog = read_rows(post_catalog_path)
    post_by_external = {r['external_id']:r for r in post_catalog if r.get('external_id')}
    feed_path = output / 'tilda-intensive-snapshot.jsonl'
    if args.refresh_tilda or not feed_path.exists():
        handoff = (ROOT/'work/free-intensive-rebuild/handoff/03-source-and-program-handoff.md').read_text(encoding='utf-8')
        urls = sorted(set(re.findall(r'https://[^\s<>]+/tpost/[^\s<>]+', handoff)))
        with ThreadPoolExecutor(max_workers=4) as pool:
            pages = list(pool.map(fetch_post, urls))
        feed_path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in pages),encoding='utf-8')
    pages = read_rows(feed_path)
    sources = cards + [x for x in pages if x['snapshot_status']=='full_text_read']
    registry = json.loads((ROOT/'content/author-voice/source-selection/article-source-registry.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT/'content/blog/manifest.json').read_text(encoding='utf-8'))
    families = registry['canonical_blog'] + registry['deferred']
    by_url = defaultdict(set)
    family_by_id = {f['family_id']:f for f in families}
    for family in families:
        for member in family['members']:
            if member.get('url'):
                by_url[url_key(member['url'])].add(family['family_id'])
    for article in manifest['articles']:
        prov = article.get('source_provenance') or {}
        for url in (prov.get('urls') or []) + ([prov['url']] if prov.get('url') else []):
            by_url[url_key(url)].add('blog:'+article['slug'])
    # Independently catalog old site sources, with no length cutoff and no
    # automatic publication approval inferred from a publicly accessible URL.
    source_index = {}
    for source in sources:
        if not source.get('source_url'):
            continue
        key = url_key(source['source_url'])
        source_index.setdefault(key, source)
        if source['source'] in {'tilda_site','tilda_intensive'} and not by_url[key]:
            fid = 'deferred:'+source['catalog_id']
            by_url[key].add(fid)
            family_by_id[fid] = {'family_id':fid,'title':source['headline'],'disposition':'deferred'}

    occurrences = []
    for kind, rows in [('telegram_channel',channel),('bot_template',bots)]:
        for row in rows:
            text = row.get('text_content',row.get('body_source',''))
            post_card = post_by_external.get(row.get('external_id',row.get('code')), {})
            links = URL.findall(text)
            block_locations = defaultdict(set)
            for block in row.get('blocks') or []:
                block_links = URL.findall(block.get('text') or '')
                for entity in block.get('entities') or []:
                    target = entity.get('href') or entity.get('url')
                    if target:
                        links.append(target)
                        block_links.append(target)
                for target in block_links:
                    block_locations[url_key(target)].add(block.get('message_id'))
            if row.get('cta_url'):
                links.append(row['cta_url'])
            for url in sorted(set(html.unescape(x).rstrip('.,);') for x in links)):
                key = url_key(url)
                targets = sorted(by_url.get(key, []))
                if not targets and not key.startswith(('pikabu:', 'telegra.ph/', 'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/')):
                    continue
                canon = [family_by_id[f]['canonical']['url'] for f in targets if family_by_id[f].get('canonical')]
                occurrences.append({'source':kind, 'source_id':row.get('external_id',row.get('code')),
                    'message_url':row.get('canonical_url'), 'title':row.get('title'),
                    'post_catalog_family_id':post_card.get('family_id'),
                    'post_catalog_assignment':(post_card.get('control') or {}).get('family_assignment'),
                    'physical_message_ids':sorted(x for x in block_locations.get(key,[]) if x is not None),
                    'hash_scope':'grouped_publication_text' if kind=='telegram_channel' else 'template_body_source',
                    'published_at':row.get('published_at'), 'template_id':row.get('id') if kind=='bot_template' else None,
                    'scenario':row.get('origin_scenario_name'), 'old_url':url, 'family_ids':targets,
                    'relation':'references_article', 'new_url':canon[0] if len(targets)==1 and len(canon)==1 else None,
                    'status':'mapped_recheck_before_apply' if len(targets)==1 and len(canon)==1 else 'review_required',
                    'source_text_sha256':hashlib.sha256(text.encode()).hexdigest()})

    articles = [s for s in sources if s['source'] in {'pikabu','telegraph','tilda_site','tilda_intensive'} and len(s.get('text_plain',''))>=1500]
    article_sets = [(s,shingles(s['text_plain'])) for s in articles]
    channel_sets = [(r,shingles(r.get('text_content') or '')) for r in channel if len(r.get('text_content') or '')>=1200]
    overlaps = []
    for row in channel:
        text = row.get('text_content') or ''
        if len(text)<1200:
            continue
        words = shingles(text)
        for source, other in article_sets:
            common = len(words & other)
            coverage = common/max(1,min(len(words),len(other)))
            if common < 80 or coverage < .55:
                continue
            exact = plain(text)==plain(source['text_plain'])
            overlaps.append({'message_id':row['external_id'],'message_url':row['canonical_url'],
                'article_url':source['source_url'],'article_title':source['headline'],
                'family_ids':sorted(by_url.get(url_key(source['source_url']),[])),
                'relation':'normalized_text_match' if exact else 'semantic_overlap_candidate',
                'coverage_shorter':round(coverage,3),'shared_5grams':common,
                'coverage_message':round(common/max(1,len(words)),3),
                'coverage_article':round(common/max(1,len(other)),3),
                'status':'review_required','content_form':'long_material_in_channel'})

    candidates = []
    twelve = 'Prostejshie-12-izmenenij-v-vashej-zhizni-08-11'
    for source in sources:
        is_tilda = source['source'] in {'tilda_site','tilda_intensive'}
        is_bot = source['source']=='bot_constructor' and len(source.get('text_plain',''))>=3000
        is_twelve = twelve in (source.get('source_url') or '')
        if not (is_tilda or is_bot or is_twelve):
            continue
        if is_tilda and source['source']=='tilda_site' and (source.get('context') or {}).get('site_page_kind') not in {'article_or_editorial','free_intensive_lesson'}:
            continue
        source_url = source.get('source_url')
        key = url_key(source_url) if source_url else None
        words = shingles(source.get('text_plain',''))
        matches = []
        for other, grams in article_sets:
            if other is source or other['source'] not in {'pikabu','telegraph'}:
                continue
            common = len(words & grams)
            coverage = common/max(1,min(len(words),len(grams)))
            if common >=80 and coverage>=.55:
                matches.append({'platform':other['source'],'url':other['source_url'],'coverage_shorter':round(coverage,3),'relation':'overlap_candidate'})
        channel_matches = []
        for message, grams in channel_sets:
            common = len(words & grams)
            coverage = common/max(1,min(len(words),len(grams)))
            if common >=80 and coverage>=.55:
                channel_matches.append({'message_url':message['canonical_url'],'message_id':message['external_id'],
                                        'coverage_shorter':round(coverage,3),'relation':'overlap_candidate'})
        refs = [x for x in occurrences if key and url_key(x['old_url'])==key]
        family_ids = sorted(by_url.get(key,[]))
        known_members = [m for f in family_ids for m in family_by_id[f].get('members',[])]
        pikabu_seen = any(x['platform']=='pikabu' for x in matches) or any(m['source']=='pikabu' for m in known_members)
        channel_seen = bool(channel_matches)
        status = 'publication_evidence_found' if pikabu_seen or channel_seen else 'priority_first_pikabu_review'
        if is_bot:
            status = 'bot_material_editorial_review'
        if source['source']=='tilda_site' and (source.get('context') or {}).get('site_page_kind')=='free_intensive_lesson':
            status = 'intensive_container_split_review'
        if source['catalog_id']=='tilda-post:5kegfp3o71':
            status = 'personal_examples_access_review'
        candidates.append({'source_id':source['catalog_id'],'title':source['headline'],'source':source['source'],
            'url':source_url,'characters':len(source.get('text_plain','')),'family_ids':family_ids,
            'known_pikabu_family_members':[m['url'] for m in known_members if m['source']=='pikabu'],
            'priority':status,'blog_status':'published' if any(f.startswith('blog:') for f in by_url.get(key,[])) else 'deferred_for_review',
            'pikabu_matches':matches,'channel_text_matches':channel_matches,'references':refs,
            'novelty':'not_found_in_snapshot' if not pikabu_seen and not channel_seen else 'overlap_requires_comparison',
            'delivery_evidence':'template_only_not_proof_of_send' if source['source']=='bot_constructor' else None,
            'access_review':'required_before_blog_publication',
            'source_text_sha256':hashlib.sha256(source.get('text_plain','').encode()).hexdigest()})

    long_channel = [{'source_id':r['external_id'],'url':r['canonical_url'],'title':r['title'],
        'characters':len(r['text_content']),'content_form':'long_material','platform':'telegram',
        'family_candidates':sorted({f for x in overlaps if x['message_id']==r['external_id'] for f in x['family_ids']}),
        'review_status':'candidate_long_form_not_length_only_approval'} for r in channel if len(r.get('text_content') or '')>=3000]

    summary = {'channel_publications_scanned':len(channel),'bot_templates_scanned':len(bots),
        'tilda_posts':len([x for x in pages if x['snapshot_status']=='full_text_read']),
        'tilda_fetch_failures':len([x for x in pages if x['snapshot_status']!='full_text_read']),
        'link_occurrences':len(occurrences),'mapped_to_blog':sum(bool(x['new_url']) for x in occurrences),
        'mapped_channel_links':sum(bool(x['new_url']) and x['source']=='telegram_channel' for x in occurrences),
        'channel_article_overlap_candidates':len(overlaps),'candidate_sources':len(candidates),
        'long_channel_materials':len(long_channel),
        'priority_candidates':sum(x['priority']=='priority_first_pikabu_review' for x in candidates)}
    linked_source_ids = {x['source_id'] for x in occurrences}
    post_memberships = [{'post_catalog_id':r['id'],'post_family_id':r['family_id'],
        'assignment':(r.get('control') or {}).get('family_assignment'),'source_url':r.get('source_url'),
        'external_id':r['external_id'],'article_family_ids':sorted(by_url.get(url_key(r['source_url']),[])) if r.get('source_url') else []}
        for r in post_catalog if r.get('family_id') and (r.get('external_id') in linked_source_ids or
        (r.get('source_url') and by_url.get(url_key(r['source_url']))))]
    result = {'schema_version':1,'summary':summary,
        'coverage':{'channel_last_message':max(x['published_at'] for x in channel),'bot_snapshot':'2026-08-25',
                    'novelty_limit':'No match in saved corpus does not prove never published; template does not prove delivery.'},
        'inputs':[{ 'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [cards_path,channel_path,bot_path,feed_path,post_catalog_path]],
        'existing_post_memberships':post_memberships,
        'link_occurrences':occurrences,'channel_article_overlaps':overlaps,'publication_candidates':candidates,
        'long_channel_materials':long_channel}
    (output/'article-channel-links.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    labels = {'publication_evidence_found':'Есть пересечение с опубликованным; сравнить версии',
              'priority_first_pikabu_review':'Приоритет: проверить первую публикацию на Pikabu',
              'bot_material_editorial_review':'Содержательный шаблон бота: редакторский разбор',
              'intensive_container_split_review':'Страница дня: выделить самостоятельные статьи',
              'personal_examples_access_review':'Клиентские дневники: проверить права',
              'published':'Уже в блоге','deferred_for_review':'На разбор'}
    lines=['# Статьи: канал, старый интенсив и рассылки','',
           'Приватная производная карта существующих источников. Сообщения и рассылки не изменены.','',
           '## Сводка','',*['- '+k+': '+str(v) for k,v in summary.items()],'',
           'Сходство — кандидат на сравнение. Анонс доказывает ссылку, но не публикацию полного текста. Шаблон бота не доказывает отправку. Отсутствие совпадений ограничено датой снимка.','',
           '## Материалы старого интенсива, сайта и бота','',
           '| Материал | Источник | Блог | Pikabu / канал |','|---|---|---|---|']
    for c in candidates:
        label=c['title'].replace('|','/')
        link=f'[{label}]({c["url"]})' if c['url'] else label+' (`'+c['source_id']+'`)'
        lines.append(f'| {link} | {c["source"]} | {labels[c["blog_status"]]} | {labels[c["priority"]]} |')
    lines += ['', '## Ссылки, сопоставленные с каноном блога','', '| Где | Старая ссылка | Канон |','|---|---|---|']
    for x in occurrences:
        if x['new_url']:
            location=f'[{x["source_id"]}]({x["message_url"]})' if x['message_url'] else '`'+x['source_id']+'`'
            lines.append(f'| {location} | [источник]({x["old_url"]}) | [блог]({x["new_url"]}) |')
    lines += ['', '## Полные и частичные версии в канале: очередь сравнения','', '| Канал | Статья | Покрытие короткого текста |','|---|---|---|']
    for x in overlaps:
        lines.append(f'| [пост]({x["message_url"]}) | [{x["article_title"].replace("|","/")}]({x["article_url"]}) | {x["coverage_shorter"]:.0%} |')
    (output/'ARTICLE_CHANNEL_MAP.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    priority_lines = ['# Приоритетные кандидаты на первую публикацию в Pikabu','',
        'Это очередь проверки по сохранённому корпусу, а не доказательство отсутствия старой публикации. '+
        'Канал проверен по 25.07.2026; даты рассылки по шаблону неизвестны. Две версии дневника питания требуют совместного сравнения.','',
        '| Материал | Уже где-то анонсировался? | Следующее действие |','|---|---|---|']
    for c in candidates:
        if c['priority']!='priority_first_pikabu_review':
            continue
        channels = sorted({x['message_url'] for x in c['references'] if x['message_url']})
        bot_count = sum(x['source']=='bot_template' for x in c['references'])
        evidence = ', '.join('[канал]('+u+')' for u in channels) or 'Анонс в снимке канала не найден'
        if bot_count:
            evidence += f'; шаблонов бота: {bot_count}'
        action = 'Проверить свежие публикации и подготовить Markdown'
        if 'sgpfzdvvy1' in c['source_id']:
            action = 'Сначала проверить старые численные утверждения; не менять фактуру без решения автора'
        priority_lines.append(f'| [{c["title"]}]({c["url"]}) | {evidence} | {action} |')
    (output/'PRIORITY_PIKABU.md').write_text('\n'.join(priority_lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if args.sync_library:
        sync_navigation(result, registry, output)


if __name__ == '__main__':
    main()
