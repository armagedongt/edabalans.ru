"""One-time bootstrap of the owner-editable Masterclass Markdown package.

The command copies existing author text without rewriting it. It deliberately
does not publish anything and never talks to PostgreSQL.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
EDITORIAL = ROOT / "content" / "masterclass" / "editorial"
SOURCE = ROOT / "content" / "masterclass" / "source-current"
COURSE = ROOT / "content" / "masterclass" / "course" / "course.json"


SOURCE_BY_STEP = {
    "day-01-article-tutorial": "00-how-to-use-masterclass.md",
    "day-01-article-02": "01-food-diary.md",
    "day-01-article-03": "02-weighing.md",
    "day-02-article-01": "03-four-diet-categories.md",
    "day-02-article-02": "04-mediterranean-diet.md",
    "day-03-video-01": "06-necessary-restrictions.md",
    "day-03-article-02": "08-whole-processed-ultraprocessed-food.md",
    "day-03-article-03": "07-reading-labels.md",
    "day-04-article-01": "13-dqs-system.md",
    "day-04-dqs": "19-dqs-access-and-print-options.md",
    "day-05-article-01": "14-protein-fat-carbohydrates.md",
    "day-05-article-03": "15-plate-rule.md",
    "day-06-article-01": "44-anchor-points-in-nutrition.md",
    "day-06-article-02": "45-my-anchor-point-oatmeal.md",
    "day-06-article-03": "34-five-tastes.md",
    "day-06-offer": "59-recipe-system-offer.md",
    "day-07-video-01": "54-meal-constructor.md",
    "day-07-store-food": "55-store-food-without-cooking.md",
    "day-07-recipes-part-1": "58-first-recipes-selection.md",
    "day-09-article-01": "67-emotional-hunger-guide.md",
    "day-10-article-01": "66-sugar-plan.md",
    "day-10-article-02": "51-sugar-norms.md",
    "day-10-article-03": "27-added-sugar-guide.md",
    "day-11-article-01": "28-reduce-harm-from-sweets.md",
    "day-11-article-02": "29-reduce-amount-of-sweets.md",
    "day-12-article-01": "30-breakdowns-overeating-cheat-meals.md",
    "day-12-article-02": "38-cheat-meals-audio.md",
    "day-13-article-01": "31-satiety-habits.md",
    "day-13-article-02": "32-pleasure-habits.md",
    "day-14-article-01": "46-eating-outside-home.md",
    "day-15-article-02": "33-kitchen-matters.md",
    "day-18-article-02": "63-behind-scenes.md",
    "day-17-article-01": "16-health-block-closing.md",
    "day-17-article-02": "17-detox-vitamins-minerals-tests.md",
    "day-17-article-03": "18-water.md",
    "day-20-article-01": "64-addictions-guide.md",
    "day-20-article-02": "65-five-years-goal.md",
    "day-19-article-02": "52-how-consultation-works.md",
    "day-21-article-01": "50-final-stream-and-periodization.md",
}


QUESTIONNAIRE_BY_STEP = {
    "day-01-questionnaire": ("ONBOARDING_QUESTIONS", "onboarding"),
    "day-02-current-diet": ("CURRENT_DIET_QUESTIONS", "current-diet"),
    "day-19-closing-review": ("CLOSING_QUESTIONS", "closing-review"),
}


TYPE_LABELS = {
    "article": "статья",
    "questionnaire": "анкета",
    "application": "приложение",
    "offer": "допродажа",
}


def parse_program() -> tuple[list[dict], dict[str, dict]]:
    text = (EDITORIAL / "program.md").read_text(encoding="utf-8")
    days: list[dict] = []
    materials: dict[str, dict] = {}
    current_day: dict | None = None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        day_match = re.match(r"## (\d+)\. (.+)$", line)
        if day_match:
            current_day = {
                "number": int(day_match.group(1)),
                "title": day_match.group(2).strip(),
                "materials": [],
            }
            days.append(current_day)
            continue
        material_match = re.match(
            r"\d+\. \[([^]]+)]\((materials/[^)]+)\) · ≈ (\d+) мин$", line
        )
        if not material_match or current_day is None:
            continue
        if index + 1 >= len(lines):
            raise ValueError(f"Нет технической привязки после: {line}")
        meta = re.search(
            r"step_id: ([^; ]+); type: ([^; ]+)(?:;[^>]*)?", lines[index + 1]
        )
        if not meta:
            raise ValueError(f"Нет step_id/type после: {line}")
        item = {
            "day": current_day["number"],
            "title": material_match.group(1).strip(),
            "path": EDITORIAL / material_match.group(2),
            "duration": int(material_match.group(3)),
            "step_id": meta.group(1),
            "type": meta.group(2),
        }
        if item["title"].endswith("."):
            raise ValueError(f"Точка в конце названия материала: {item['title']}")
        if item["step_id"] in materials:
            raise ValueError(f"Повторяется step_id: {item['step_id']}")
        current_day["materials"].append(item)
        materials[item["step_id"]] = item
    if [day["number"] for day in days] != list(range(1, 21)):
        raise ValueError("В program.md должны быть дни 1–20 без пропусков")
    return days, materials


def special_body(item: dict) -> str:
    step_id = item["step_id"]
    if step_id in QUESTIONNAIRE_BY_STEP:
        constant, questionnaire_kind = QUESTIONNAIRE_BY_STEP[step_id]
        route_path = ROOT / "backend" / "app" / "masterclass_routes.py"
        tree = ast.parse(route_path.read_text(encoding="utf-8"))
        questions = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == constant
                for target in node.targets
            ):
                questions = ast.literal_eval(node.value)
                break
        if questions is None:
            raise ValueError(f"Не найдены вопросы {constant}")
        intro = (
            "Отвечайте в свободной форме. Каждый ответ сохраняется отдельно и автоматически."
            if questionnaire_kind != "current-diet"
            else "Оцените, как сейчас представлены в вашем питании разные продуктовые категории."
        )
        rendered = [intro, "", "## Вопросы", ""]
        for index, (code, title, description) in enumerate(questions, 1):
            rendered.extend([
                f"### {index}. {title}",
                f"<!-- question_code: {code} -->",
                "",
                description or "<!-- Пояснение к вопросу пока отсутствует. -->",
                "",
            ])
        rendered.append(f"<!-- EMBED: questionnaire {questionnaire_kind} -->")
        if questionnaire_kind in {"onboarding", "closing-review"}:
            rendered.extend([
                "",
                "После заполнения нажмите «Отправить в мессенджер». Анкета отправится в мессенджер, который вы привязали к личному кабинету.",
            ])
        return "\n".join(rendered) + "\n"
    if step_id == "day-07-recipes-part-1":
        source = without_duplicate_leading_title(
            (SOURCE / SOURCE_BY_STEP[step_id]).read_text(encoding="utf-8")
        )
        return source + "\n\n<!-- EMBED: application recipes-part-1 -->\n"
    if step_id == "day-15-recipes-part-2":
        return "<!-- EMBED: application recipes-part-2 -->\n"
    if step_id == "day-04-dqs":
        source = without_duplicate_leading_title(
            (SOURCE / SOURCE_BY_STEP[step_id]).read_text(encoding="utf-8")
        )
        return source + "\n\n<!-- EMBED: application dqs -->\n"
    if item["type"] == "offer":
        source_name = SOURCE_BY_STEP.get(step_id)
        source = (
            without_duplicate_leading_title(
                (SOURCE / source_name).read_text(encoding="utf-8")
            )
            if source_name
            else ""
        )
        return source.rstrip() + "\n\n<!-- EMBED: universal-offer -->\n"
    return "<!-- Текст материала будет отредактирован владельцем. -->\n"


def without_duplicate_leading_title(text: str) -> str:
    """The editorial wrapper owns the only H1; preserve the rest byte-for-byte."""
    return re.sub(r"\A\ufeff?# [^\r\n]+\r?\n(?:\r?\n)?", "", text, count=1)


def write_material(item: dict, *, force: bool) -> None:
    path: Path = item["path"]
    if path.exists() and not force:
        return
    source_name = SOURCE_BY_STEP.get(item["step_id"])
    if item["type"] == "article" and source_name:
        source_text = (SOURCE / source_name).read_text(encoding="utf-8")
        body = without_duplicate_leading_title(source_text).strip() + "\n"
    else:
        body = special_body(item).strip() + "\n"
    marker = TYPE_LABELS[item["type"]]
    header = (
        f"# {item['title']}\n\n"
        f"> Тип: **{marker}** · примерное время: **{item['duration']} мин**\n\n"
        f"<!-- step_id: {item['step_id']}; day: {item['day']}; "
        f"source: {source_name or 'none'} -->\n\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body, encoding="utf-8")


def write_day(day: dict, manifest_day: dict, *, force: bool) -> None:
    safe_title = re.sub(r'[<>:"/\\|?*]', "-", day["title"]).strip().rstrip(".")
    path = EDITORIAL / "days" / f"{day['number']:02d}-{safe_title}.md"
    if path.exists() and not force:
        return
    materials = "\n".join(
        f"{index}. [{item['title']}](../materials/{item['path'].name}) · ≈ {item['duration']} мин"
        for index, item in enumerate(day["materials"], 1)
    )
    checks = "\n".join(
        f"- [ ] {check['text']}"
        for check in manifest_day.get("checks", [])
        if not check.get("hidden", False)
    )
    body = f"""# {day['number']}. {day['title']}

