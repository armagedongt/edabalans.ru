import os
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from app.course_structure_service import merge_seed_additions, sanitize_fragment


ROOT = Path(__file__).resolve().parents[2]


def test_course_structure_keeps_plain_newlines_and_renders_them() -> None:
    assert sanitize_fragment("Первая строка\nВторая строка") == (
        "Первая строка\nВторая строка"
    )

    static = ROOT / "backend" / "app" / "static"
    editor = (static / "course-structure-editor.js").read_text(encoding="utf-8")
    course = (static / "masterclass-first-days-preview.html").read_text(
        encoding="utf-8"
    )

    assert '<textarea class="grow check-text" rows="3" data-check-text=' in editor
    assert ".hero-lead,.intro,.assignment-intro p" in course
    assert ".checkline span{white-space:pre-line}" in course


def test_chat_managed_seed_addition_preserves_existing_copy_and_marks_new_step() -> None:
    current = {
        "days": [{
            "number": 2,
            "title": "Отредактированное название",
            "steps": [
                {"id": "article-1", "kind": "article", "title": "Первый"},
                {"id": "article-2", "kind": "article", "title": "Второй"},
            ],
            "checks": [],
        }]
    }
    seed = {
        "days": [{
            "number": 2,
            "title": "Название из seed",
            "steps": [
                {"id": "article-1", "kind": "article", "title": "Первый"},
                {"id": "article-2", "kind": "article", "title": "Второй"},
                {"id": "questionnaire", "kind": "questionnaire", "label": "Опросник"},
            ],
            "checks": [],
        }]
    }

    merged = merge_seed_additions(current, seed, 7)

    assert merged["days"][0]["title"] == "Отредактированное название"
    assert [step["id"] for step in merged["days"][0]["steps"]] == [
        "article-1", "article-2", "questionnaire",
    ]
    assert merged["days"][0]["steps"][-1]["requiredForAllAfterRevision"] == 7
