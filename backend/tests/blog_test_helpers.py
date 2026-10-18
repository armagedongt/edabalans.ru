from app.blog_content import load_blog_catalog


def public_slug(key):
    catalog = load_blog_catalog()
    article = catalog.by_document_key(key) or catalog.by_slug(key)
    return article.slug if article else key
