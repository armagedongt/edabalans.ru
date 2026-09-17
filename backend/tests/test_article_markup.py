import sys
import types
import unittest

try:
    import fastapi  # noqa: F401
except ImportError:
    fastapi_stub = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str = "") -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi_stub.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi_stub

from app.article_markup import markdown_to_article_html, safe_href, safe_image_src, sanitize_article_html


class ArticleMarkupTests(unittest.TestCase):
    def test_note_preserves_paragraphs_inline_formatting_and_safe_links(self) -> None:
        rendered = markdown_to_article_html("> [!NOTE]\n> **Акцент** и [ссылка](https://example.test/a).\n>\n> Второй абзац.")
        self.assertEqual(rendered, '<div class="article-note-accent"><p><strong>Акцент</strong> и <a href="https://example.test/a" target="_blank" rel="noopener">ссылка</a>.</p><p>Второй абзац.</p></div>')
        self.assertEqual(sanitize_article_html(rendered, allow_h1=False, course_semantics=True), rendered)

    def test_note_does_not_turn_author_html_or_unsafe_links_into_code(self) -> None:
        rendered = markdown_to_article_html('> [!NOTE]\n> <script>alert(1)</script> [текст](javascript:alert)')
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertIn('&lt;script&gt;', rendered)

    def test_note_rejects_empty_unknown_and_unsupported_nested_blocks(self) -> None:
        for source in ('> [!NOTE]', '> [!WARNING]\n> Текст', '> [!NOTE] Заголовок\n> Текст', '> [!NOTE]\n> |А|Б|', '> [!NOTE]\n> > Цитата', '> [!NOTE]\n> slider(\n> )'):
            with self.subTest(source=source), self.assertRaises(Exception) as caught:
                markdown_to_article_html(source)
            self.assertEqual(caught.exception.status_code, 422)

    def test_note_preserves_dqs_portion_lists(self) -> None:
        rendered = markdown_to_article_html('> [!NOTE]\n> **Стандартные порции**\n>\n> - 120 г для густых\n> - **250 мл** для жидких')
        self.assertIn('<p><strong>Стандартные порции</strong></p><ul><li>120 г для густых</li><li><strong>250 мл</strong> для жидких</li></ul>', rendered)
        self.assertEqual(sanitize_article_html(rendered, course_semantics=True), rendered)

    def test_plain_quote_stays_plain_quote(self) -> None:
        self.assertEqual(markdown_to_article_html('> Обычная цитата'), '<blockquote>Обычная цитата</blockquote>')

    def test_markdown_table_renders_as_scrollable_course_table(self) -> None:
        source = """| Блюдо | Ккал | Белки, г |
|---|---:|---:|
| Овсянка | 496 | 33,2 |
| **Итого** | **496** | **33,2** |

После таблицы.
"""

        rendered = markdown_to_article_html(source)

        self.assertIn('<div class="article-table-wrap">', rendered)
        self.assertIn('<table class="article-data-table">', rendered)
        self.assertIn("<thead><tr><th>Блюдо</th><th>Ккал</th><th>Белки, г</th></tr></thead>", rendered)
        self.assertIn("<td><strong>Итого</strong></td>", rendered)
        self.assertTrue(rendered.endswith("<p>После таблицы.</p>"))

    def test_markdown_table_rejects_row_with_wrong_column_count(self) -> None:
        source = """| Блюдо | Ккал |
|---|---:|
| Овсянка |
"""

        with self.assertRaisesRegex(Exception, "не совпадает число колонок"):
            markdown_to_article_html(source)

    def test_markdown_link_can_show_square_brackets_around_full_source_title(self) -> None:
        source = r"- [\[Healthy diet — World Health Organization\]](https://example.test/source)"

        rendered = markdown_to_article_html(source)

        self.assertEqual(
            rendered,
            '<ul><li><a href="https://example.test/source" target="_blank" rel="noopener">'
            '[Healthy diet — World Health Organization]</a></li></ul>',
        )

    def test_regular_markdown_link_is_unchanged(self) -> None:
        rendered = markdown_to_article_html("[Источник](https://example.test/source)")

        self.assertEqual(
            rendered,
            '<p><a href="https://example.test/source" target="_blank" rel="noopener">'
            'Источник</a></p>',
        )

    def test_markdown_images_are_lazy_and_decode_asynchronously(self) -> None:
        rendered = markdown_to_article_html("![Подпись](/media/example.webp)")

        self.assertIn('loading="lazy" decoding="async"', rendered)

    def test_network_path_disguised_with_backslash_is_rejected(self) -> None:
        self.assertFalse(safe_image_src(r"/\evil.example/pixel", allow_relative=True))
        self.assertFalse(safe_image_src("/%5cevil.example/pixel", allow_relative=True))
        self.assertFalse(safe_href(r"/\evil.example/page"))


if __name__ == "__main__":
    unittest.main()
