"""Add a readable editorial layer to the private Telegram Saved Messages corpus.

This is intentionally a navigational layer: it does not replace the reversible
source classification and never removes a message from the archive.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SPACE = re.compile(r"\s+")
URL = re.compile(r"https?://[^\s<>]+|tg://\S+", re.I)
TASK_VERB = re.compile(
    r"\b(?:сделать|написать|дописать|запустить|настроить|ответить|узнать|подобрать|"
    r"собрать|создать|завести|обновить|переделать|зарегистрировать|проверить|купить|"
    r"позвонить|заказать|поставить|дочекать|редачить|искать|добавить|составить)\b",
    re.I,
)
TASK_CONTEXT = re.compile(r"\b(?:план|задач|todo|контент[ -]?план|на неделю|сегодня|завтра|надо)\b", re.I)
# Telegram exports often flatten a numbered checklist into one line, hence the
# whitespace alternative in addition to genuine line starts.
LIST_ITEM = re.compile(r"(?:^|\n|\s)(?:\d{1,2}[.)]|[-•✅])\s+", re.M)

TOPICS: dict[str, re.Pattern[str]] = {
    "похудение и питание": re.compile(r"похуд|калори|питан|еда\b|дефицит|сладк|голод|сытост|переедан|диет", re.I),
    "тренировки и движение": re.compile(r"трениров|зал\b|бег\b|спорт|упражнен|мышц|вынослив", re.I),
    "контент и редактура": re.compile(r"пост\b|стать[ья]|контент|хук|заголов|пикабу|телеграф|канал\b|рилс|reels", re.I),
    "продажи и воронки": re.compile(r"воронк|продаж|оффер|реклам|лид|консультац|прогрев|подпис", re.I),
    "продукт и обучение": re.compile(r"курс\b|урок\b|интенсив|бот\b|мастер-класс|мк\b", re.I),
    "личное и быт": re.compile(r"ноутбук|кекс|собак|квартир|поездк|здоровье|семь[яи]|друз", re.I),
}


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("editorial catalog paths must be outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def write_markdown_view(path: Path, title: str, rows: list[dict[str, Any]]) -> None:
    """Make the private catalogue usable as plain text, not only as JSONL."""
    lines = [f"# {title}", "", f"Записей: {len(rows)}. Поиск по файлу: Ctrl+F. Это навигатор, полный исходный текст остаётся в одноимённом JSONL.", ""]
    for row in rows:
        date = str(row.get("published_at") or "без даты")[:10]
        topics_text = ", ".join(row.get("topic_tags") or [])
        excerpt = SPACE.sub(" ", str(row.get("text_plain") or ""))[:360]
        lines += [f"## {date} · {topics_text} · message_id {row.get('message_id')}", "", excerpt or "_Нет текстового тела: откройте исходное сообщение._", ""]
        if row.get("source_url"):
            lines += [f"Источник: {row['source_url']}", ""]
        lines += [f"Что делать: {row['recommended_action']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def task_score(text: str) -> int:
    verbs = len(TASK_VERB.findall(text))
    list_items = len(LIST_ITEM.findall(text))
    context = bool(TASK_CONTEXT.search(text))
    if list_items >= 2 and verbs >= 1 and len(text) < 1800:
        return 3
    if context and verbs >= 2 and len(text) < 1200:
        return 2
    return 0


def topics(text: str) -> list[str]:
    return [label for label, pattern in TOPICS.items() if pattern.search(text)] or ["без явной темы"]


def classify_editorially(card: dict[str, Any]) -> tuple[str, str, str]:
    text = str(card.get("text_plain") or "")
    original = card["classification"]
    if original == "external_reference":
        return "reference", "внешний материал", "Сохраняйте как источник идеи или факта; не используйте как образец авторского голоса."
    if original == "unknown_review":
        return "needs_triage", "медиа или пустой контекст", "Открыть исходное сообщение: текста недостаточно, чтобы понять его пользу."
    if task_score(text) >= 2:
        return "task_or_project", "список дел / рабочий план", "Не читать как пост: извлечь только незавершённые или повторно полезные задачи в текущий план."
    if original == "nutrition_or_content_idea":
        return "content_idea", "идея / хук / наблюдение", "Использовать как затравку для нового материала; сначала проверить, не раскрыта ли тема в готовых постах."
    if original == "template_or_mechanic":
        return "content_mechanic", "шаблон / структура / приём", "Брать конструкцию, а не формулировки; адаптировать под текущий продукт и фактологию."
    if original in {"authored_ready_post", "authored_draft_or_fragment"}:
        if len(text) >= 600:
            return "post_or_substantial_draft", "готовый пост или большой черновик", "Кандидат для поиска, разбора голоса и повторного использования после проверки актуальности фактов."
        return "content_fragment", "фрагмент авторского текста", "Использовать как отдельную мысль, разворот или основу нового поста, а не как готовую публикацию."
    if URL.fullmatch(text.strip()):
        return "reference", "ссылка-закладка", "Открыть ссылку и вручную решить: это источник, материал автора или уже неактуальная закладка."
    return "personal_archive", "личное / прочее", "Не включать в авторский корпус; оставить в архиве на случай будущего поиска."


def make_card(card: dict[str, Any]) -> dict[str, Any]:
    kind, label, action = classify_editorially(card)
    return {
        **card,
        "editorial_kind": kind,
        "editorial_label": label,
        "topic_tags": topics(card.get("text_plain") or ""),
        "recommended_action": action,
    }


OUTPUTS = {
    "posts-and-substantial-drafts.jsonl": {"post_or_substantial_draft", "content_fragment"},
    "content-ideas-and-hooks.jsonl": {"content_idea", "content_mechanic"},
    "task-lists-and-projects.jsonl": {"task_or_project"},
    "references-and-links.jsonl": {"reference"},
    "personal-and-archive.jsonl": {"personal_archive"},
}


def guide(rows: list[dict[str, Any]], output: Path) -> str:
    by_kind = Counter(row["editorial_kind"] for row in rows)
    by_topic = Counter(topic for row in rows for topic in row["topic_tags"])
    lines = [
        "# Навигатор по сохранённым заметкам", "",
        "Это не новая чистка и не решение, какие тексты «хорошие». Это удобная карта поверх полного архива: каждая строка по-прежнему ссылается на исходное message_id.", "",
        "## С чего начать", "",
        "1. Если нужен старый пост или сильная мысль — откройте `posts-and-substantial-drafts.jsonl` и фильтруйте по `topic_tags`.",
        "2. Если нужно придумать новый контент — начните с `content-ideas-and-hooks.jsonl`; это сырьё, а не готовые публикации.",
        "3. Если ищете старые планы — используйте `task-lists-and-projects.jsonl`. Это исторические списки дел: не переносите их автоматически в текущую работу.",
        "4. Чужие тексты и одиночные ссылки лежат в `references-and-links.jsonl`: они помогают искать подходы и факты, но не участвуют в обучении голоса.",
        "5. `needs-human-triage.jsonl` — все записи с `needs_review`: медиа-зависимые, короткие и спорные случаи. Файл пересекается с другими рубриками специально.", "",
        "## Что означают рубрики", "",
        "- **Готовый пост / большой черновик** — текст достаточно длинный, чтобы читать его как самостоятельный материал. Перед повторным использованием проверяйте факты, дату и CTA.",
        "- **Фрагмент** — мысль, подводка, аргумент или мини-черновик. Полезен как материал для нового текста, но не обязательно как публикация целиком.",
        "- **Идея / хук** — тема, наблюдение или заготовка. Лучше сначала искать готовые материалы по той же теме, затем решать: повторять, обновлять или развивать.",
        "- **Шаблон / механика** — способ построить сообщение, воронку или продажу. Берите логику, не копируйте формулировки без проверки контекста.",
        "- **Список дел / проект** — историческое планирование. Он отвечает «что тогда хотел сделать», а не «что сейчас нужно делать».",
        "- **Референс / ссылка** — внешний источник или закладка. Не образец голоса автора.",
        "- **Личное / архив** — сознательно сохранено, но не попадает в рабочий авторский слой.", "",
        "## Количества", "",
    ]
    lines.extend(f"- {kind}: {count}" for kind, count in sorted(by_kind.items()))
    lines += ["", "## Темы, которые чаще всего встречаются", ""]
    lines.extend(f"- {topic}: {count}" for topic, count in by_topic.most_common())
    lines += ["", "## Как не утонуть", "", "Не открывайте `all-messages.jsonl` для обычной работы. Это аудит-архив. Рабочий вход — нужный файл-рубрика, затем поле `topic_tags`, потом `text_plain`; `message_id` позволяет вернуться к оригиналу в Telegram при необходимости.", "", "## Важная оговорка", "", "Рубрики получены по прозрачным правилам и ускоряют первый проход, но не заменяют редакторское решение. Особенно осторожно относитесь к старым задачам, ссылкам без описания и медиа-зависимым записям."]
    return "\n".join(lines) + "\n"


def run(source: Path, output: Path) -> dict[str, Any]:
    rows = [make_card(card) for card in read_jsonl(source)]
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "editorial-catalog.jsonl", rows)
    for filename, kinds in OUTPUTS.items():
        selected = [row for row in rows if row["editorial_kind"] in kinds]
        write_jsonl(output / filename, selected)
        write_markdown_view(output / filename.replace(".jsonl", ".md"), filename.removesuffix(".jsonl").replace("-", " "), selected)
    triage = [row for row in rows if row.get("needs_review")]
    write_jsonl(output / "needs-human-triage.jsonl", triage)
    write_markdown_view(output / "needs-human-triage.md", "Очередь внимательной проверки", triage)
    (output / "EDITORIAL_CATALOG_GUIDE.md").write_text(guide(rows, output), encoding="utf-8")
    report = {
        "source_cards": len(rows),
        "by_editorial_kind": dict(sorted(Counter(row["editorial_kind"] for row in rows).items())),
        "by_topic": dict(Counter(topic for row in rows for topic in row["topic_tags"]).most_common()),
        "output": str(output),
    }
    (output / "editorial-catalog-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build readable editorial views of private saved Telegram notes")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(private(args.source), private(args.output)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
