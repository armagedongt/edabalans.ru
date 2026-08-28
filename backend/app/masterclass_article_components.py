"""Closed product-owned renderers for Masterclass article component calls."""
from __future__ import annotations

from html import escape

from fastapi import HTTPException

from app.article_markup import inline_markdown, safe_image_src


DQS_SCORE_CATEGORIES = {
    "fruits": ("🍏", "Фрукты", [2, 2, 2, 1, 0, 0, 0, -1]),
    "vegetables": ("🍆", "Овощи", [2, 2, 2, 1, 0, 0, 0, -1]),
    "greens": ("🌿", "Зелень", [2, 2, 2, 1, 0, 0, 0, -1]),
    "meat": ("🥩", "Мясо", [2, 2, 1, 0, 0, -1, -2, -2]),
    "dairy": ("🥛", "Молочка", [2, 2, 1, 0, -1, -2, -2, -2]),
    "cheese": ("🧀", "Сыры", [2, 0, -1, -2, -2, -2, -2, -2]),
    "nuts": ("🥜", "Орехи", [2, 0, -1, -2, -2, -2, -2, -2]),
    "oil": ("🧈", "Масло", [1, 0, 0, -1, -2, -2, -2, -2]),
    "whole-grains": ("🌾", "ЦЗ", [2, 2, 1, 0, -1, -1, -1, -2]),
    "legumes": ("🌱", "Бобовые", [2, 2, 1, 0, -1, -1, -1, -2]),
    "potatoes": ("🥔", "Картофель", [2, 2, 1, 0, -1, -1, -1, -2]),
    "other-sides": ("🍚", "Др. гарниры", [0, -1, -2, -2, -2, -2, -2, -2]),
    "sweets": ("🍰", "Сладости", [-2, -2, -2, -2, -2, -2, -2, -2]),
    "drinks": ("🥤", "Напитки", [-2, -2, -2, -2, -2, -2, -2, -2]),
    "alcohol": ("🍺", "Алкоголь", [-2, -2, -2, -2, -2, -2, -2, -2]),
    "fried": ("🍟", "Жареное", [-2, -2, -2, -2, -2, -2, -2, -2]),
    "processed-meat": ("🌭", "Типа мясо", [-2, -2, -2, -2, -2, -2, -2, -2]),
}

DQS_SCORE_TABLES = {
    "full": list(DQS_SCORE_CATEGORIES),
    "plants": ["fruits", "vegetables", "greens"],
    "protein": ["meat", "dairy"],
    "fats": ["cheese", "nuts", "oil"],
    "side-dishes": ["whole-grains", "legumes", "potatoes", "other-sides"],
    "unhealthy": ["sweets", "drinks", "alcohol", "fried", "processed-meat"],
}


def render_score_table(arguments: list[str]) -> str:
    if len(arguments) != 1 or arguments[0] not in DQS_SCORE_TABLES:
        raise HTTPException(422, "Неизвестная таблица DQS")
    rows = []
    for category_id in DQS_SCORE_TABLES[arguments[0]]:
        icon, name, scores = DQS_SCORE_CATEGORIES[category_id]
        cells = "".join(
            f'<td class="score-{score}">{"+" if score > 0 else ""}{score}</td>'
            for score in scores
        )
        rows.append(f"<tr><th><span>{icon}</span>{escape(name)}</th>{cells}</tr>")
    headings = "".join(f"<th>#{number}</th>" for number in range(1, 9))
    return (
        '<div class="dqs-score-table-wrap"><table class="dqs-score-table">'
        f"<thead><tr><th>Категория</th>{headings}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_slider(arguments: list[str]) -> str:
    if not 2 <= len(arguments) <= 20:
        raise HTTPException(422, "Слайдер принимает от 2 до 20 изображений")
    if any(not safe_image_src(url, allow_relative=True) for url in arguments):
        raise HTTPException(422, "Слайдер принимает только безопасные HTTPS или локальные изображения")
    slides = "".join(
        f'<figure class="gallery-slide"><img src="{escape(url, quote=True)}" alt="" loading="lazy"></figure>'
        for url in arguments
    )
    dots = "".join(
        f'<button class="gallery-dot{" active" if index == 0 else ""}" data-slide="{index}" aria-label="Изображение {index + 1}"></button>'
        for index in range(len(arguments))
    )
    return (
        '<section class="article-gallery" data-gallery="true" data-component="image-slider">'
        f'<div class="gallery-window"><div class="gallery-track">{slides}</div>'
        '<button class="gallery-arrow gallery-prev" aria-label="Предыдущее изображение">‹</button>'
        '<button class="gallery-arrow gallery-next" aria-label="Следующее изображение">›</button></div>'
        f'<div class="gallery-footer"><span class="gallery-counter">1 / {len(arguments)}</span>'
        f'<div class="gallery-dots">{dots}</div></div></section>'
    )


def render_spoiler(arguments: list[str]) -> str:
    if not 2 <= len(arguments) <= 40:
        raise HTTPException(422, "Спойлер принимает заголовок и от 1 до 39 строк текста")
    title, *paragraphs = arguments
    return (
        '<details class="article-spoiler">'
        f"<summary>{inline_markdown(title)}</summary>"
        '<div class="article-spoiler-body">'
        + "".join(f"<p>{inline_markdown(paragraph)}</p>" for paragraph in paragraphs)
        + "</div></details>"
    )


def render_masterclass_component(name: str, arguments: list[str]) -> str:
    if name == "slider":
        return render_slider(arguments)
    if name == "dqs_score_table":
        return render_score_table(arguments)
    if name == "spoiler":
        return render_spoiler(arguments)
    raise HTTPException(422, f"Неизвестный компонент материала: {name}")
