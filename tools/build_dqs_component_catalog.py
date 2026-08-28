"""Extract reusable DQS authoring components from the legacy source.

The legacy text remains untouched. This tool produces the Markdown source used by
the course and a small component catalogue for future authoring.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "content/masterclass/source-current/13-dqs-system.txt"
MARKDOWN = ROOT / "content/masterclass/source-current/13-dqs-system.md"
COMPONENTS = ROOT / "content/masterclass/components"
SLIDER_DIR = COMPONENTS / "dqs-image-slider"
CATEGORY_DIR = COMPONENTS / "dqs-product-categories"
SCORE_TABLE_DIR = COMPONENTS / "dqs-score-tables"

CATEGORY_HEADING_ICONS = {
    "Фрукты и овощи": "🍏",
    "Зелень и пряные растения": "🌿",
    "Мясо, птица, рыба, яйца и морепродукты": "🥩",
    "Диетические молочные продукты (молочка)": "🥛",
    "Сыры и жирная молочка": "🧀",
    "Орехи и семена": "🥜",
    "Масло и другие добавленные жиры": "🧈",
    "Цельные злаки": "🌾",
    "Бобовые": "🌱",
    "Картофель": "🥔",
    "Другие гарниры": "🍚",
    "Сладкое": "🍰",
    "Сладкие и калорийные напитки": "🥤",
    "Алкоголь": "🍺",
    "Жареное во фритюре, кляре и панировке": "🍟",
    "Переработанное мясо и рыба": "🌭",
}


SLIDER_CSS = """/* Каноническое оформление галерей материалов и компонента slider(...). */
.article-gallery { margin-top: 52px; }
.article-gallery h2 { margin: 0 0 14px; }
.gallery-window { position: relative; overflow: hidden; border-radius: 22px; background: #e9e2d8; box-shadow: var(--shadow); touch-action: pan-y; }
.gallery-track { display: flex; transition: transform .28s ease; }
.gallery-slide { flex: 0 0 100%; margin: 0 !important; display: grid; place-items: center; min-height: 280px; background: #eee8df; }
.gallery-slide img { display: block; width: 100%; height: auto; max-height: 72vh; object-fit: contain; margin: 0 !important; border-radius: 0 !important; }
.gallery-slide figcaption { width: 100%; padding: 10px 15px; background: #fffaf2; color: var(--muted); font-size: var(--text-xs); }
.gallery-arrow { position: absolute; top: 50%; z-index: 2; display: grid; place-items: center; width: 44px; height: 44px; border: 0; border-radius: 50%; background: #fffdf8e8; color: var(--ink); box-shadow: 0 5px 18px #261b1340; cursor: pointer; transform: translateY(-50%); font-size: var(--text-title); }
.gallery-prev { left: 12px; }
.gallery-next { right: 12px; }
.gallery-footer { display: flex; align-items: center; gap: 13px; margin-top: 12px; }
.gallery-counter { flex: 0 0 auto; color: var(--muted); font-size: var(--text-xs); font-weight: var(--weight-bold); }
.gallery-dots { display: flex; gap: 6px; overflow-x: auto; padding: 5px 2px; scrollbar-width: none; }
.gallery-dot { flex: 0 0 auto; width: 7px; height: 7px; padding: 0; border: 0; border-radius: 50%; background: #c8beb0; cursor: pointer; }
.gallery-dot.active { background: var(--accent); transform: scale(1.35); }
"""

SLIDER_JS = """// Каноническое поведение всех галерей материалов, включая slider(...).
(function (global) {
  'use strict';

  function bindGallery(scope) {
    (scope || document).querySelectorAll('[data-gallery]').forEach(function (root) {
      if (root.dataset.galleryBound === 'true') return;
      var track = root.querySelector('.gallery-track');
      var slides = root.querySelectorAll('.gallery-slide');
      var counter = root.querySelector('.gallery-counter');
      var dots = root.querySelectorAll('.gallery-dot');
      var index = 0;
      var startX = 0;
      if (!track || !slides.length) return;

      function show(next) {
        index = (next + slides.length) % slides.length;
        track.style.transform = 'translateX(-' + (index * 100) + '%)';
        if (counter) counter.textContent = (index + 1) + ' / ' + slides.length;
        dots.forEach(function (dot, dotIndex) {
          dot.classList.toggle('active', dotIndex === index);
        });
        var active = dots[index];
        if (active && active.scrollIntoView) {
          active.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
      }

      var previous = root.querySelector('.gallery-prev');
      var next = root.querySelector('.gallery-next');
      if (previous) previous.onclick = function () { show(index - 1); };
      if (next) next.onclick = function () { show(index + 1); };
      dots.forEach(function (dot) {
        dot.onclick = function () { show(Number(dot.dataset.slide)); };
      });
      var windowElement = root.querySelector('.gallery-window');
      if (windowElement) {
        windowElement.addEventListener('pointerdown', function (event) { startX = event.clientX; });
        windowElement.addEventListener('pointerup', function (event) {
          var shift = event.clientX - startX;
          if (Math.abs(shift) > 45) show(index + (shift < 0 ? 1 : -1));
        });
      }
      root.dataset.galleryBound = 'true';
      show(0);
    });
  }

  global.bindGallery = bindGallery;
})(window);
"""


def normalized_markdown(text: str) -> str:
    """Perform presentation-only conversion; all author words stay unchanged."""
    text = text.replace("\r\n", "\n")
    text = text.replace("<br />", "\n\n").replace("<br/>", "\n\n").replace("<br>", "\n\n")
    # Service-editor residue surrounding the old inline code, not author text.
    text = text.replace("Код будет выполнен на опубликованной странице", "")
    text = text.replace("1234567891011121314151617", "")
    text = re.sub(r"\d{100,}", "", text)
    text = re.sub(r"[\u05d4\u00a0\s]{100,}", "\n\n", text)
    text = re.sub(r"X{100,}", "", text)
    text = re.sub(r"(?m)^→\s+(.+)$", r"## \1", text)
    text = re.sub(r"(?m)^Примеры$", "## Примеры", text)
    text = re.sub(r"(?m)^Блюда, которые могут встретиться у вас дома:$", r"### Блюда, которые могут встретиться у вас дома:", text)
    text = re.sub(r"(?m)^Блюда, которые вы можете купить вне дома:$", r"### Блюда, которые вы можете купить вне дома:", text)
    lines = text.splitlines()
    if lines and lines[0].strip():
        lines[0] = "# " + lines[0].strip()
    return "\n".join(lines).strip() + "\n"


def slider_call(name: str, markup: str) -> str:
    urls = re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', markup)
    if not urls:
        raise ValueError(f"Gallery {name} has no images")
    return "\n\n".join((
        f"<!-- Слайдер DQS: {name}. Управляющий код: components/dqs-image-slider/. -->",
        "slider(\n" + "\n".join(urls) + "\n)",
    ))


def replace_galleries(source: str) -> tuple[str, dict[str, str]]:
    pattern = re.compile(
        r'(?P<markup><div class="dqs-gallery dqs-gallery-(?P<name>[^"]+)">.*?</div>)'
        r'\s*<style>.*?</style>\s*<script>.*?</script>',
        re.S,
    )
    found: dict[str, str] = {}

    def replacement(match: re.Match[str]) -> str:
        name = match.group("name")
        found[name] = match.group("markup")
        return slider_call(name, match.group("markup"))

    result, count = pattern.subn(replacement, source)
    if count != 2 or set(found) != {"home", "takeout"}:
        raise ValueError(f"Expected home and takeout galleries, got {sorted(found)}")
    return result, found


def category_slug(title: str) -> str:
    transliteration = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        "А": "a", "Б": "b", "В": "v", "Г": "g", "Д": "d", "Е": "e", "Ё": "e", "Ж": "zh", "З": "z", "И": "i", "Й": "y", "К": "k", "Л": "l", "М": "m", "Н": "n", "О": "o", "П": "p", "Р": "r", "С": "s", "Т": "t", "У": "u", "Ф": "f", "Х": "h", "Ц": "ts", "Ч": "ch", "Ш": "sh", "Щ": "sch", "Ъ": "", "Ы": "y", "Ь": "", "Э": "e", "Ю": "yu", "Я": "ya",
    })
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.translate(transliteration).lower())).strip("-")


def category_heading_title(value: str) -> str:
    """Return a category title without the old arrow or its presentation icon."""
    return re.sub(r"^[^\w]+", "", value, flags=re.UNICODE).strip()


def category_heading_index(markdown: str, title: str) -> int:
    """Find a category H2 regardless of an old arrow or the current DQS icon."""
    expected = title.casefold()
    matches = [
        match.start()
        for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown)
        if category_heading_title(match.group(1)).casefold() == expected
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one DQS category heading for {title!r}, got {len(matches)}")
    return matches[0]


def write_category_inserts(markdown: str) -> list[tuple[str, str, str]]:
    """Store the authoring inserts at the same useful level as the page blocks."""
    if CATEGORY_DIR.exists():
        shutil.rmtree(CATEGORY_DIR)
    CATEGORY_DIR.mkdir(parents=True)
    positions = {
        "plants": markdown.index('Начнем с блока "растения"'),
        "protein": category_heading_index(markdown, "Мясо, птица, рыба, яйца и морепродукты"),
        "fats": category_heading_index(markdown, "Сыры и жирная молочка"),
        "carbs": category_heading_index(markdown, "Цельные злаки"),
        "less_useful": category_heading_index(markdown, "Сладкое"),
        "examples": markdown.index("## Примеры"),
    }
    cheatsheet_start = markdown.index("Шпаргалка по порциям", positions["less_useful"])
    inserts = [
        ("01-full-dqs-material.md", "Полный материал DQS", "Вставь полный материал DQS", markdown),
        ("02-plants-fruits-vegetables-greens.md", "Растения: фрукты, овощи и зелень", "Вставь блок про растения", markdown[positions["plants"]:positions["protein"]]),
        ("03-protein.md", "Белок: мясо, рыба, яйца и диетическая молочка", "Вставь блок про белок", markdown[positions["protein"]:positions["fats"]]),
        ("04-fats.md", "Жиры: сыры, жирная молочка, орехи и масло", "Вставь блок про жиры", markdown[positions["fats"]:positions["carbs"]]),
        ("05-carbs-and-side-dishes.md", "Гарниры: цельные злаки, бобовые, картофель и другие", "Вставь блок про гарниры", markdown[positions["carbs"]:positions["less_useful"]]),
        ("06-sweets-drinks-alcohol-and-processed-food.md", "Сладкое, напитки, алкоголь, жареное и переработанное мясо", "Вставь блок про вредные категории", markdown[positions["less_useful"]:cheatsheet_start]),
        ("07-portion-cheatsheet.md", "Шпаргалка по порциям DQS", "Вставь шпаргалку по порциям DQS", markdown[cheatsheet_start:positions["examples"]]),
    ]
    for filename, _, _, fragment in inserts:
        (CATEGORY_DIR / filename).write_text(fragment.strip() + "\n", encoding="utf-8")
    return [(filename, title, command) for filename, title, command, _ in inserts]


def componentized_article(markdown: str) -> str:
    """Keep the course source readable: calls here, full DQS blocks in the catalogue."""
    positions = {
        "plants": markdown.index('Начнем с блока "растения"'),
        "protein": category_heading_index(markdown, "Мясо, птица, рыба, яйца и морепродукты"),
        "fats": category_heading_index(markdown, "Сыры и жирная молочка"),
        "carbs": category_heading_index(markdown, "Цельные злаки"),
        "less_useful": category_heading_index(markdown, "Сладкое"),
        "examples": markdown.index("## Примеры"),
    }
    cheatsheet = markdown.index("Шпаргалка по порциям", positions["less_useful"])
    ranges = [
        (positions["plants"], positions["protein"], "plants"),
        (positions["protein"], positions["fats"], "protein"),
        (positions["fats"], positions["carbs"], "fats"),
        (positions["carbs"], positions["less_useful"], "carbs-and-side-dishes"),
        (positions["less_useful"], cheatsheet, "sweets-drinks-alcohol-and-processed-food"),
        (cheatsheet, positions["examples"], "portion-cheatsheet"),
    ]
    for start, end, name in reversed(ranges):
        call = f"dqs_categories(\n{name}\n)\n\n"
        markdown = markdown[:start] + call + markdown[end:]
    return markdown


def score_table_article_calls(markdown: str) -> str:
    """Add visual score-table calls without moving or removing author text."""
    if markdown.count("Что такое порция?") != 1:
        raise ValueError("Expected one DQS table insertion point for 'Что такое порция?'")
    markdown = markdown.replace("Что такое порция?", "dqs_score_table(\nfull\n)\n\nЧто такое порция?")
    for title, call in reversed((
        ("Фрукты и овощи", "dqs_score_table(\nplants\n)\n\n"),
        ("Мясо, птица, рыба, яйца и морепродукты", "dqs_score_table(\nprotein\n)\n\n"),
        ("Сыры и жирная молочка", "dqs_score_table(\nfats\n)\n\n"),
        ("Цельные злаки", "dqs_score_table(\nside-dishes\n)\n\n"),
        ("Сладкое", "dqs_score_table(\nunhealthy\n)\n\n"),
    )):
        position = category_heading_index(markdown, title)
        markdown = markdown[:position] + call + markdown[position:]
    return markdown


def structure_only_format(markdown: str) -> str:
    """Restore readable Markdown presentation without changing author characters."""
    replacements = (
        ("Что такое порция?Если", "## Что такое порция?\n\nЕсли"),
        ("Как считать сложные блюда.", "### Как считать сложные блюда.\n\n"),
        ("Всё яд и все лекарствоВесь", "\n\n## Всё яд и все лекарство\n\nВесь"),
        ("РазнообразиеРазнообразие", "\n\n## Разнообразие\n\nРазнообразие"),
        ("\nПримечания\n", "\n\n### Примечания\n\n"),
        ("\nПримечания:\n", "\n\n### Примечания:\n\n"),
        ("Что НЕ входит в эти категории:", "\n\n### Что НЕ входит в эти категории:\n\n"),
        ("Что НЕ входит в эту категорию:", "\n\n### Что НЕ входит в эту категорию:\n\n"),
        ("Исчерпывающий список:", "\n\n### Исчерпывающий список:\n\n"),
        ("Основные примеры:", "\n\n### Основные примеры:\n\n"),
        ("Шпаргалка по порциям\n", "## Шпаргалка по порциям\n\n"),
        ("Главное, запомните!", "## Главное, запомните!"),
    )
    for source, replacement in replacements:
        markdown = markdown.replace(source, replacement)

    formatted_lines: list[str] = []
    for line in markdown.splitlines():
        plain = line.strip()
        if plain.startswith("## "):
            title = category_heading_title(plain[3:])
            icon = next(
                (value for key, value in CATEGORY_HEADING_ICONS.items() if key.casefold() == title.casefold()),
                None,
            )
            if icon:
                line = f"## {icon} {title}"
                plain = line
        if (
            len(line) > 460
            and not plain.startswith(("#", "<!--", "http", "slider(", "dqs_", ")"))
        ):
            sentences = re.split(r"(?<=[.!?])(?=[А-ЯЁ])", line)
            paragraphs = ["".join(sentences[index:index + 3]) for index in range(0, len(sentences), 3)]
            formatted_lines.extend(paragraphs)
            formatted_lines.append("")
        else:
            formatted_lines.append(line)
    result = "\n".join(formatted_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"(\n#{1,6} [^\n]+)\n\n +", r"\1\n\n", result)
    return result.strip() + "\n"


def write_score_table_catalog() -> None:
    """Create presentation assets; table data stays in the server renderer."""
    SCORE_TABLE_DIR.mkdir(parents=True, exist_ok=True)
    css = """/* DQS: таблицы баллов в учебном материале. */
.dqs-score-table-wrap { overflow-x: auto; margin: 24px 0; padding: 12px; border-radius: 28px; background: #fffdf9; box-shadow: 0 12px 30px rgba(40, 29, 13, .08); }
.dqs-score-table { width: 100%; min-width: 760px; border-collapse: separate; border-spacing: 6px; font: 700 16px/1.2 system-ui, sans-serif; }
.dqs-score-table th, .dqs-score-table td { padding: 14px 10px; border-radius: 15px; text-align: center; background: #faf9f6; }
.dqs-score-table thead th:first-child, .dqs-score-table tbody th { min-width: 190px; text-align: left; }
.dqs-score-table tbody th { background: #fff0e5; font-size: 18px; }
.dqs-score-table tbody th span { display: inline-block; margin-right: 14px; }
.dqs-score-table .score-2 { background: #cfeecb; }.dqs-score-table .score-1 { background: #e1f3ce; }.dqs-score-table .score-0 { background: #fff0bc; }.dqs-score-table .score--1 { background: #ffe2bd; }.dqs-score-table .score--2 { background: #ffd5d2; }
"""
    (SCORE_TABLE_DIR / "score-tables.js").unlink(missing_ok=True)
    (SCORE_TABLE_DIR / "score-tables.css").write_text(css, encoding="utf-8")
    (SCORE_TABLE_DIR / "README.md").write_text(
        "# Таблицы баллов DQS\n\n"
        "Это именно визуальные таблицы категорий и баллов — не авторский текст статьи. "
        "Они вынесены из текущей модели DQS и вставляются в Markdown так:\n\n"
        "```text\ndqs_score_table(\nunhealthy\n)\n```\n\n"
        "Варианты: `full` — все 17 категорий; `plants` — фрукты, овощи и зелень; "
        "`protein` — мясо и молочка; `fats` — сыры, орехи и масло; `side-dishes` — гарниры; "
        "`unhealthy` — сладости, напитки, алкоголь, жареное и типа мясо.\n\n"
        "Человеческая команда: «вставь полную таблицу DQS», «поставь таблицу растений» или "
        "«добавь таблицу вредных категорий».\n\n"
        "Данные и HTML таблицы строит закрытый серверный renderer; здесь хранится только "
        "визуальный CSS, поэтому второго набора баллов в JavaScript нет.\n",
        encoding="utf-8",
    )
    (COMPONENTS / "README.md").write_text(
        "# Каталог вставок для материалов\n\n"
        "## Слайдер изображений\n\n"
        "[Универсальный слайдер DQS](./dqs-image-slider/README.md) — один код без картинок; "
        "ссылки на картинки остаются прямо в статье внутри `slider(...)`.\n\n"
        "## Таблицы баллов DQS\n\n"
        "[Таблицы категорий и баллов](./dqs-score-tables/README.md) — визуальные вставки, как "
        "в таблице со «Сладостями», «Напитками» и «Типа мясом». Авторский текст статьи сюда не вынесен.\n",
        encoding="utf-8",
    )


def write_readmes(inserts: list[tuple[str, str, str]]) -> None:
    SLIDER_DIR.mkdir(parents=True, exist_ok=True)
    (SLIDER_DIR / "slider.css").write_text(SLIDER_CSS, encoding="utf-8")
    (SLIDER_DIR / "slider.js").write_text(SLIDER_JS, encoding="utf-8")
    (SLIDER_DIR / "README.md").write_text(
        "# Слайдер изображений DQS\n\n"
        "Это один универсальный слайдер. В нём **нет картинок**: картинки всегда лежат прямо в статье, "
        "чтобы их можно было увидеть и заменить в Markdown без правки кода.\n\n"
        "В статье слайдер записывается так:\n\n"
        "```text\nslider(\nhttps://…/первая-картинка.png\nhttps://…/вторая-картинка.png\n)\n```\n\n"
        "Человеческая команда: «вставь слайдер с этими картинками», «добавь ещё картинку в слайдер "
        "домашних блюд» или «поставь слайдер после этого абзаца». Код для всех таких случаев один и тот же: "
        "`slider.css` и `slider.js`. Страница курса загружает эти файлы напрямую через "
        "`/course-assets/masterclass/article-components.*`.\n",
        encoding="utf-8",
    )
    rows = "\n".join(
        f"| {title} | [{filename}](./dqs-product-categories/{filename}) | «{command}» |"
        for filename, title, command in inserts
    )
    (COMPONENTS / "README.md").write_text(
        "# Каталог вставок для материалов\n\n"
        "Здесь лежат переиспользуемые куски материалов. Это не отдельные тексты для публикации: "
        "это исходные блоки, которые можно попросить вставить в статью обычными словами.\n\n"
        "## Слайдер изображений\n\n"
        "[Универсальный слайдер DQS](./dqs-image-slider/README.md) — один код без картинок. В самой статье "
        "остаются только ссылки на изображения внутри `slider(...)`.\n\n"
        "## Вставки продуктовых категорий DQS\n\n"
        "Это не разрезание статьи на 16 мелких файлов. Здесь один полный материал и крупные готовые "
        "вставки по смыслу: растения, белок, жиры, гарниры и вредные категории. Текст внутри не сокращён "
        "и не переписан. В DQS-статье они вызываются короткой записью:\n\n"
        "```text\ndqs_categories(\nplants\n)\n```\n\n"
        "| Что это | Файл | Как можно сказать голосом |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n\n"
        "Если нужно изменить не один из этих блоков, а сам принцип работы слайдера, говорить: «поправь "
        "универсальный слайдер DQS». Если нужны только другие картинки — говорить: «поменяй картинки в "
        "слайдере»; код слайдера при этом не трогаем.\n",
        encoding="utf-8",
    )


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    without_galleries, _ = replace_galleries(source)
    markdown = normalized_markdown(without_galleries)
    write_score_table_catalog()
    # The course article keeps every author paragraph. Only visual widgets are
    # represented by calls such as slider(...).
    MARKDOWN.write_text(structure_only_format(score_table_article_calls(markdown)), encoding="utf-8")
    print(f"Created {MARKDOWN.relative_to(ROOT)}")
    print("Created DQS score-table components and one image-slider component")


if __name__ == "__main__":
    main()
