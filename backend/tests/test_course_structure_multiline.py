import os
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/test",
)

from app.course_structure_service import sanitize_fragment


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
