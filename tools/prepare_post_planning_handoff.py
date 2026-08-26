"""Extract only author-owned post-planning material from the private editorial catalog."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


CONTENT_TASK = re.compile(
    r"\b(?:пост|стать[ья]|контент|пикабу|телеграм|канал\b|рилс|reels|заголов|хук|"
    r"план\s+пост|контент[ -]?план|прогрев|рассылк|подводк|cta|призыв)\b",
    re.I,
)
SOURCE_CLASSIFICATIONS = {
    "authored_ready_post", "authored_draft_or_fragment",
    "nutrition_or_content_idea", "template_or_mechanic",
}


def private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("post-planning handoff paths must be outside Git")
    return resolved


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def instructions(source_count: int, task_count: int) -> str:
    return f"""# Передача: материалы для планирования постов

## Что здесь есть

`post-planning-source.jsonl` содержит {source_count} **собственных** материалов: готовые посты, большие и малые черновики, идеи, хуки и контентные механики. Это основной файл для подбора/написания постов.

`post-planning-needs-context.jsonl` — пересекающаяся подборка из основного файла: короткие, медиа-зависимые и иные записи с `needs_review=true`. Не выбрасывайте их, но не считайте их полный смысл доступным по одному тексту.

`content-tasks-from-old-plans.jsonl` содержит {task_count} исторических записей со словами о постах, статьях, каналах, контент-планах и рассылках. Это не текущий backlog: брать оттуда только нераскрытые темы и направления, не переносить старые действия как актуальные задачи.

## Чего здесь намеренно нет

- внешних постов, ссылок и пересылок — они не являются голосом автора;
- личного и технического архива;
- произвольных старых задач без связи с контентом.

## Как работать

1. Сначала найдите в `post-planning-source.jsonl` 3–7 материалов по теме через `topic_tags`, `editorial_kind` и `text_plain`.
2. Откройте связанные варианты по `related_message_ids` и не принимайте точный дубль за новую идею.
3. Если у строки `needs_review=true`, считайте текст только частичной подсказкой и при важном использовании откройте оригинал по `message_id`. Разделяйте: факт из текущего брифа, голос/подача из старого материала и структура из шаблона. Не переносите старые офферы, цены, CTA и медицинские утверждения без проверки.
4. Если тема уже есть в готовом посте, предложите не простой повтор, а новый угол, аудиторию или место в цепочке.
5. При необходимости вернитесь к исходной записи по `message_id`; это ссылка на архив, а не повод изменять его.

## Границы

Материалы read-only, локальные и вне Git. Не публиковать и не изменять Telegram. Не считать этот набор паспортом голоса: он лишь даёт кандидатов для планирования и последующей редакторской оценки.
"""


def run(source: Path, output: Path) -> dict[str, Any]:
    rows = read_jsonl(source)
    # The source classification owns author relevance.  Editorial kinds are a
    # convenience view and can legitimately call a numbered post a task list.
    planning = [row for row in rows if row.get("classification") in SOURCE_CLASSIFICATIONS]
    old_content_tasks = [
        row for row in rows
        if row.get("editorial_kind") == "task_or_project"
        and row.get("classification") not in SOURCE_CLASSIFICATIONS
        and CONTENT_TASK.search(str(row.get("text_plain") or ""))
    ]
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "post-planning-source.jsonl", planning)
    write_jsonl(output / "post-planning-needs-context.jsonl", [row for row in planning if row.get("needs_review")])
    write_jsonl(output / "content-tasks-from-old-plans.jsonl", old_content_tasks)
    (output / "INSTRUCTIONS_FOR_POST_PLANNING_CHAT.md").write_text(instructions(len(planning), len(old_content_tasks)), encoding="utf-8")
    report = {
        "post_planning_source": len(planning),
        "by_source_classification": dict(sorted(Counter(row["classification"] for row in planning).items())),
        "needs_context": sum(bool(row.get("needs_review")) for row in planning),
        "old_content_tasks": len(old_content_tasks),
        "output": str(output),
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a private handoff for post planning")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(private(args.source), private(args.output)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
