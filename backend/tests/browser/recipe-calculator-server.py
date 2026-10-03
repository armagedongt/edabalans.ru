"""Synthetic loopback server for the real recipe browser journey; no external jobs."""

import json
import os
import socket
import sys
from decimal import Decimal
from pathlib import Path

database = Path(sys.argv[1]).resolve()
if database.exists() or database.suffix != ".sqlite":
    raise RuntimeError("A fresh synthetic .sqlite path is required")
database.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + database.as_posix()
os.environ["APP_AUTH_SECRET"] = "test-client-session-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Resource, UserCoursePolicy  # noqa: E402
from app.product_catalog_service import PRODUCT_CONNECTIONS  # noqa: E402
from app.recipe_models import NutritionProduct  # noqa: E402
from test_recipe_calculator import grant_user, seed_original  # noqa: E402

PRODUCT_CONNECTIONS["recipes"]["maintenance"] = False
Base.metadata.create_all(engine)
vectors = json.loads(Path(__file__).with_name("recipe-calculator-vectors.json").read_text(encoding="utf-8"))
with SessionLocal() as db:
    seed_original(db)
    user = grant_user(db, "recipe-browser@example.test")
    grant_user(db, "recipe-other@example.test")
    course = Resource(code="ACCESS_RECIPES", name="Тестовый курс", status="active")
    db.add(course)
    db.flush()
    db.add(UserCoursePolicy(user_id=user.id, resource_id=course.id, start_mode="blocked", source="test"))
    for vector in vectors:
        for name, _, protein, fat, carbohydrate, calories in vector["rows"]:
            db.add(NutritionProduct(
                name=name, name_normalized=name.casefold(), is_active=True,
                protein_g=Decimal(protein) / 1000, fat_g=Decimal(fat) / 1000,
                carbohydrate_g=Decimal(carbohydrate) / 1000, calories_kcal=Decimal(calories) / 1000,
            ))
    db.commit()

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen()
print("RECIPE_TEST_URL=http://127.0.0.1:" + str(sock.getsockname()[1]), flush=True)
uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off")).run(sockets=[sock])
