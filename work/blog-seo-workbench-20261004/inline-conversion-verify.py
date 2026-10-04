"""Deterministic check of curated assignments and preservation against baseline."""
import json
import re
import subprocess
from app.blog_content import load_blog_catalog, insert_inline_related, render_article_body


def main():
    catalog = load_blog_catalog()
    assert catalog.inline_related_pool_source_ids
    current = json.loads((catalog.content_dir / 'manifest.json').read_text(encoding='utf-8'))
    baseline = json.loads(subprocess.check_output(['git', 'show', '6afb280:content/blog/manifest.json']).decode('utf-8'))
    decisions = []
    for article in catalog.published:
        body, _ = render_article_body(catalog, article)
        rendered = insert_inline_related(catalog, article, body)
        blocks = re.findall(r'<aside class="reader-related">.*?</aside>', rendered)
        slot = article.inline_related
        assert len(blocks) == int(slot is not None), article.source_id
        if slot:
            target = catalog.by_source_id(slot.source_id)
            assert target and slot.source_id in catalog.inline_related_pool_source_ids
            assert slot.source_id != article.source_id
            assert rendered.replace(blocks[0], '') == body
            assert rendered.split(blocks[0])[1].startswith('<h2 id="' + slot.before_heading + '">')
            assert '/articles/' + target.slug not in body
        else:
            assert rendered == body
        decisions.append({'source_id': article.source_id, 'target': slot.source_id if slot else None,
                          'anchor': slot.before_heading if slot else None, 'checks': 'PASS'})
    current.pop('inline_related_pool_source_ids')
    for manifest in [baseline, current]:
        for article in manifest['articles']:
            article.pop('inline_related', None)
    assert baseline == current, 'Unexpected non-inline metadata change'
    assert not subprocess.check_output(['git', 'diff', '6afb280', '--', 'content/blog/articles'])
    print(json.dumps({'baseline_commit': '6afb280', 'pool': catalog.inline_related_pool_source_ids,
                      'coverage': len(decisions), 'assigned': sum(d['target'] is not None for d in decisions),
                      'all_markdown_and_non_inline_metadata_unchanged': True,
                      'decisions': decisions}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
