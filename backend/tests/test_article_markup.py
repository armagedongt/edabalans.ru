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

from app.article_markup import markdown_to_article_html


class ArticleMarkupTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