<!-- day_id: day-{day['number']:02d} -->

## Перед вводным медиа

{manifest_day.get('lead', '')}

## После вводного медиа

{manifest_day.get('intro', '')}

## Материалы дня

{materials or '<!-- В этом дне нет отдельных материалов. -->'}

## Перед заданием

{manifest_day.get('afterLead', '')}

{manifest_day.get('afterTitle', '')}

{manifest_day.get('afterText', '')}

## Задание на сегодня

{checks or '<!-- Задания дня будут добавлены владельцем. -->'}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def write_access_placeholders(*, force: bool) -> None:
    placeholders = {
        "07-00-приобрести-систему-рецептов.md": (
            "Приобрести «Систему рецептов»",
            "recipes-part-1-gate",
        ),
        "15-00-приобрести-каталог-рецептов.md": (
            "Приобрести полный каталог рецептов",
            "recipes-part-2-gate",
        ),
    }
    for filename, (title, placement) in placeholders.items():
        path = EDITORIAL / "materials" / filename
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {title}\n\n> Тип: **заглушка доступа**\n\n"
            f"<!-- access_gate: {placement} -->\n\n"
            "<!-- Индивидуальный текст заглушки будет добавлен владельцем. -->\n\n"
            "<!-- EMBED: universal-offer -->\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    days, materials = parse_program()
    manifest = json.loads(COURSE.read_text(encoding="utf-8"))
    manifest_days = {int(day["number"]): day for day in manifest["days"]}
    for item in materials.values():
        write_material(item, force=False)
    for day in days:
        write_day(day, manifest_days[day["number"]], force=False)
    write_access_placeholders(force=False)
    print(f"Подготовлено: {len(days)} дней, {len(materials)} материалов")


if __name__ == "__main__":
    main()
