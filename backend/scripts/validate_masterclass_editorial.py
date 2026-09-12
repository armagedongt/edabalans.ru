"""Validate the owner-editable Masterclass Markdown package without publishing."""
from __future__ import annotations

from pathlib import Path
import re

from bootstrap_masterclass_editorial import EDITORIAL, parse_program


def main() -> None:
    days, materials = parse_program()
    errors: list[str] = []
    linked = {item["path"].resolve() for item in materials.values()}
    linked.update({
        (EDITORIAL / "materials" / "07-00-приобрести-систему-рецептов.md").resolve(),
        (EDITORIAL / "materials" / "15-00-приобрести-каталог-рецептов.md").resolve(),
    })
    for item in materials.values():
        path: Path = item["path"]
        if not path.is_file():
            errors.append(f"Нет файла: {path.relative_to(EDITORIAL)}")
            continue
        text = path.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        if first != f"# {item['title']}":
            errors.append(
                f"Заголовок не совпадает с program.md: {path.relative_to(EDITORIAL)}"
            )
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
            "day-07-recipes-part-1": "<!-- EMBED: application recipes-part-1 -->",
            "day-15-recipes-part-2": "<!-- EMBED: application recipes-part-2 -->",
        }
        expected_embed = exact_embeds.get(item["step_id"])
        if item["type"] == "offer":
            expected_embed = "<!-- EMBED: universal-offer -->"
        if expected_embed and expected_embed not in text:
            errors.append(
                f"Неверная метка встроенного блока: {path.relative_to(EDITORIAL)}"
            )
    expected_day_paths: set[Path] = set()
    for day in days:
        safe_title = re.sub(r'[<>:"/\\|?*]', "-", day["title"]).strip().rstrip(".")
        path = EDITORIAL / "days" / f"{day['number']:02d}-{safe_title}.md"
        expected_day_paths.add(path.resolve())
        if not path.is_file():
            errors.append(f"Нет файла дня: {path.relative_to(EDITORIAL)}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith(f"# {day['number']}. {day['title']}\n"):
            errors.append(f"Заголовок дня не совпадает: {path.relative_to(EDITORIAL)}")
        if f"day_id: day-{day['number']:02d}" not in text:
            errors.append(f"Нет стабильного ID дня: {path.relative_to(EDITORIAL)}")
    for path in (EDITORIAL / "days").glob("*.md"):
        if path.resolve() not in expected_day_paths:
            errors.append(f"Файл дня не включён в программу: {path.relative_to(EDITORIAL)}")
    for path in (EDITORIAL / "materials").glob("*.md"):
        if path.resolve() not in linked:
            errors.append(f"Файл не включён в программу: {path.relative_to(EDITORIAL)}")
        first = path.read_text(encoding="utf-8").splitlines()[0]
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
