from dataclasses import replace
import json

import pytest
from sqlalchemy import select

from app.blog_content import BLOG_PUBLIC_URL, load_blog_catalog, validate_blog_catalog, rewrite_blog_links
from app.blog_draft_service import ensure_existing_article, update_text, publish_article
from app.models import ManagedDocumentVersion
from test_blog_draft_authoring import authoring


def test_renamed_article_keeps_published_draft_history_and_internal_key(authoring):
    client, factory = authoring
    article = load_blog_catalog().by_source_id("13277231")
    key = "skolko-vremeni-nuzhno-na-pohudenie"
    assert article.document_key == key and article.slug == "sroki-pohudeniya"
    with factory() as db:
        seed = ensure_existing_article(db, key)
        markdown = ("Опубликованнаяредакция. Второе предложение.\n\n"
                    "[Другая статья](/blog/articles/pochemu-yapontsy-hudye-a-ty-net?utm_source=article#part)")
        draft = update_text(db, slug=key, markdown=markdown,
                            expected_version=seed.version_no, admin="test")
        publish_article(db, slug=key, expected_version=draft.version_no, admin="test")
        update_text(db, slug=key, markdown="Секретныйчерновик. Другое предложение.",
                    expected_version=draft.version_no, admin="test")
        before = [(str(v.id), v.document_key, v.version_no, v.content_hash, v.is_active)
                  for v in db.scalars(select(ManagedDocumentVersion))]

    public = client.get("/blog/sroki-pohudeniya")
    assert public.status_code == 200
    assert "Опубликованнаяредакция" in public.text and "Секретныйчерновик" not in public.text
    assert 'href="/blog/pochemu-yapontsy-hudye?utm_source=article#part"' in public.text
    assert 'href="/blog/articles/' not in public.text
    assert f'href="{BLOG_PUBLIC_URL}/sroki-pohudeniya"' in public.text
    editor = client.get("/admin/api/blog/articles/" + key).json()
    assert editor["article"]["public_slug"] == article.slug
    assert editor["article"]["slug"] == key
    assert editor["article"]["markdown"].startswith("Секретныйчерновик")
    assert len(editor["history"]) == 3
    with factory() as db:
        saved_publication = db.scalar(select(ManagedDocumentVersion).where(
            ManagedDocumentVersion.document_type == "blog-article-published",
            ManagedDocumentVersion.document_key == key,
            ManagedDocumentVersion.is_active.is_(True)))
        assert saved_publication.payload["markdown"] == markdown
        after = [(str(v.id), v.document_key, v.version_no, v.content_hash, v.is_active)
                 for v in db.scalars(select(ManagedDocumentVersion))]
    assert after == before
    for path in ("/blog/articles/" + key, "/articles/" + key, "/blog/" + key):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 404 and "location" not in response.headers


def test_every_article_has_one_final_address_and_service_routes_survive(authoring):
    client, _ = authoring
    catalog = load_blog_catalog()
    sitemap = client.get("/blog/sitemap.xml")
    assert sitemap.status_code == 200 and "/articles/" not in sitemap.text
    for article in catalog.published:
        page = client.get("/blog/" + article.slug)
        assert page.status_code == 200
        assert f'href="{BLOG_PUBLIC_URL}/{article.slug}"' in page.text
        data = json.loads(page.text.split('<script type="application/ld+json">', 1)[1].split('</script>', 1)[0])
        assert data["mainEntityOfPage"] == BLOG_PUBLIC_URL + "/" + article.slug
        assert data["headline"] == article.title
        assert BLOG_PUBLIC_URL + "/" + article.slug + "</loc>" in sitemap.text
        assert 'href="/blog/articles/' not in page.text
        assert 'href="/articles/' not in page.text
        assert client.get("/blog/articles/" + article.document_key, follow_redirects=False).status_code == 404
    assert client.get("/blog/robots.txt").status_code == 200
    assert client.get("/blog/author/sergey-vorontsov").status_code == 200
    assert client.get("/blog/assets/blog.css").status_code == 200
    assert client.get("/jpn", follow_redirects=False).status_code == 404


@pytest.mark.parametrize("slug", ["author", "media", "assets", "reader", "fonts", "drafts", "articles", "favicon-tests"])
def test_new_article_cannot_claim_a_service_segment(slug):
    catalog = load_blog_catalog()
    changed = replace(catalog, articles=(replace(catalog.published[0], slug=slug), *catalog.articles[1:]))
    with pytest.raises(ValueError, match="invalid blog slug"):
        validate_blog_catalog(changed)


def test_saved_article_links_use_final_paths_without_touching_external_sources():
    source = ('<a href="https://blog.похудение-это-есть.рф/articles/skolko-vremeni-nuzhno-na-pohudenie?utm_source=test&amp;x=1#part">A</a>'
              '<a href="/articles/pochemu-yapontsy-hudye-a-ty-net">B</a>'
              '<a href="https://example.org/articles/skolko-vremeni-nuzhno-na-pohudenie">C</a>'
              '<a href="https://pikabu.ru/story/post_13277231">D</a>')
    result = rewrite_blog_links(source, load_blog_catalog())
    assert 'href="/blog/sroki-pohudeniya?utm_source=test&amp;x=1#part"' in result
    assert 'href="/blog/pochemu-yapontsy-hudye"' in result
    assert 'href="https://example.org/articles/skolko-vremeni-nuzhno-na-pohudenie"' in result
    assert 'href="https://pikabu.ru/story/post_13277231"' in result
