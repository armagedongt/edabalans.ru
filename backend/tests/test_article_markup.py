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
    def test_ordered_recipe_steps_continue_after_photo_and_paragraph(self) -> None:
        source = '1. Первый шаг\n2. Второй шаг\n\nКомментарий.\n\n![Варка](/course-assets/masterclass/media/rice.jpg)\n\n3. Третий шаг\n4. Четвёртый шаг'
        rendered = markdown_to_article_html(source)
        self.assertIn('<ol><li>Первый шаг</li><li>Второй шаг</li></ol>', rendered)
        self.assertIn('<ol start="3"><li>Третий шаг</li><li>Четвёртый шаг</li></ol>', rendered)
        self.assertEqual(sanitize_article_html(rendered, course_semantics=True), rendered)

    def test_ordered_list_start_does_not_enable_other_attributes_or_unsafe_values(self) -> None:
        self.assertEqual(sanitize_article_html('<ol start="6" onclick="bad()" reversed><li>Шаг</li></ol>'), '<ol start="6"><li>Шаг</li></ol>')
        for value in ('0', '-1', '1.5', 'javascript:bad()', '100000'):
            with self.subTest(value=value):
                rendered = sanitize_article_html(f'<ol start="{value}"><li>Шаг</li></ol>')
                self.assertEqual(rendered, '<ol><li>Шаг</li></ol>')

    def test_recipe_roles_render_readonly_marks_with_accessible_states_in_source_order(self) -> None:
        source = """**Роль в конструкторе:**

- [x] Белок
- [ ] Гарнир
- [ ] Объём
- [X] Вкус
- [x] Сочность
- [ ] Топпинги
"""
        rendered = markdown_to_article_html(source)
        self.assertIn('<ul class="article-recipe-roles">', rendered)
        self.assertEqual(rendered.count('class="article-role-check article-role-checked"'), 3)
        self.assertEqual(rendered.count('class="article-role-check"'), 3)
        for label, status in (("Белок", "Есть"), ("Гарнир", "Нет"), ("Объём", "Нет"),
                              ("Вкус", "Есть"), ("Сочность", "Есть"), ("Топпинги", "Нет")):
            visual_class = "article-role-check article-role-checked" if status == "Есть" else "article-role-check"
            self.assertIn(
                f'<li><span class="{visual_class}"></span>'
                f'<span class="article-role-status">{status}: </span>{label}</li>', rendered
            )
        self.assertLess(rendered.index("Белок</li>"), rendered.index("Гарнир</li>"))
        self.assertLess(rendered.index("Гарнир</li>"), rendered.index("Объём</li>"))
        self.assertLess(rendered.index("Объём</li>"), rendered.index("Вкус</li>"))
        self.assertLess(rendered.index("Вкус</li>"), rendered.index("Сочность</li>"))
        self.assertLess(rendered.index("Сочность</li>"), rendered.index("Топпинги</li>"))
        self.assertNotIn("<input", rendered)
        self.assertEqual(sanitize_article_html(rendered, course_semantics=True), rendered)

    def test_unrelated_lists_do_not_become_recipe_role_grids(self) -> None:
        role_items = "- [x] Белок\n- [ ] Гарнир\n- [ ] Объём\n- [x] Вкус\n- [x] Сочность\n- [ ] Топпинги"
        for source in (
            role_items,
            "**Роль в конструкторе:**\n\nДругой абзац.\n\n" + role_items,
            "**Роль в конструкторе:**\n\n" + role_items.replace("Белок", "Протеин"),
            "**Роль в конструкторе:**\n\n" + role_items + "\n- [x] Дополнение",
            "**Роль в конструкторе:**\n\n" + role_items.replace("- [x] Белок\n- [ ] Гарнир", "- [ ] Гарнир\n- [x] Белок"),
            "- Купить рис\n- Отварить рис",
            "1. [x] Сделать задание\n2. [ ] Проверить задание",
        ):
            with self.subTest(source=source):
                rendered = markdown_to_article_html(source)
                self.assertNotIn("article-recipe-roles", rendered)
                self.assertNotIn("article-role-status", rendered)
        self.assertEqual(markdown_to_article_html("- [x] Сделать задание"), '<ul><li>[x] Сделать задание</li></ul>')

    def test_dessert_role_uses_one_readonly_mark_and_preserves_owner_emoticon(self) -> None:
        source = "**Роль в конструкторе:**\n\n- [x] Десерт ¯\\_(ツ)_/¯"
        rendered = markdown_to_article_html(source)
        self.assertIn('<ul class="article-recipe-roles">', rendered)
        self.assertEqual(rendered.count('class="article-role-check article-role-checked"'), 1)
        self.assertIn('Десерт ¯\\_(ツ)_/¯</li>', rendered)
        self.assertNotIn('[x]', rendered)
        self.assertNotIn('<input', rendered)
        self.assertEqual(sanitize_article_html(rendered, course_semantics=True), rendered)
        for unrelated in (
            '- [x] Десерт ¯\\_(ツ)_/¯',
            source + '\n- [x] Белок',
            '**Роль в конструкторе:**\n\n- [x] Десерт <script>alert(1)</script>',
        ):
            with self.subTest(source=unrelated):
                self.assertNotIn('article-recipe-roles', markdown_to_article_html(unrelated))

    def test_role_sanitizer_keeps_only_closed_classes_and_never_enables_forms(self) -> None:
        rendered = sanitize_article_html(
            '<ul class="article-recipe-roles" onclick="bad()"><li>'
            '<span class="article-role-check article-role-checked" onclick="bad()" '
            'tabindex="0" role="checkbox" aria-checked="true"></span>'
            '<span class="article-role-status">Есть: </span>Белок'
            '<input checked type="checkbox" onchange="bad()">'
            '<form action="https://example.test"><button type="submit">Отправить</button></form>'
            '</li></ul>', course_semantics=True,
        )
        self.assertIn('class="article-recipe-roles"', rendered)
        self.assertIn('class="article-role-check article-role-checked"', rendered)
        for unsafe in ("onclick", "onchange", "tabindex", "aria-checked", 'role="', "<input", "<form", 'type="submit"'):
            self.assertNotIn(unsafe, rendered)
        self.assertNotIn('class=', sanitize_article_html('<span class="article-role-check arbitrary">Есть</span>', course_semantics=True))

    def test_source_strikethrough_preserves_author_words_and_emphasis(self) -> None:
        rendered = markdown_to_article_html('В госпитале ~~были **белые люди**~~ поставляли рис.')
        self.assertEqual(rendered, '<p>В госпитале <del>были <strong>белые люди</strong></del> поставляли рис.</p>')

    def test_strikethrough_does_not_activate_raw_html_or_unsafe_attributes(self) -> None:
        rendered = markdown_to_article_html('~~<img src=x onerror=alert(1)>~~')
        self.assertEqual(rendered, '<p><del>&lt;img src=x onerror=alert(1)&gt;</del></p>')
        self.assertEqual(sanitize_article_html('<del onclick="alert(1)">слова</del>'), '<del>слова</del>')

    def test_unclosed_and_escaped_strikethrough_stay_literal(self) -> None:
        self.assertEqual(markdown_to_article_html('~~Не закрыто'), '<p>~~Не закрыто</p>')
        self.assertEqual(markdown_to_article_html(r'\~\~буквально\~\~ и ~~зачёркнуто~~'), '<p>~~буквально~~ и <del>зачёркнуто</del></p>')

    def test_escaped_multiplication_preserves_formula_and_bold(self) -> None:
        source = r"**(Ваш вес \* X ) - (Ваш вес \* текущий % жира) = кг**"
        rendered = markdown_to_article_html(source)
        self.assertEqual(
            sanitize_article_html(rendered),
            '<p><strong>(Ваш вес * X ) - (Ваш вес * текущий % жира) = кг</strong></p>',
        )

    def test_escaped_asterisks_stay_literal_without_disabling_other_emphasis(self) -> None:
        rendered = markdown_to_article_html(r"\*Не курсив\* и *курсив*, **жирное** <script>")
        self.assertEqual(
            sanitize_article_html(rendered),
            '<p>*Не курсив* и <em>курсив</em>, <strong>жирное</strong> &lt;script&gt;</p>',
        )

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

    def test_course_material_links_stay_on_the_account_site_and_in_the_same_tab(self) -> None:
        source = (
            "[Вкусы](https://похудение-это-есть.рф/lk?course_day=7&course_material=day-06-article-03) "
            "[Рецепт](/apps/masterclass-course.html?course_day=7&course_material=day-07-recipe-marinara)"
        )
        rendered = markdown_to_article_html(source)
        self.assertIn(
            '<a href="/lk?course_day=7&amp;course_material=day-06-article-03">Вкусы</a>',
            rendered,
        )
        self.assertIn(
            '<a href="/lk?course_day=7&amp;course_material=day-07-recipe-marinara">Рецепт</a>',
            rendered,
        )
        self.assertNotIn('target="_blank"', rendered)
        self.assertEqual(
            sanitize_article_html(
                '<p><a href="https://edabalans.ru/apps/masterclass-course.html?course_day=7&amp;course_material=day-06-article-03" target="_blank">Вкусы</a></p>',
                course_semantics=True,
            ),
            '<p><a href="/lk?course_day=7&amp;course_material=day-06-article-03">Вкусы</a></p>',
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
