"""Generate an isolated real SSR fixture; never assign origin to a real article."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.blog_routes import router
from app.blog_content import load_blog_catalog, default_content_dir
from unittest.mock import patch

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
article = load_blog_catalog().by_slug('pochemu-yapontsy-hudye-a-ty-net')
source_path = default_content_dir() / 'articles' / article.body_file
original = Path.read_text

def read(path, *args, **kwargs):
    text = original(path, *args, **kwargs)
    if path == source_path:
        return '---\ntelegram_post_url: https://t.me/Fitness_Talks/123\ntelegram_discussion_url: https://t.me/Fitness_Talks/123?comment=2\n---\n' + text
    return text

engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
app = FastAPI()
app.include_router(router)
def test_db():
    with Session(engine) as db:
        yield db
app.dependency_overrides[get_db] = test_db
try:
    with patch.object(Path, 'read_text', read), TestClient(app) as client:
        response = client.get('/blog/articles/' + article.slug)
        assert response.status_code == 200, response.text
        assert response.text.count('data-channel-origin="telegram"') == 1
        (out / 'article.html').write_text(response.text, encoding='utf-8')
        if '--serve' in sys.argv:
            import uvicorn
            uvicorn.run(app, host='127.0.0.1', port=8787)
finally:
    engine.dispose()
