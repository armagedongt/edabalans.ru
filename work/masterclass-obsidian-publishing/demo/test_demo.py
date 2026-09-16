import unittest
import json
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
from threading import Thread

from serve_demo import Handler, ThreadingHTTPServer, image_links, render_source, obsidian_spoilers


class FormattingStandTests(unittest.TestCase):
    def test_folded_obsidian_note_becomes_closed_spoiler_without_changing_quotes(self):
        _, body, _ = render_source('# Тест\n\n> [!note]- Подробнее\n> Первая строка\n> продолжается здесь.\n>\n> **Второй абзац.**\n\n> Обычная цитата.\n\nПосле блока.')
        self.assertIn('<details class="article-spoiler">', body)
        self.assertIn('<summary>Подробнее</summary>', body)
        self.assertIn('<p>Первая строка продолжается здесь.</p>', body)
        self.assertIn('<strong>Второй абзац.</strong>', body)
        self.assertIn('<blockquote>Обычная цитата.</blockquote>', body)
        self.assertNotIn(' open', body)
        self.assertIn('</details><blockquote>', body)
        _, escaped, _ = render_source('# Тест\n\n> [!note]- <script>alert(1)</script>\n> <img src=x onerror=alert(1)>')
        self.assertNotIn('<script', escaped)
        self.assertNotIn('<img', escaped)
        fenced = '```md\n> [!note]- Пример\n> Текст\n```'
        self.assertEqual(obsidian_spoilers(fenced), fenced)

    def test_plain_uppercase_note_is_accent_without_heading_and_parenthesis_is_plain_text(self):
        _, body, _ = render_source('# Тест\n\n> [!NOTE] Заголовок спойлера\n> содержание спойлера\n>\n> )\n\nПосле блока.')
        self.assertIn('<div class="article-note-accent">', body)
        self.assertNotIn('Заголовок спойлера', body)
        self.assertIn('<p>содержание спойлера</p>', body)
        self.assertIn('<p>)</p>', body)
        self.assertIn('</div><p>После блока.</p>', body)
        self.assertNotIn(' open', body)

    def test_formatting_comments_tasks_and_rule(self):
        _, body, _ = render_source('# Тест\n\n**Жирный** *Курсив* __Ещё жирный__ _Ещё курсив_ ~~Зачёркнутый~~ ==Подсветка== `**буквально** %%код%%` %%НЕ ПУБЛИКОВАТЬ%%\n\n- [ ] Проверить\n- [x] Готово\n\n---\n\nПосле разделителя.')
        for fragment in ('<strong>Жирный</strong>', '<em>Курсив</em>', '<strong>Ещё жирный</strong>', '<em>Ещё курсив</em>', '<del>Зачёркнутый</del>', '<mark>Подсветка</mark>', '<code>**буквально** %%код%%</code>', '<hr>', 'article-task-negative', 'Нет: ', 'Да: '):
            self.assertIn(fragment, body)
        self.assertNotIn('НЕ ПУБЛИКОВАТЬ', body)
        self.assertNotIn('<input', body)
        self.assertIn('<li class="article-task article-task-negative"><span class="article-status-label">Нет: </span>Проверить</li>', body)
        self.assertIn('<li class="article-task"><span class="article-status-label">Да: </span>Готово</li>', body)

    def test_code_block_preserves_lines_and_html_without_rendering_or_hiding_it(self):
        code = '<script>alert(1)</script>\n<!--literal-->\n%%literal%%\n> [!NOTE]- literal\n)'
        _, body, _ = render_source('# Тест\n\n```text\n' + code + '\n```\n\nПосле кода.')
        self.assertIn('class="article-copy-button"', body)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertIn('&lt;!--literal--&gt;\n%%literal%%', body)
        self.assertNotIn('<script>', body)
        self.assertNotIn('<details', body)
        self.assertIn('</button></div><p>После кода.</p>', body)
        self.assertLess(body.index('</pre>'), body.index('class="article-copy-button"'))

    def test_inline_code_is_not_restored_as_markup_in_link_attributes(self):
        _, body, _ = render_source('# Тест\n\n[Ссылка](https://example.com/`x`) и `<img src=x onerror=alert(1)>`.')
        self.assertNotIn('href="https://example.com/<code>', body)
        self.assertNotIn('<img ', body)
        self.assertIn('<code>&lt;img src=x onerror=alert(1)&gt;</code>', body)

    def test_highlight_and_strike_preserve_nested_emphasis_and_links(self):
        _, body, _ = render_source('# Тест\n\n==**Главное**== ~~*Старое*~~ ***Совместно*** ==[Ссылка](https://example.com/page)==')
        self.assertIn('<mark><strong>Главное</strong></mark>', body)
        self.assertIn('<del><em>Старое</em></del>', body)
        self.assertIn('<strong><em>Совместно</em></strong>', body)
        self.assertIn('<mark><a href="https://example.com/page" target="_blank" rel="noopener">Ссылка</a></mark>', body)

    def test_native_link_callouts_render_safe_placement_groups(self):
        for mode, css in (('', 'stack'), (' В строку', 'row'), (' По центру', 'center')):
            _, body, _ = render_source('# Тест\n\n> [!LINK]' + mode + '\n> [Первая](https://example.com/a)\n>\n> [Вторая](/day-1)')
            self.assertIn('article-actions-' + css, body)
            self.assertIn('href="https://example.com/a"', body)
            self.assertIn('href="/day-1"', body)
            self.assertLess(body.index('Первая'), body.index('Вторая'))
            self.assertNotIn('<blockquote', body)
        for text in ('> [!LINK]\n> [Плохая](javascript:alert(1))',
                     '> [!LINK]\n> [Плохая](//example.com)',
                     '> [!LINK]\n> [Плохая](https:/a)',
                     '> [!LINK]\n> [Плохая](https://example.com/%0afoo)',
                     '> [!LINK]\n> Текст без ссылки', '> [!LINK]',
                     '> [!LINK] Неизвестный режим\n> [Да](/day-1)',
                     '> [!NOTE]+ Открытый\n> Текст'):
            with self.subTest(text=text), self.assertRaises(Exception) as caught:
                render_source('# Тест\n\n' + text)
            self.assertEqual(caught.exception.status_code, 422)
        _, escaped, _ = render_source('# Тест\n\n> [!LINK]\n> [<img src=x onerror=alert(1)>](/day-1)')
        self.assertNotIn('<img ', escaped)
        self.assertIn('&lt;img', escaped)

    def test_simple_table_gets_escaped_labels_without_changing_cell_data(self):
        _, body, _ = render_source('# Тест\n\n| **Название** | Подсказка "X" |\n|---|---|\n| Значение | [Ссылка](https://example.com) |')
        self.assertIn('<th scope="col"><strong>Название</strong></th>', body)
        self.assertIn('<td data-label="Название">Значение</td>', body)
        self.assertIn('data-label="Подсказка &quot;X&quot;"', body)
        self.assertEqual(body.count('>Значение<'), 1)
        self.assertIn('href="https://example.com"', body)

    def test_image_url_keeps_position_but_regular_links_and_code_are_not_images(self):
        source = 'До\n\nhttps://example.com/photo.webp?v=2\n\nПосле\nhttps://example.com/page\n```text\nhttps://example.com/no.png\n```'
        result = image_links(source)
        self.assertIn('До\n\n![Иллюстрация к материалу](https://example.com/photo.webp?v=2)\n\nПосле', result)
        self.assertIn('https://example.com/page', result)
        self.assertIn('```text\nhttps://example.com/no.png\n```', result)
        self.assertEqual(result.count('!['), 1)

    def test_renderer_preserves_basic_semantics_and_contents_has_unique_anchors(self):
        title, body, contents = render_source('# Тест\n\n## Повтор\n\n**Текст** и *слово*.\n\n### Повтор\n\n> Цитата\n\n:::note [Важно]\nПлашка\n:::\n\nhttps://example.com/a.jpg')
        self.assertEqual(title, 'Тест')
        for fragment in ('<strong>Текст</strong>', '<em>слово</em>', '<blockquote>', 'class="editorial-note"', '<img src="https://example.com/a.jpg"'):
            self.assertIn(fragment, body)
        self.assertNotIn('<h1', body)
        self.assertIn('id="section-1"', body)
        self.assertIn('id="section-2"', body)
        self.assertIn('href="#section-1"', contents)
        self.assertIn('href="#section-2"', contents)

    def test_http_stand_exposes_only_allowlisted_routes_and_rejects_writes(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/material') as response:
                self.assertEqual(response.status, 200)
                self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
                self.assertIn("'sha256-", response.headers['Content-Security-Policy'])
                html = response.read().decode()
                self.assertIn('id="masterclass-course-app"', html)
                self.assertIn('configureArticleToc()', html)
            with urlopen(base + '/content/masterclass/course/course.json') as response:
                manifest = json.load(response)
            available = [(day['number'], index, step) for day in manifest['days']
                for index, step in enumerate(day['steps'])
                if not step.get('locked') and not step.get('hidden')]
            self.assertEqual(len(available), 1)
            day_number, position, demo = available[0]
            self.assertEqual((day_number, position, demo['kind']), (1, 0, 'article'))
            for day in manifest['days']:
                for step in day['steps']:
                    if step is not demo:
                        self.assertTrue(step['locked'])
                        self.assertNotIn('contentAsset', step)
            with urlopen(base + '/content/masterclass/source-current/' + demo['contentAsset']) as response:
                material = json.load(response)['pages'][0]
            self.assertEqual(material['title'], demo['contentPageTitle'])
            self.assertIn('<h2', material['rich_html'])
            # Simulate two saved file versions without modifying the author's MD.
            with patch('serve_demo.SOURCE') as saved_source:
                saved_source.read_text.side_effect = ['# Тест\n\nПервая версия.', '# Тест\n\nОбновлённая версия.']
                with urlopen(base + '/content/masterclass/source-current/local-formatting.json') as response:
                    first = response.read().decode()
                with urlopen(base + '/content/masterclass/source-current/local-formatting.json') as response:
                    refreshed = response.read().decode()
                self.assertIn('Первая версия.', first)
                self.assertNotIn('Обновлённая версия.', first)
                self.assertIn('Обновлённая версия.', refreshed)
                self.assertNotIn('Первая версия.', refreshed)
                self.assertEqual(saved_source.read_text.call_count, 2)
            for path in ('/../AGENTS.md', '/.env', '/unknown'):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(base + path)
                self.assertEqual(caught.exception.code, 404)
            from urllib.request import Request
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base + '/material', data=b'test', method='POST'))
            self.assertEqual(caught.exception.code, 501)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
