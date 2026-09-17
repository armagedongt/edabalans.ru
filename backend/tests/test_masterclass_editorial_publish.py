from __future__ import annotations

import json
import os
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import MasterclassStepProgress, User
from scripts.bootstrap_masterclass_editorial import parse_program
from scripts.publish_masterclass_editorial import (
    apply_day_copy,
    compile_manifest,
    editorial_body,
    migrate_step_progress,
    special_prelude,
)


ROOT = Path(__file__).resolve().parents[2]


def test_editorial_program_compiles_to_runtime_titles_and_visible_steps() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )

    compiled, _ = compile_manifest(manifest, next_version=12)

    assert len(compiled["days"]) == 20
    assert compiled["days"][5]["title"] == "Опорные точки в питании"
    assert compiled["days"][5]["tocSummary"] == ""
    assert [
        step["id"]
        for step in compiled["days"][6]["steps"]
        if not step.get("hidden", False)
    ] == [
        "day-07-video-01",
        "day-07-store-food",
        "day-07-recipes-part-1",
    ]
    assert next(
        step
        for step in compiled["days"][5]["steps"]
        if step["id"] == "day-06-article-04"
    )["hidden"] is True
    cycles = next(
        step
        for step in compiled["days"][16]["steps"]
        if step["id"] == "day-17-article-04"
    )
    assert cycles["hidden"] is False
    assert cycles["locked"] is True
    assert cycles["badge"] == "Скоро"


def test_editorial_program_restores_placeholder_missing_from_older_runtime() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["days"][16]["steps"] = [
        step
        for step in manifest["days"][16]["steps"]
        if step["id"] != "day-17-article-04"
    ]

    compiled, _ = compile_manifest(manifest, next_version=12)

    cycles = next(
        step
        for step in compiled["days"][16]["steps"]
        if step["id"] == "day-17-article-04"
    )
    assert cycles["contentKind"] == "placeholder"
    assert cycles["status"] == "draft"
    assert cycles["locked"] is True
    assert cycles["badge"] == "Скоро"


def test_program_order_replaces_stale_runtime_order() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["days"][9]["steps"][0], manifest["days"][9]["steps"][1] = (
        manifest["days"][9]["steps"][1],
        manifest["days"][9]["steps"][0],
    )

    compiled, _ = compile_manifest(manifest, next_version=12)

    assert [step["id"] for step in compiled["days"][9]["steps"][:3]] == [
        "day-10-article-01",
        "day-10-article-02",
        "day-10-article-03",
    ]


def test_day_markdown_supplies_runtime_day_copy_and_checks() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    days, _ = parse_program()
    compiled, _ = compile_manifest(manifest, next_version=12)

    apply_day_copy(compiled, days)

    day = compiled["days"][5]
    assert day["lead"].startswith("Сегодня собираем первую версию еды")
    assert day["intro"].startswith("<p>Сегодня не нужно искать идеальный рецепт")
    assert day["afterText"].startswith("<p>Выберите один повторяющийся приём пищи")
    assert day["checks"][0]["text"].startswith("Выбрать одну опорную точку")
    assert "<p>" in day["intro"]

    first = compiled["days"][0]
    assert first["intro"] == ""
    assert "достаточно одной галочки" in first["afterText"]


def test_first_five_release_preserves_later_days_and_adds_practice() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["days"][5]["intro"] = "Редакция другого потока"
    compiled, _ = compile_manifest(manifest, next_version=12, through_day=5)
    days, _ = parse_program()
    apply_day_copy(compiled, days, through_day=5)
    assert compiled["days"][5:] == manifest["days"][5:]
    practice = next(step for step in compiled["days"][2]["steps"]
                    if step["id"] == "day-03-practice")
    assert practice["hidden"] is False
    assert practice["contentKind"] == "text"
    assert practice["requiredForAllAfterRevision"] == 12


def test_partial_publish_writes_only_selected_day_articles(monkeypatch) -> None:
    from scripts import publish_masterclass_editorial as publisher
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    writes = []
    class Database:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def commit(self):
            pass
    monkeypatch.setattr(publisher, "SessionLocal", Database)
    monkeypatch.setattr(publisher, "active_course_version", lambda db:
                        SimpleNamespace(payload=manifest, version_no=11))
    monkeypatch.setattr(publisher, "publish_document", lambda *a, **kw:
                        SimpleNamespace(version_no=12))
    monkeypatch.setattr(publisher, "migrate_step_progress", lambda *a: 0)
    monkeypatch.setattr(publisher, "get_material", lambda *a: {"version": 0})
    monkeypatch.setattr(publisher, "publish_material", lambda *a, **kw:
                        writes.append(kw["step_id"]))
    monkeypatch.setattr("sys.argv", ["publisher", "--through-day", "5", "--publish"])
    publisher.main()
    _, materials = parse_program()
    expected = {item["step_id"] for item in materials.values()
                if item["day"] <= 5 and item["type"] == "article"}
    assert set(writes) == expected
    assert len(writes) == len(expected)


def test_special_material_prelude_uses_markdown_before_embed_only() -> None:
    path = (
        ROOT / "content" / "masterclass" / "editorial" / "materials"
        / "06-04-что-такое-система-рецептов.md"
    )

    html = special_prelude(path, "offer")

    assert "Можно знать правило тарелки" in html
    assert "EMBED" not in html

    empty = (
        ROOT / "content" / "masterclass" / "editorial" / "materials"
        / "01-05-что-еще-вам-может-понадобиться.md"
    )
    assert special_prelude(empty, "offer") == ""


def test_step_progress_follows_stable_id_when_program_reorders_steps() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    current = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    current["days"][9]["steps"][0], current["days"][9]["steps"][1] = (
        current["days"][9]["steps"][1],
        current["days"][9]["steps"][0],
    )
    compiled, _ = compile_manifest(current, next_version=12)
    with Session(engine) as db:
        user = User(display_name="Тест", status="active")
        db.add(user)
        db.flush()
        first = MasterclassStepProgress(
            user_id=user.id, day_number=10, step_index=0,
            step_kind="article",
        )
        second = MasterclassStepProgress(
            user_id=user.id, day_number=10, step_index=1,
            step_kind="article",
        )
        db.add_all([first, second])
        db.flush()
        first_id, second_id = first.id, second.id

        assert migrate_step_progress(db, current, compiled) == 2
        rows = list(db.scalars(
            select(MasterclassStepProgress).order_by(MasterclassStepProgress.step_index)
        ))
        assert [row.step_index for row in rows] == [0, 1]
        assert rows[0].id == second_id
        assert rows[1].id == first_id


def test_editorial_body_rewrites_local_article_images_to_public_media_route() -> None:
    path = (
        ROOT
        / "content"
        / "masterclass"
        / "editorial"
        / "materials"
        / "07-02-еда-из-магазина-и-доставок.md"
    )

    body = editorial_body(path)

    assert "](assets/" not in body
    assert "](/course-assets/masterclass/media/55-store-food-without-cooking/" in body
    assert not body.startswith("# ")
    assert "> Тип:" not in body


def test_tutorial_body_omits_working_status_metadata() -> None:
    body = editorial_body(
        ROOT / "content/masterclass/editorial/materials/01-01-как-устроен-мастер-класс.md"
    )
    assert "draft_for_editing" not in body
    assert "хотя бы одна галочка" in body
