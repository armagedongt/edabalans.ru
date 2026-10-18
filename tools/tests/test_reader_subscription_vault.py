from tools.editorial_vault import Vault


def test_reader_subscription_is_discovered_and_read_by_existing_editor(tmp_path, monkeypatch):
    for module in ('editorial_bot_adapter', 'editorial_email_adapter', 'editorial_catalog_adapter', 'editorial_graph_adapter'):
        monkeypatch.setattr(f'tools.{module}.discover', lambda api: {})

    class API:
        def request(self, method, path, payload=None):
            assert method == 'GET'
            if path == '/admin/api/public-site/content':
                return {'documents': [{'slug': 'reader-subscription', 'title': 'Блок статьи и подписки'}]}
            if path == '/admin/api/public-site/content/reader-subscription':
                return {'active': {'version': 3, 'markdown': 'Оригинал с настройками', 'title': 'Блок статьи и подписки'}}
            if path == '/admin/api/blog/articles':
                return {'articles': []}
            if path.endswith('/materials'):
                return {'materials': []}
            raise AssertionError(path)

    vault = Vault(tmp_path, API())
    item = vault.discover()['public:reader-subscription']
    assert item['path'] == 'Сайт/Блок статьи и подписки.md'
    assert vault.read(item) == {'version': 3, 'text': 'Оригинал с настройками', 'title': 'Блок статьи и подписки'}
