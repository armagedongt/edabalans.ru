import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import course_material_routes as routes


class DirectRecipeArticleTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)

    def test_public_article_has_card_without_login_or_course_navigation(self):
        response = self.client.get('/recipe-preview/mackerel-pasta-salad')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['x-robots-tag'], 'noindex, nofollow')
        self.assertIn('class="recipe-card"', response.text)
        self.assertIn(' download', response.text)
        self.assertNotIn('recipe-card-data:start', response.text)
        self.assertNotIn('course_day=', response.text)
        self.assertNotIn('Полный каталог', response.text)
        self.assertEqual(response.text.count('<h1>'), 1)

    def test_unknown_course_ids_and_path_inputs_cannot_open_other_materials(self):
        for slug in ['day-15-recipes-part-2', 'day-01-article-02', 'program', '%2e%2e', 'unknown']:
            with self.subTest(slug=slug):
                self.assertEqual(self.client.get('/recipe-preview/' + slug).status_code, 404)

    def test_missing_allowed_source_is_not_a_server_error(self):
        with TemporaryDirectory() as folder, patch.object(routes, 'COURSE_CONTENT_ROOT', Path(folder)):
            self.assertEqual(self.client.get('/recipe-preview/yogurt-cake').status_code, 404)

    def test_existing_unapproved_markdown_cannot_be_published_by_guessing_its_name(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'editorial/unlisted-recipes/unknown.md'
            source.parent.mkdir(parents=True)
            source.write_text('# Не разрешённый материал\n\nЗакрытый черновик.', encoding='utf-8')
            template = root / 'components/recipe-preview/page.html'
            template.parent.mkdir(parents=True)
            template.write_text('<h1>{{title}}</h1>{{body}}', encoding='utf-8')
            with patch.object(routes, 'COURSE_CONTENT_ROOT', root):
                self.assertEqual(self.client.get('/recipe-preview/unknown').status_code, 404)


if __name__ == '__main__':
    unittest.main()
