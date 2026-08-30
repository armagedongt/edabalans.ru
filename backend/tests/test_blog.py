from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.blog_routes import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_blog_home_is_public_and_uses_the_accepted_structure() -> None:
    response = client.get("/blog")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "Похудение — это есть" in response.text
    assert "Блог Сергея Воронцова" in response.text
    assert "Разбираю питание, похудение, пищевые привычки без диетических страшилок и волшебных обещаний." in response.text
    assert "30 августа" not in response.text.lower()
    assert response.text.count('class="article-card"') == 6
    assert response.text.count('class="card-tag"') == 6
    assert 'href="?page=1#articles"' in response.text
    assert 'href="?page=2#articles"' in response.text
    assert "showPage(Math.min(current + 1, pageCount), true)" in response.text
    assert "Включить тёмную тему" in response.text
    assert "site-footer.js" in response.text
    assert '/blog/fonts/inter-cyrillic.woff2' in response.text


def test_blog_home_trailing_slash_is_supported() -> None:
    assert client.get("/blog/").status_code == 200


def test_blog_fonts_are_self_hosted_and_whitelisted() -> None:
    font = client.get("/blog/fonts/inter-cyrillic.woff2")

    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert font.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/blog/fonts/unknown.woff2").status_code == 404
