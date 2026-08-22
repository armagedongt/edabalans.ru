from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .database import ArchiveDB
from .parser import text_to_markdown


def _yaml(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_content_files(parsed: dict[str, Any], data_dir: Path) -> None:
    scenario_id = parsed["scenario_id"]
    target_dir = data_dir / "parsed" / "content" / str(scenario_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    for block in parsed["blocks"]:
        if not block.get("text_raw"):
            continue
        relative = f"content/{scenario_id}/block_{block['block_id']}.md"
        block["content_file"] = relative
        body = (
            "---\n"
            f"scenario_id: {_yaml(scenario_id)}\n"
            f"scenario_name: {_yaml(parsed.get('scenario_name'))}\n"
            f"block_id: {_yaml(block['block_id'])}\n"
            f"classification: {_yaml(block['classification'])}\n"
            "---\n\n"
            f"{text_to_markdown(block.get('text_raw'))}\n"
        )
        (data_dir / "parsed" / relative).write_text(body, encoding="utf-8", newline="\n")


def scenario_report(parsed: dict[str, Any]) -> str:
    blocks = parsed["blocks"]
    counts = Counter(block["classification"] for block in blocks)
    detached = parsed.get("detached_components", [])
    delays = [edge for edge in parsed["edges"] if edge.get("delay_seconds") is not None]
    conditions = [edge for edge in parsed["edges"] if edge.get("conditions")]
    text_blocks = [block for block in blocks if block.get("text_raw")]
    lines = [
        f"# {parsed.get('scenario_name') or 'Сценарий без названия'}",
        "",
        f"ID: {parsed['scenario_id']}",
        "",
        f"Всего блоков: {len(blocks)}",
        "",
        "## Основной поток",
        "",
        f"{counts['main_flow']} блоков; старт: `{parsed.get('main_start_block_id')}`.",
        "",
        "## Отдельные компоненты",
        "",
    ]
    if detached:
        by_id = {block["block_id"]: block for block in blocks}
        for component in detached:
            samples = []
            for block_id in component["block_ids"]:
                block = by_id[block_id]
                preview = block.get("name") or block.get("text_plain") or block.get("type") or "без названия"
                samples.append(str(preview).replace("\n", " ")[:100])
                if len(samples) == 3:
                    break
            lines.append(
                f"- Компонента {component['component_id']}: {len(component['block_ids'])} блоков — "
                + "; ".join(samples)
            )
    else:
        lines.append("Нет.")
    lines += [
        "",
        "## Одиночные блоки",
        "",
        f"Orphan: {counts['orphan']}; возможный внешний вход: {counts['unknown_external_entry']}.",
        "",
        "## Задержки",
        "",
    ]
    lines.extend(
        [f"- `{edge['from_block']}` → `{edge['to_block']}`: `{edge['delay_seconds']}`" for edge in delays]
        or ["Не найдены в восстановленных переходах."]
    )
    lines += ["", "## Условия", ""]
    lines.extend(
        [f"- `{edge['from_block']}` → `{edge['to_block']}`: `{json.dumps(edge['conditions'], ensure_ascii=False)[:300]}`" for edge in conditions]
        or ["Не найдены в восстановленных переходах."]
    )
    tags = sum((block.get("tags", []) for block in blocks), [])
    variables = sum((block.get("variables", []) for block in blocks), [])
    lines += [
        "",
        "## Теги",
        "",
        f"Извлечено записей: {len(tags)}.",
        "",
        "## Переменные",
        "",
        f"Извлечено записей: {len(variables)}.",
        "",
        "## Текстовые блоки",
        "",
    ]
    for block in text_blocks:
        preview = (block.get("text_plain") or "").replace("\n", " ")[:160]
        lines.append(f"- `{block['block_id']}` [{block['classification']}]: {preview}")
    if not text_blocks:
        lines.append("Нет.")
    return "\n".join(lines) + "\n"


def write_scenario_report(parsed: dict[str, Any], data_dir: Path) -> None:
    target = data_dir / "reports" / f"{parsed['scenario_id']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(scenario_report(parsed), encoding="utf-8", newline="\n")


def rebuild_indexes(db: ArchiveDB, data_dir: Path) -> None:
    rows = db.content_rows()
    index = [
        {
            "scenario_id": row["scenario_id"],
            "scenario_name": row["scenario_name"],
            "block_id": int(row["block_id"]) if str(row["block_id"]).isdigit() else row["block_id"],
            "block_name": row["block_name"],
            "classification": row["classification"],
            "preview": (row["text_plain"] or "")[:200],
            "file": row["markdown_file"],
        }
        for row in rows
    ]
    target = data_dir / "parsed" / "content_index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    summary = db.summary()
    lines = [
        "# Сводка экспорта LeadTeh",
        "",
        f"Папок: {summary['folders']}",
        f"Сценариев: {summary['scenarios']}",
        f"Скачано PASS 1: {summary['passes'].get('priority', 0)}",
        f"Скачано PASS 2: {summary['passes'].get('archive', 0)}",
        f"Ошибок: {len(summary['errors'])}",
        f"Всего блоков: {summary['blocks']}",
        f"Текстовых блоков: {summary['texts']}",
        f"Main flow: {summary['classifications'].get('main_flow', 0)}",
        f"Detached: {summary['classifications'].get('detached_component', 0)}",
        f"Orphan: {summary['classifications'].get('orphan', 0)}",
        f"Unknown external entry: {summary['classifications'].get('unknown_external_entry', 0)}",
        "",
        "## Сценарии",
        "",
    ]
    for row in summary["scenario_rows"]:
        suffix = f" — ошибка: {row['error']}" if row.get("error") else ""
        lines.append(f"- `{row['id']}` {row.get('name') or 'без названия'}: {row['block_count']} блоков, {row['status']}{suffix}")
    (data_dir / "reports" / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
