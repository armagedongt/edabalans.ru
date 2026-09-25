"""Validate the owner-editable Masterclass Markdown package without publishing."""
from __future__ import annotations

from pathlib import Path
import re
import sys

try:
    from bootstrap_masterclass_editorial import EDITORIAL, parse_program
except ModuleNotFoundError:  # Imported as backend.scripts.* in tests and tooling.
    from scripts.bootstrap_masterclass_editorial import EDITORIAL, parse_program

try:
    from app.masterclass_editorial import (
        EDITABLE_MATERIALS,
        ROOT,
        validate_editorial_source,
    )
except ModuleNotFoundError:  # Executed with the repository root on sys.path.
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from app.masterclass_editorial import (
        EDITABLE_MATERIALS,
        ROOT,
        validate_editorial_source,
    )


def main() -> None:
    days, materials = parse_program()
    errors: list[str] = []
    linked = {
        item["path"].resolve()
        for item in materials.values()
        if item["path"] is not None
    }
    linked.update({
        (EDITORIAL / "materials" / "07-00-приобрести-систему-рецептов.md").resolve(),
        (EDITORIAL / "materials" / "15-00-приобрести-каталог-рецептов.md").resolve(),
        (EDITORIAL / "materials" / "08-01-система-рецептов-последний-день.md").resolve(),
    })
    for step_id, relative_path in EDITABLE_MATERIALS.items():
        path = (ROOT / relative_path).resolve()
        linked.add(path)
        if not path.is_file():
            errors.append(f"Нет подключённого Markdown-файла: {relative_path}")
            continue
        try:
            validate_editorial_source(step_id, path.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"Неверный подключённый Markdown-файл {relative_path}: {exc}")
    for item in materials.values():
        path: Path | None = item["path"]
        if path is None:
            if item["type"] != "messenger":
                errors.append(
                    f"Материал без Markdown допустим только для messenger: {item['step_id']}"
                )
            continue
        if not path.is_file():
            errors.append(f"Нет файла: {path.relative_to(EDITORIAL)}")
            continue
        text = path.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        # The file H1 is a reading aid, never an independent runtime title.
        if f"step_id: {item['step_id']}" not in text:
            errors.append(f"Нет стабильного ID: {path.relative_to(EDITORIAL)}")
        expected_type = {
            "article": "статья",
            "questionnaire": "анкета",
            "application": "приложение",
            "offer": "допродажа",
        }[item["type"]]
        if f"Тип: **{expected_type}**" not in text:
            errors.append(f"Неверный тип: {path.relative_to(EDITORIAL)}")
        exact_embeds = {
            "day-01-questionnaire": "<!-- EMBED: questionnaire onboarding -->",
            "day-02-current-diet": "<!-- EMBED: questionnaire current-diet -->",
            "day-19-closing-review": "<!-- EMBED: questionnaire closing-review -->",
            "day-04-dqs": "<!-- EMBED: application dqs -->",
            "day-15-recipes-part-2": "<!-- EMBED: application recipes-part-2 -->",
        }
        expected_embed = exact_embeds.get(item["step_id"])
        if item["type"] == "offer":
            expected_embed = "<!-- EMBED: universal-offer -->"
        if expected_embed and expected_embed not in text:
            errors.append(
                f"Неверная метка встроенного блока: {path.relative_to(EDITORIAL)}"
            )
    for day in days:
        if not day["intro_text"]:
            errors.append(f"Нет текста дня {day['number']} в program.md")
        if not re.search(r"^- \[[ xX]] .+", day["task_text"], flags=re.MULTILINE):
            errors.append(f"Нет пунктов задания дня {day['number']} в program.md")
    for path in (EDITORIAL / "materials").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        is_editing_draft = "Статус: `draft_for_editing`" in text
        if path.resolve() not in linked and not is_editing_draft:
            errors.append(f"Файл не включён в программу: {path.relative_to(EDITORIAL)}")
        first = text.splitlines()[0]
        if re.match(r"^# .+\.$", first):
            errors.append(f"Точка в конце заголовка: {path.relative_to(EDITORIAL)}")
    access_markers = {
        "07-00-приобрести-систему-рецептов.md": "recipes-part-1-gate",
        "15-00-приобрести-каталог-рецептов.md": "recipes-part-2-gate",
    }
    for filename, gate in access_markers.items():
        text = (EDITORIAL / "materials" / filename).read_text(encoding="utf-8")
        if f"access_gate: {gate}" not in text or "<!-- EMBED: universal-offer -->" not in text:
            errors.append(f"Неверная заглушка доступа: materials/{filename}")
    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print(f"OK: {len(days)} дней, {len(materials)} материалов и 2 заглушки доступа")


if __name__ == "__main__":
    main()
