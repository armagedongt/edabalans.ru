import unittest

import test_article_markup  # supplies optional FastAPI stub
from app.article_markup import markdown_to_article_html, sanitize_article_html
from app.masterclass_article_components import render_masterclass_component


class RecipeCardTests(unittest.TestCase):
    def test_card_keeps_both_same_origin_download_controls(self):
        url = '/course-assets/masterclass/media/15-recipes/caesar/recipe-card-caesar.webp'
        rendered = markdown_to_article_html(
            f'recipe_card(\n{url}\nЦезарь\n)',
            component_renderer=render_masterclass_component,
        )
        self.assertEqual(rendered.count(' download'), 2)
        self.assertEqual(rendered.count(f'href="{url}"'), 2)
        self.assertIn(f'src="{url}"', rendered)
        self.assertIn('class="recipe-card-download"', rendered)
        self.assertIn('class="recipe-card-save"', rendered)
        self.assertIn('Скачать карточку', rendered)
        self.assertNotIn('target="_blank"', rendered)

    def test_component_rejects_foreign_encoded_and_traversal_sources(self):
        for url in ['https://example.test/image.webp', '//example.test/x.webp',
                    '/course-assets/masterclass/media/../x.webp',
                    '/course-assets/masterclass/media/%2e%2e/x.webp',
                    '/course-assets/masterclass/media/x.webp?download=1',
                    '/course-assets/masterclass/media/x.svg']:
            with self.subTest(url=url), self.assertRaises(Exception):
                render_masterclass_component('recipe_card', [url, 'Название'])

    def test_foreign_anchor_cannot_gain_download_classes(self):
        html = '<a href="https://example.test/x.webp" class="recipe-card-save" download onclick="x()">X</a>'
        cleaned = sanitize_article_html(html, course_semantics=True, allow_product_components=True)
        self.assertNotIn('download', cleaned)
        self.assertNotIn('recipe-card-save', cleaned)
        self.assertNotIn('onclick', cleaned)

    def test_caption_is_escaped_and_component_disabled_for_plain_article(self):
        url='/course-assets/masterclass/media/15-recipes/caesar/a.webp'
        rendered=render_masterclass_component('recipe_card',[url,'<img onerror="bad">'])
        self.assertIn('&lt;img',rendered)
        with self.assertRaises(Exception):
            markdown_to_article_html(f'recipe_card(\n{url}\nЦезарь\n)')
