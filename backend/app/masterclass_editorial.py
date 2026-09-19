from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
EDITORIAL_ROOT = ROOT / "content" / "masterclass" / "editorial"

# Первый безопасный вертикальный срез. Новые материалы добавляются сюда только
# после проверки их runtime-типа и публикационного маршрута.
EDITABLE_MATERIALS = {
    "day-01-article-02": (
        "content/masterclass/editorial/materials/"
        "01-02-как-вести-дневник-питания.md"
    ),
}


def editable_material_path(step_id: str) -> str:
    try:
        return EDITABLE_MATERIALS[step_id]
    except KeyError as exc:
        raise KeyError("Материал пока не подключён к Markdown-редактору") from exc


def local_editable_material(step_id: str) -> Path:
    return ROOT / editable_material_path(step_id)


def editorial_body_text(text: str) -> str:
    """Remove the editorial title/type/source wrapper before runtime rendering."""
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^>\s*Тип:", lines[0].strip(), re.IGNORECASE):
        lines.pop(0)
    while lines and (
        not lines[0].strip()
        or re.match(r"^<!--\s*step_id:", lines[0].strip(), re.IGNORECASE)
    ):
        lines.pop(0)
    return "\n".join(lines).strip() + "\n"


def editorial_body(path: Path) -> str:
    return editorial_body_text(path.read_text(encoding="utf-8"))


def validate_editorial_source(step_id: str, text: str) -> list[str]:
    """Validate the stable authoring wrapper; return non-blocking warnings."""
    if len(text.encode("utf-8")) > 500_000:
        raise ValueError("Markdown-файл превышает допустимый размер 500 КБ")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError("Первая строка материала должна быть заголовком Markdown: # …")
    h1_lines = [line for line in lines if line.startswith("# ")]
    if len(h1_lines) != 1:
        raise ValueError("В материале должен быть ровно один служебный заголовок первого уровня")
    markers = re.findall(r"<!--\s*step_id:\s*([^;\s]+)", text, re.IGNORECASE)
    if markers != [step_id]:
        raise ValueError(f"Служебный step_id должен быть ровно один и равен {step_id}")
    if re.search(r"\]\(\s*javascript:", text, re.IGNORECASE):
        raise ValueError("В Markdown запрещены ссылки javascript:")
    warnings: list[str] = []
    if not any(line.startswith("## ") for line in lines):
        warnings.append("В материале нет разделов второго уровня — оглавление не появится")
    return warnings
