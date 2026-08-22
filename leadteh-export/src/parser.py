from __future__ import annotations

import html
import json
import re
from collections import defaultdict, deque
from typing import Any, Iterable

from bs4 import BeautifulSoup
from markdownify import markdownify


TARGET_KEYS = {
    "next_step_id",
    "next_id",
    "target_id",
    "to_step_id",
    "true_step_id",
    "false_step_id",
    "success_step_id",
    "failure_step_id",
}
URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _as_id(value: object) -> int | str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value) if value.isdigit() else value
    return None


def _walk(value: object, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], object]]:
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, path + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, path + (str(index),))


def _values_for_keys(value: object, names: set[str]) -> list[object]:
    found: list[object] = []
    for path, item in _walk(value):
        if path and path[-1].lower() in names:
            if isinstance(item, list):
                found.extend(item)
            elif item not in (None, "", False):
                found.append(item)
    return found


def _dedupe_json(values: Iterable[object]) -> list[object]:
    result: list[object] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _plain_text(source: str | None) -> str | None:
    if not source:
        return None
    if "<" in source and ">" in source:
        return BeautifulSoup(source, "html.parser").get_text("\n", strip=True)
    return html.unescape(source).strip()


def text_to_markdown(source: str | None) -> str:
    if not source:
        return ""
    if "<" in source and ">" in source:
        return markdownify(source, heading_style="ATX").strip()
    return source.strip()


def _extract_text(step: dict[str, Any]) -> tuple[str | None, str | None]:
    answer = step.get("answer") if isinstance(step.get("answer"), dict) else {}
    candidates: list[str] = []
    for container in (answer, step):
        for key in ("value", "text", "message", "html", "caption", "description"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value)
    raw = max(candidates, key=len) if candidates else None
    html_value = raw if raw and "<" in raw and ">" in raw else None
    return raw, html_value


def _extract_targets(step: dict[str, Any], valid_ids: set[int | str]) -> list[tuple[int | str, dict[str, Any]]]:
    found: list[tuple[int | str, dict[str, Any]]] = []
    for path, value in _walk(step):
        if not path or path[-1].lower() not in TARGET_KEYS:
            continue
        target = _as_id(value)
        if target in valid_ids:
            context: object = step
            if len(path) >= 2:
                context = _get_at_path(step, path[:-1])
            found.append((target, context if isinstance(context, dict) else {"value": context}))
    unique: dict[int | str, dict[str, Any]] = {}
    for target, context in found:
        unique.setdefault(target, context)
    return list(unique.items())


def _get_at_path(value: object, path: tuple[str, ...]) -> object:
    current = value
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _delay_value(value: object) -> object | None:
    containers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        containers.append(value)
        if isinstance(value.get("answer"), dict):
            containers.append(value["answer"])
    for container in containers:
        item = container.get("smart_delay")
        if container.get("type") == "smart_delay" and isinstance(item, dict):
            try:
                return (
                    int(item.get("days", 0)) * 86400
                    + int(item.get("hours", 0)) * 3600
                    + int(item.get("minutes", 0)) * 60
                    + int(item.get("seconds", 0))
                )
            except (TypeError, ValueError):
                return None
    delay_keys = {"delay", "delay_seconds"}
    values = _values_for_keys(value, delay_keys)
    for item in values:
        if isinstance(item, (int, float, str)) and item not in ("", 0, "0"):
            return item
    return None


def _block_delays(step: dict[str, Any]) -> list[object]:
    answer = step.get("answer") if isinstance(step.get("answer"), dict) else {}
    if answer.get("type") == "smart_delay" and isinstance(answer.get("smart_delay"), dict):
        return [answer["smart_delay"]]
    return _dedupe_json(_values_for_keys(step, {"delay", "delay_seconds"}))


def _components(ids: set[int | str], outgoing: dict[int | str, set[int | str]]) -> list[list[int | str]]:
    neighbors: dict[int | str, set[int | str]] = {item: set() for item in ids}
    for source, targets in outgoing.items():
        if source not in ids:
            continue
        for target in targets:
            if target not in ids:
                continue
            neighbors[source].add(target)
            neighbors[target].add(source)
    result: list[list[int | str]] = []
    remaining = set(ids)
    while remaining:
        seed = next(iter(remaining))
        queue = [seed]
        component: list[int | str] = []
        remaining.remove(seed)
        while queue:
            current = queue.pop()
            component.append(current)
            for neighbor in neighbors[current] & remaining:
                remaining.remove(neighbor)
                queue.append(neighbor)
        result.append(sorted(component, key=str))
    return sorted(result, key=lambda group: (-len(group), str(group[0])))


def _reachable(start: int | str | None, outgoing: dict[int | str, set[int | str]]) -> set[int | str]:
    if start is None:
        return set()
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for target in outgoing[current] - seen:
            seen.add(target)
            queue.append(target)
    return seen


def _paths(start: int | str | None, outgoing: dict[int | str, set[int | str]], limit: int = 1000) -> list[list[int | str]]:
    if start is None:
        return []
    result: list[list[int | str]] = []

    def visit(node: int | str, path: list[int | str]) -> None:
        if len(result) >= limit:
            return
        targets = sorted(outgoing[node], key=str)
        if not targets:
            result.append(path)
            return
        advanced = False
        for target in targets:
            if target in path:
                result.append(path + [target])
            else:
                advanced = True
                visit(target, path + [target])
        if not advanced and not result:
            result.append(path)

    visit(start, [start])
    return result


