# Исследование кода

Проверено на `origin/main` 97b820d.

- Публичный источник блога: `content/blog/manifest.json`, `blog_content.py`, `blog_routes.py`. Он остаётся единственной публичной authority.
- `ManagedDocumentVersion` и `managed_documents.py` уже дают JSON payload, active version, optimistic update, idempotency и retention 20; новая таблица не нужна.
- `auth.py` уже даёт `admin_identity`/`require_admin` и общий 30-дневный admin cookie. Новый login не нужен.
- `article_markup.markdown_to_article_html`, `blog_content.add_heading_anchors`, `toc_html`, `render_blog_component` переиспользуются.
- Принятый 19.09 GitHub Markdown editor Мастер-класса является полезным UI-паттерном, но его Git branch/publish/deploy контракт не подходит DB-пакетам блога.
- В backend пока нет Pillow dependency. Она нужна для полного decode-validation untrusted images; актуальная проверенная версия 12.3.0.
- Owner UI должен работать на same-host `edabalans.ru/blog`; отдельный blog-домен не получает `.edabalans.ru` cookie.
- Inline media атомарно сохраняется с MD, но base64 добавляет около трети объёма и повторяется в версиях. Поэтому это ограниченный test slice, не масштабное решение.