def normalize_scenario(payload: dict[str, Any], scenario_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("Scenario JSON must contain an object in data")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("Scenario JSON has no data.steps list")
    steps = [step for step in raw_steps if isinstance(step, dict) and _as_id(step.get("id")) is not None]
    ids = {_as_id(step["id"]) for step in steps}
    ids.discard(None)
    outgoing: dict[int | str, set[int | str]] = {item: set() for item in ids}
    edge_contexts: dict[tuple[int | str, int | str], dict[str, Any]] = {}
    for step in steps:
        source = _as_id(step["id"])
        for target, context in _extract_targets(step, ids):
            outgoing[source].add(target)
            edge_contexts.setdefault((source, target), context)
    incoming: dict[int | str, set[int | str]] = {item: set() for item in ids}
    for source, targets in outgoing.items():
        for target in targets:
            incoming[target].add(source)
    explicit_main = next((_as_id(step["id"]) for step in steps if step.get("is_main") is True), None)
    explicit_start = next(
        (
            _as_id(step["id"])
            for step in steps
            if isinstance(step.get("answer"), dict) and step["answer"].get("type") == "start"
        ),
        None,
    )
    roots = sorted((item for item in ids if not incoming[item]), key=str)
    if explicit_main is not None:
        main_start = explicit_main
    elif explicit_start is not None:
        main_start = explicit_start
    elif roots:
        by_id = {_as_id(step["id"]): step for step in steps}
        main_start = min(roots, key=lambda item: (by_id[item].get("y", 0), by_id[item].get("x", 0), str(item)))
    else:
        main_start = min(ids, key=str) if ids else None
    reachable = _reachable(main_start, outgoing)
    components = _components(ids, outgoing)
    component_by_id = {item: index for index, group in enumerate(components) for item in group}
    normalized_blocks: list[dict[str, Any]] = []
    for step in steps:
        block_id = _as_id(step["id"])
        answer = step.get("answer") if isinstance(step.get("answer"), dict) else {}
        text_raw, html_value = _extract_text(step)
        linked = bool(incoming[block_id] or outgoing[block_id])
        external_signal = bool(step.get("is_main") or step.get("is_alt_main") or step.get("commands"))
        if block_id in reachable:
            classification = "main_flow"
        elif not linked and external_signal:
            classification = "unknown_external_entry"
        elif not linked:
            classification = "orphan"
        else:
            classification = "detached_component"
        links = sorted(set(URL_RE.findall(text_raw or "")))
        links.extend(str(item) for item in _values_for_keys(step, {"url", "link", "href"}) if isinstance(item, str))
        normalized_blocks.append(
            {
                "block_id": block_id,
                "type": answer.get("type") or step.get("type"),
                "name": step.get("name"),
                "text_raw": text_raw,
                "text_plain": _plain_text(text_raw),
                "html": html_value,
                "x": step.get("x"),
                "y": step.get("y"),
                "next_ids": sorted(outgoing[block_id], key=str),
                "incoming_ids": sorted(incoming[block_id], key=str),
                "buttons": _dedupe_json(_values_for_keys(step, {"commands", "keyboard", "buttons"})),
                "links": sorted(set(links)),
                "media": _dedupe_json(_values_for_keys(step, {"media", "photo", "video", "audio", "voice", "document", "file"})),
                "conditions": _dedupe_json(_values_for_keys(step, {"condition", "conditions"})),
                "delays": _block_delays(step),
                "variables": _dedupe_json(_values_for_keys(step, {"variable", "variables", "set_variable"})),
                "tags": _dedupe_json(_values_for_keys(step, {"tag", "tags"})),
                "actions": [step.get("actions")] if isinstance(step.get("actions"), dict) else [],
                "classification": classification,
                "component_id": component_by_id[block_id],
                "raw": step,
            }
        )
    edges = []
    for (source, target), context in sorted(edge_contexts.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))):
        edges.append(
            {
                "from_block": source,
                "to_block": target,
                "delay_seconds": _delay_value(context),
                "conditions": _dedupe_json(_values_for_keys(context, {"condition", "conditions"})),
                "raw": context,
            }
        )
    detached_components = _components(ids - reachable, outgoing) if ids - reachable else []
    meta = scenario_meta or {}
    return {
        "scenario_id": meta.get("id") or meta.get("scenario_id"),
        "scenario_name": meta.get("name") or meta.get("scenario_name"),
        "parent_id": meta.get("parent_id"),
        "blocks": normalized_blocks,
        "edges": edges,
        "components": [
            {
                "component_id": index,
                "block_ids": group,
                "reachable_from_main": bool(set(group) & reachable),
            }
            for index, group in enumerate(components)
        ],
        "detached_components": [
            {"component_id": index, "block_ids": group}
            for index, group in enumerate(detached_components)
        ],
        "root_block_ids": roots,
        "main_start_block_id": main_start,
        "terminal_block_ids": sorted((item for item in ids if not outgoing[item]), key=str),
        "reachable_block_ids": sorted(reachable, key=str),
        "unreachable_block_ids": sorted(ids - reachable, key=str),
        "ordered_paths": _paths(main_start, outgoing),
        "metadata": {
            "bot_id": data.get("id"),
            "raw_scenario_metadata": meta,
            "raw_data_without_steps": {key: value for key, value in data.items() if key != "steps"},
            "raw_response_without_steps": {key: value for key, value in payload.items() if key != "data"},
        },
    }
