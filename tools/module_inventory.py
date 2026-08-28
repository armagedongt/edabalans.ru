#!/usr/bin/env python3
"""Build and validate the project module inventory using only Python stdlib."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = 1
DOCUMENT_STATUSES = {"current", "draft", "planned", "archived"}
IMPLEMENTATION_STATUSES = {"implemented", "in_development", "planned", "archived"}
SOURCE_ROLES = {"runtime", "seed", "rule", "copy", "config", "consumer"}
ADMIN_CATALOG_CATEGORIES = {"clients", "applications", "tools", "project", "services"}
RELATION_TYPES = ("reads_from", "writes_to", "depends_on", "events_in", "events_out")
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "api_route"}
JS_FUNCTION_RE = re.compile(
    r"(?mx)"
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|"
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s*)?(?:function\b|(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)"
)
STATUS_LINE_RE = re.compile(
    r"(?im)^\s*(?:document_status|статус(?:\s+документа)?)\s*:\s*[`\"']?([a-z_]+)"
)
TOP_STATUS_RE = re.compile(
    r"(?im)^\s*Статус(?:\s+документа)?\s*:\s*[`\"']?([a-z_]+)[`\"']?\s{0,2}$"
)


class InventoryError(RuntimeError):
    """A user-actionable registry or inventory validation error."""


@dataclass(frozen=True)
class Discovery:
    symbols: tuple[dict[str, Any], ...] = ()
    routes: tuple[dict[str, Any], ...] = ()
    tables: tuple[dict[str, Any], ...] = ()


def posix_path(value: str | Path) -> str:
    return PurePosixPath(str(value).replace("\\", "/")).as_posix()


def _run_git(repo: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=repo,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise InventoryError(f"git {' '.join(args)} failed: {detail}")
    return [line for line in result.stdout.splitlines() if line]


def tracked_inputs(
    repo: Path,
    derived_outputs: Iterable[str],
    *,
    include_untracked: bool = True,
) -> list[str]:
    """Return tracked inputs, optionally with local untracked files, excluding outputs."""
    derived = {posix_path(path) for path in derived_outputs}
    args = (
        ("ls-files", "--cached", "--others", "--exclude-standard")
        if include_untracked
        else ("ls-files", "--cached")
    )
    files = _run_git(repo, *args)
    return sorted({posix_path(path) for path in files if posix_path(path) not in derived})


def _front_matter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}
    result: dict[str, Any] = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        value = value.strip().strip("\"'")
        if value.lower() in {"true", "false"}:
            result[key.strip()] = value.lower() == "true"
        elif value.startswith("[") and value.endswith("]"):
            result[key.strip()] = [
                part.strip().strip("\"'") for part in value[1:-1].split(",") if part.strip()
            ]
        else:
            result[key.strip()] = value
    return result


def parse_card(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    meta = _front_matter(text)
    heading = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    capabilities: list[str] = []
    section = re.search(
        r"(?ims)^##\s+(?:Возможности|Функции|Capabilities)\s*$\s*(.*?)(?=^##\s|\Z)", text
    )
    if section:
        capabilities = [
            match.group(1).strip()
            for match in re.finditer(r"(?m)^\s*[-*]\s+(.+?)\s*$", section.group(1))
        ]
    boundary_match = re.search(
        r"(?ims)^##\s+(?:Граница|Boundary)\s*$\s*(.*?)(?=^##\s|\Z)", text
    )
    boundary = boundary_match.group(1).strip() if boundary_match else ""
    truths_match = re.search(
        r"(?ims)^##\s+(?:Источники истины|Sources of truth)\s*$\s*(.*?)(?=^##\s|\Z)",
        text,
    )
    truths = []
    if truths_match:
        truths = [
            re.sub(r"^\s*[-*]\s+", "", paragraph.strip())
            for paragraph in re.split(r"\n\s*\n", truths_match.group(1))
            if paragraph.strip()
            and not paragraph.strip().startswith("Технические файлы, routes, таблицы")
        ]
    document_status = str(meta.get("document_status", "")).strip()
    if not document_status:
        match = STATUS_LINE_RE.search(text)
        document_status = match.group(1) if match else ""
    return {
        "title": str(meta.get("title") or (heading.group(1).strip() if heading else "")),
        "summary": str(meta.get("summary", "")).strip(),
        "document_status": document_status,
        "implementation_status": str(meta.get("implementation_status", "")).strip(),
        "capabilities": capabilities,
        "boundary": boundary,
        "truths": truths,
    }


def top_document_status(path: Path) -> str:
    """Read only document-level status, never a similarly named nested section."""
    text = path.read_text(encoding="utf-8")
    meta = _front_matter(text)
    if "document_status" in meta:
        return str(meta["document_status"]).strip()
    before_sections = text.split("\n## ", 1)[0]
    match = TOP_STATUS_RE.search(before_sections)
    return match.group(1) if match else ""


def load_registry(repo: Path, registry_path: str = "docs/modules.toml") -> dict[str, Any]:
    path = repo / registry_path
    try:
        with path.open("rb") as handle:
            registry = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InventoryError(f"Cannot read valid {registry_path}: {exc}") from exc
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise InventoryError(
            f"{registry_path}: schema_version must be {SCHEMA_VERSION}, "
            f"got {registry.get('schema_version')!r}"
        )
    if not isinstance(registry.get("modules"), list):
        raise InventoryError(f"{registry_path}: [[modules]] entries are required")
    derived_records: list[dict[str, str]] = []
    for entry in registry.get("derived_outputs", []):
        if isinstance(entry, str):
            derived_records.append(
                {"path": posix_path(entry), "module_id": "admin.project-knowledge"}
            )
        elif isinstance(entry, dict):
            derived_records.append(
                {
                    "path": posix_path(str(entry.get("path", ""))),
                    "module_id": str(entry.get("module_id", "")),
                }
            )
        else:
            raise InventoryError(f"{registry_path}: invalid derived_outputs entry {entry!r}")
    registry["derived_output_records"] = derived_records
    registry["derived_outputs"] = [entry["path"] for entry in derived_records]
    return registry


def pattern_specificity(pattern: str) -> tuple[int, int]:
    literal = sum(char not in "*?[]" for char in pattern)
    return literal, pattern.count("/")


def resolve_owner(
    value: str,
    rules: Iterable[tuple[str, str]],
    *,
    object_kind: str,
) -> str:
    matches = [(pattern_specificity(pattern), module_id, pattern) for pattern, module_id in rules if fnmatch.fnmatchcase(value, pattern)]
    if not matches:
        raise InventoryError(f"{object_kind} has no owner: {value}")
    best_rank = max(rank for rank, _, _ in matches)
    best = [(module_id, pattern) for rank, module_id, pattern in matches if rank == best_rank]
    owners = {module_id for module_id, _ in best}
    if len(owners) != 1:
        details = ", ".join(f"{module_id}:{pattern}" for module_id, pattern in best)
        raise InventoryError(f"{object_kind} has overlapping owner rules: {value} ({details})")
    return best[0][0]


def _string_literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def extract_python(path: Path, relative_path: str) -> Discovery:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise InventoryError(f"Cannot parse Python file {relative_path}: {exc}") from exc

    router_prefixes: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Call) or not _call_name(value.func).endswith("APIRouter"):
            continue
        prefix = next((_string_literal(keyword.value) for keyword in value.keywords if keyword.arg == "prefix"), "") or ""
        for target in targets:
            if isinstance(target, ast.Name):
                router_prefixes[target.id] = prefix

    symbols: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[tuple[str, str]] = []

        def _visit_symbol(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> None:
            qualname = ".".join([*(name for name, _ in self.stack), node.name])
            actual_kind = (
                "method"
                if kind == "function" and self.stack and self.stack[-1][1] == "class"
                else kind
            )
            symbols.append(
                {
                    "name": node.name,
                    "qualname": qualname,
                    "kind": actual_kind,
                    "file": relative_path,
                    "line": node.lineno,
                }
            )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    call = decorator if isinstance(decorator, ast.Call) else None
                    name = _call_name(call.func if call else decorator)
                    method = name.rsplit(".", 1)[-1].lower()
                    if method not in HTTP_METHODS or not call or not call.args:
                        continue
                    route_path = _string_literal(call.args[0])
                    if route_path is None:
                        continue
                    owner_name = name.rsplit(".", 1)[0]
                    prefix = router_prefixes.get(owner_name, "")
                    full_path = f"{prefix.rstrip('/')}/{route_path.lstrip('/')}"
                    if full_path != "/":
                        full_path = full_path.rstrip("/") or "/"
                    methods = [method.upper()]
                    if method == "api_route":
                        methods = []
                        for keyword in call.keywords:
                            if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                                methods = [
                                    literal.upper()
                                    for item in keyword.value.elts
                                    if (literal := _string_literal(item))
                                ]
                        methods = methods or ["ANY"]
                    for http_method in methods:
                        routes.append(
                            {
                                "method": http_method,
                                "path": full_path,
                                "file": relative_path,
                                "line": node.lineno,
                                "symbol": qualname,
                            }
                        )
            self.stack.append((node.name, kind))
            self.generic_visit(node)
            self.stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            for statement in node.body:
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                if any(isinstance(target, ast.Name) and target.id == "__tablename__" for target in targets):
                    table_name = _string_literal(statement.value)
                    if table_name:
                        tables.append(
                            {"name": table_name, "file": relative_path, "line": statement.lineno, "source": "orm"}
                        )
            self._visit_symbol(node, "class")

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self._visit_symbol(node, "function")

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self._visit_symbol(node, "function")

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            if _call_name(node.func).endswith("op.create_table") and node.args:
                table_name = _string_literal(node.args[0])
                if table_name:
                    tables.append(
                        {"name": table_name, "file": relative_path, "line": node.lineno, "source": "migration"}
                    )
            self.generic_visit(node)

    Visitor().visit(tree)
    key = lambda item: (item["file"], item["line"], item.get("qualname", item.get("name", "")))
    return Discovery(
        symbols=tuple(sorted(symbols, key=key)),
        routes=tuple(sorted(routes, key=lambda item: (item["path"], item["method"], item["file"], item["line"]))),
        tables=tuple(sorted(tables, key=lambda item: (item["name"], item["file"], item["line"]))),
    )


def extract_javascript(path: Path, relative_path: str) -> Discovery:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InventoryError(f"Cannot read JavaScript file {relative_path}: {exc}") from exc
    symbols: list[dict[str, Any]] = []
    for match in JS_FUNCTION_RE.finditer(text):
        name = match.group(1) or match.group(2)
        symbols.append(
            {
                "name": name,
                "qualname": name,
                "kind": "function",
                "file": relative_path,
                "line": text.count("\n", 0, match.start()) + 1,
            }
        )
    return Discovery(symbols=tuple(sorted(symbols, key=lambda item: (item["file"], item["line"], item["name"]))))


def parse_plan(path: Path, relative_path: str) -> tuple[dict[str, Any] | None, list[str]]:
    text = path.read_text(encoding="utf-8")
    meta = _front_matter(text)
    status = str(meta.get("document_status", "")).strip()
    if not status:
        match = STATUS_LINE_RE.search(text)
        status = match.group(1) if match else ""
    if status != "planned":
        return None, []
    errors: list[str] = []
    module_id = str(meta.get("module_id", "")).strip()
    cross_project = meta.get("cross_project") is True
    if bool(module_id) == bool(cross_project):
        errors.append(f"{relative_path}: planned document needs exactly one of module_id or cross_project: true")
    if meta.get("origin") != "owner-explicit":
        errors.append(f"{relative_path}: planned document origin must be owner-explicit")
    date = str(meta.get("date", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        errors.append(f"{relative_path}: planned document date must be YYYY-MM-DD")
    heading = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return (
        {
            "path": relative_path,
            "title": heading.group(1).strip() if heading else relative_path,
            "date": date,
            "module_id": module_id or None,
            "cross_project": cross_project,
            "origin": str(meta.get("origin", "")),
        },
        errors,
    )


def parse_quick_notes(path: Path, relative_path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract active row-level plans from the current QUICK_NOTES table."""
    text = path.read_text(encoding="utf-8")
    status_match = STATUS_LINE_RE.search(text)
    if not status_match or status_match.group(1) != "current":
        return [], []
    lines = text.splitlines()
    plans: list[dict[str, Any]] = []
    errors: list[str] = []
    required = ["ID", "Module ID", "Статус", "Пожелание", "Дата", "Origin", "Источник"]
    for index, line in enumerate(lines[:-1]):
        if not line.strip().startswith("|"):
            continue
        headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if headers != required:
            continue
        separator = lines[index + 1]
        if not re.fullmatch(r"\s*\|(?:\s*:?-+:?\s*\|){7}\s*", separator):
            errors.append(f"{relative_path}: QUICK_NOTES table has an invalid separator")
            return [], errors
        for row_line in lines[index + 2 :]:
            if not row_line.strip().startswith("|"):
                break
            cells = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
            if len(cells) != len(required):
                errors.append(f"{relative_path}: malformed QUICK_NOTES row: {row_line.strip()}")
                continue
            row = dict(zip(required, cells, strict=True))
            row_status = row["Статус"].strip("` ").lower()
            if row_status != "planned":
                continue
            row_id = row["ID"].strip("` ")
            module_id = row["Module ID"].strip("` ")
            date = row["Дата"].strip("` ")
            origin = row["Origin"].strip("` ")
            if not row_id:
                errors.append(f"{relative_path}: planned QUICK_NOTES row needs ID")
            if not module_id:
                errors.append(f"{relative_path}#{row_id}: planned row needs Module ID")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                errors.append(f"{relative_path}#{row_id}: planned row date must be YYYY-MM-DD")
            if origin != "owner-explicit":
                errors.append(f"{relative_path}#{row_id}: planned row origin must be owner-explicit")
            if not row["Пожелание"]:
                errors.append(f"{relative_path}#{row_id}: planned row needs a wish")
            if not row["Источник"]:
                errors.append(f"{relative_path}#{row_id}: planned row needs a source")
            plans.append(
                {
                    "path": relative_path,
                    "row_id": row_id,
                    "title": row["Пожелание"],
                    "date": date,
                    "module_id": module_id or None,
                    "cross_project": False,
                    "origin": origin,
                    "source": row["Источник"],
                }
            )
        return plans, errors
    errors.append(f"{relative_path}: current QUICK_NOTES needs the canonical row-plan table")
    return [], errors


def _module_rules(modules: list[dict[str, Any]], key: str) -> list[tuple[str, str]]:
    return [
        (posix_path(pattern), module["id"])
        for module in modules
        for pattern in module.get(key, [])
    ]


def validate_registry(repo: Path, registry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    modules = registry["modules"]
    ids = [str(module.get("id", "")) for module in modules]
    if any(not module_id for module_id in ids):
        errors.append("Every [[modules]] entry needs a non-empty id")
    duplicates = sorted({module_id for module_id in ids if ids.count(module_id) > 1})
    if duplicates:
        errors.append(f"Duplicate module ids: {', '.join(duplicates)}")
    known = set(ids)
    raw_by_id = {str(module.get("id", "")): module for module in modules}
    telegram_codes: set[str] = set()
    telegram_orders: set[int] = set()
    for output in registry.get("derived_output_records", []):
        if not output["path"]:
            errors.append("Every derived output needs a non-empty path")
        if output["module_id"] not in known:
            errors.append(
                f"Derived output {output['path'] or '<empty>'} has unknown owner {output['module_id']!r}"
            )
    normalized: list[dict[str, Any]] = []
    for module in modules:
        module_id = str(module.get("id", ""))
        parent = module.get("parent")
        if parent and parent not in known:
            errors.append(f"{module_id}: unknown parent {parent}")
        for relation_type in RELATION_TYPES:
            for target in module.get(relation_type, []):
                if target not in known:
                    errors.append(f"{module_id}: {relation_type} targets unknown module {target}")
        card = posix_path(module.get("card", ""))
        card_meta = {
            "title": "", "summary": "", "document_status": "",
            "implementation_status": "", "capabilities": [], "boundary": "", "truths": [],
        }
        if not card or not (repo / card).is_file():
            errors.append(f"{module_id}: card does not exist: {card or '<empty>'}")
        else:
            try:
                card_meta = parse_card(repo / card)
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{module_id}: cannot read card {card}: {exc}")
        if not card_meta["title"]:
            errors.append(f"{module_id}: card {card} needs title")
        if not card_meta["summary"]:
            errors.append(f"{module_id}: card {card} needs summary")
        if card_meta["document_status"] not in DOCUMENT_STATUSES:
            errors.append(
                f"{module_id}: card {card} has invalid document_status "
                f"{card_meta['document_status']!r}"
            )
        if card_meta["implementation_status"] not in IMPLEMENTATION_STATUSES:
            errors.append(
                f"{module_id}: card {card} has invalid implementation_status "
                f"{card_meta['implementation_status']!r}"
            )
        sources: list[dict[str, Any]] = []
        for source in module.get("sources", []):
            source_path = posix_path(source.get("path", ""))
            role = source.get("role")
            consumers = list(source.get("consumers", []))
            if role not in SOURCE_ROLES:
                errors.append(f"{module_id}: source {source_path} has invalid role {role!r}")
            if not source_path or not (repo / source_path).exists():
                errors.append(f"{module_id}: source path does not exist: {source_path or '<empty>'}")
            unknown = sorted(set(consumers) - known)
            if unknown:
                errors.append(f"{module_id}: source {source_path} has unknown consumers: {', '.join(unknown)}")
            if source.get("shared") is True and role in {"runtime", "seed", "rule", "copy"} and not consumers:
                errors.append(f"{module_id}: shared {role} source {source_path} needs consumers")
            for consumer in consumers:
                if consumer in raw_by_id and module_id not in raw_by_id[consumer].get("reads_from", []):
                    errors.append(
                        f"{consumer}: shared source {source_path} requires reads_from = [{module_id}]"
                    )
            sources.append(
                {"path": source_path, "role": role, "shared": source.get("shared") is True, "consumers": sorted(consumers)}
            )
        admin_catalog: list[dict[str, Any]] = []
        for item in module.get("admin_catalog", []):
            if not isinstance(item, dict):
                errors.append(f"{module_id}: admin_catalog entries must be tables")
                continue
            category, url, label, description, order = str(item.get("category", "")), str(item.get("url", "")), str(item.get("label", "")), str(item.get("description", "")), item.get("order")
            if category not in ADMIN_CATALOG_CATEGORIES: errors.append(f"{module_id}: admin_catalog has invalid category {category!r}")
            if not url.startswith(("/", "https://")): errors.append(f"{module_id}: admin_catalog url must be an absolute path or https URL")
            if not label or not description or not isinstance(order, int): errors.append(f"{module_id}: admin_catalog needs label, description and integer order")
            admin_catalog.append({"category": category, "url": url, "label": label, "description": description, "order": order})
        telegram_fields = (
            module.get("telegram_code"),
            module.get("telegram_name"),
            module.get("telegram_status"),
            module.get("telegram_order"),
        )
        telegram: dict[str, Any] | None = None
        if any(value is not None for value in telegram_fields):
            if not all(value is not None and value != "" for value in telegram_fields):
                errors.append(
                    f"{module_id}: telegram_code/name/status/order must be declared together"
                )
            elif not isinstance(module.get("telegram_order"), int):
                errors.append(f"{module_id}: telegram_order must be an integer")
            else:
                code = str(module["telegram_code"])
                order = int(module["telegram_order"])
                if code in telegram_codes:
                    errors.append(f"Duplicate telegram_code: {code}")
                if order in telegram_orders:
                    errors.append(f"Duplicate telegram_order: {order}")
                telegram_codes.add(code)
                telegram_orders.add(order)
                telegram = {
                    "code": code,
                    "name": str(module["telegram_name"]),
                    "status": str(module["telegram_status"]),
                    "order": order,
                }
        normalized.append(
            {
                "id": module_id,
                "parent": parent or None,
                "card": card,
                **card_meta,
                "runtime_services": sorted(module.get("runtime_services", [])),
                "admin_urls": sorted(module.get("admin_urls", [])),
                "admin_catalog": sorted(admin_catalog, key=lambda item: (item["category"], item["order"], item["url"])),
                "public_urls": sorted(module.get("public_urls", [])),
                "sources": sorted(sources, key=lambda item: (item["path"], item["role"] or "")),
                "relations": {key: sorted(module.get(key, [])) for key in RELATION_TYPES},
                "telegram": telegram,
            }
        )

    # Detect parent cycles separately so tree rendering cannot recurse forever.
    parent_by_id = {module["id"]: module.get("parent") for module in modules}
    for module_id in ids:
        seen: set[str] = set()
        current: str | None = module_id
        while current:
            if current in seen:
                errors.append(f"Parent cycle contains module {module_id}")
                break
            seen.add(current)
            current = parent_by_id.get(current)
    return normalized, errors


def build_inventory(
    repo: Path,
    registry: dict[str, Any],
    *,
    include_untracked: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    modules, errors = validate_registry(repo, registry)
    raw_modules = registry["modules"]
    module_ids = {module["id"] for module in raw_modules}
    card_owner = {posix_path(module["card"]): module["id"] for module in raw_modules if module.get("card")}
    file_rules = _module_rules(raw_modules, "owns_files")
    files: list[dict[str, Any]] = []
    file_owner: dict[str, str] = {}
    inputs = tracked_inputs(
        repo,
        registry["derived_outputs"],
        include_untracked=include_untracked,
    )
    for relative_path in inputs:
        try:
            owner = card_owner.get(relative_path) or resolve_owner(relative_path, file_rules, object_kind="file")
        except InventoryError as exc:
            errors.append(str(exc))
            continue
        file_owner[relative_path] = owner
        files.append({"path": relative_path, "module_id": owner})

    canonical_markdown = [
        path
        for path in inputs
        if path in {"PROJECT_CONTEXT.md", "ARCHITECTURE.md"}
        or (path.startswith("docs/") and path.endswith(".md"))
    ]
    for relative_path in canonical_markdown:
        try:
            status = top_document_status(repo / relative_path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Cannot read document status {relative_path}: {exc}")
            continue
        if status not in DOCUMENT_STATUSES:
            errors.append(
                f"{relative_path}: top-level document status must be one of "
                f"{', '.join(sorted(DOCUMENT_STATUSES))}; got {status!r}"
            )

    table_rules: list[tuple[str, str]] = []
    route_rules: list[tuple[str, str]] = []
    symbol_rules: list[tuple[str, str]] = []
    for module in raw_modules:
        table_rules.extend((name, module["id"]) for name in module.get("owns_tables", []))
        route_rules.extend((pattern, module["id"]) for pattern in module.get("owns_routes", []))
        symbol_rules.extend((pattern, module["id"]) for pattern in module.get("owns_symbols", []))

    symbols: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for relative_path, owner in sorted(file_owner.items()):
        path = repo / relative_path
        discovery = Discovery()
        if path.suffix == ".py":
            try:
                discovery = extract_python(path, relative_path)
            except InventoryError as exc:
                errors.append(str(exc))
                continue
        elif path.suffix in {".js", ".mjs", ".gs"}:
            try:
                discovery = extract_javascript(path, relative_path)
            except InventoryError as exc:
                errors.append(str(exc))
                continue
        resolved_routes: list[dict[str, Any]] = []
        route_owner_by_symbol: dict[str, str] = {}
        for route in discovery.routes:
            route_key = f"{route['method']} {route['path']}"
            try:
                route_owner = resolve_owner(route_key, route_rules, object_kind="route")
            except InventoryError as exc:
                errors.append(str(exc))
                continue
            route_symbol = route.get("symbol")
            previous_route_owner = route_owner_by_symbol.get(route_symbol)
            if route_symbol and previous_route_owner and previous_route_owner != route_owner:
                errors.append(
                    f"route function {relative_path}:{route_symbol} belongs to both "
                    f"{previous_route_owner} and {route_owner}"
                )
            elif route_symbol:
                route_owner_by_symbol[route_symbol] = route_owner
            resolved_routes.append({**route, "module_id": route_owner})

        for symbol in discovery.symbols:
            symbol_key = f"{relative_path}:{symbol['qualname']}"
            try:
                if any(fnmatch.fnmatchcase(symbol_key, pattern) for pattern, _ in symbol_rules):
                    symbol_owner = resolve_owner(symbol_key, symbol_rules, object_kind="symbol")
                else:
                    symbol_owner = route_owner_by_symbol.get(symbol["qualname"], owner)
            except InventoryError as exc:
                errors.append(str(exc))
                symbol_owner = owner
            symbols.append({**symbol, "module_id": symbol_owner})
        routes.extend(resolved_routes)
        for table in discovery.tables:
            try:
                table_owner = resolve_owner(table["name"], table_rules, object_kind="table")
            except InventoryError as exc:
                errors.append(str(exc))
                continue
            tables.append({**table, "module_id": table_owner})

    plans: list[dict[str, Any]] = []
    for relative_path in inputs:
        if not relative_path.startswith("docs/plans/") or not relative_path.endswith(".md"):
            continue
        try:
            plan, plan_errors = parse_plan(repo / relative_path, relative_path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Cannot read plan {relative_path}: {exc}")
            continue
        errors.extend(plan_errors)
        if plan:
            if plan["module_id"] and plan["module_id"] not in module_ids:
                errors.append(f"{relative_path}: unknown module_id {plan['module_id']}")
            plans.append(plan)
    quick_notes_path = "docs/plans/QUICK_NOTES.md"
    if quick_notes_path in inputs:
        try:
            row_plans, row_errors = parse_quick_notes(repo / quick_notes_path, quick_notes_path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Cannot read plan rows {quick_notes_path}: {exc}")
        else:
            errors.extend(row_errors)
            for plan in row_plans:
                if plan["module_id"] not in module_ids:
                    errors.append(
                        f"{quick_notes_path}#{plan['row_id']}: unknown module_id {plan['module_id']}"
                    )
                plans.append(plan)

    relations = [
        {"type": relation_type, "source": module["id"], "target": target}
        for module in raw_modules
        for relation_type in RELATION_TYPES
        for target in module.get(relation_type, [])
    ]
    module_index = {module["id"]: module for module in modules}
    module_plans = [plan for plan in plans if not plan["cross_project"]]
    cross_plans = [plan for plan in plans if plan["cross_project"]]
    for module in modules:
        module_id = module["id"]
        module["files"] = [item for item in files if item["module_id"] == module_id]
        module["routes"] = [item for item in routes if item["module_id"] == module_id]
        module["tables"] = [item for item in tables if item["module_id"] == module_id]
        module["symbols"] = [item for item in symbols if item["module_id"] == module_id]
        module["plans"] = [item for item in module_plans if item["module_id"] == module_id]

    inventory = {
        "schema_version": SCHEMA_VERSION,
        "modules": sorted(module_index.values(), key=lambda item: item["id"]),
        "relations": sorted(relations, key=lambda item: (item["type"], item["source"], item["target"])),
        "files": sorted(files, key=lambda item: item["path"]),
        "routes": sorted(routes, key=lambda item: (item["path"], item["method"], item["file"], item["line"])),
        "tables": sorted(tables, key=lambda item: (item["name"], item["file"], item["line"])),
        "symbols": sorted(symbols, key=lambda item: (item["file"], item["line"], item["qualname"])),
        "derived_outputs": sorted(
            registry["derived_output_records"], key=lambda item: item["path"]
        ),
        "plans": sorted(module_plans, key=lambda item: (item["date"], item["path"], item.get("row_id", ""))),
        "cross_project_plans": sorted(cross_plans, key=lambda item: (item["date"], item["path"])),
    }
    return inventory, sorted(set(errors))


def render_json(inventory: dict[str, Any]) -> str:
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown(inventory: dict[str, Any]) -> str:
    children: dict[str | None, list[dict[str, Any]]] = {}
    for module in inventory["modules"]:
        children.setdefault(module["parent"], []).append(module)

    lines = [
        "# Карта модулей edabalans.ru",
        "",
        "Статус: `current`  ",
        "Тип документа: `generated`  ",
        "Источник: `docs/modules.toml`, карточки модулей и исходники репозитория.  ",
        "Этот файл не редактируется вручную.",
        "",
    ]

    def append_branch(parent: str | None, level: int) -> None:
        for module in sorted(children.get(parent, []), key=lambda item: item["id"]):
            lines.append(
                f"{'  ' * level}- **{module['title']}** (`{module['id']}`) — "
                f"{module['summary']} [{module['implementation_status']}]"
            )
            append_branch(module["id"], level + 1)

    append_branch(None, 0)
    lines.extend(["", "## Техническая полнота", ""])
    lines.append(f"- Входных файлов с владельцем: **{len(inventory['files'])}**")
    lines.append(f"- API-маршрутов: **{len(inventory['routes'])}**")
    lines.append(f"- Объявлений таблиц: **{len(inventory['tables'])}**")
    lines.append(f"- Программных символов: **{len(inventory['symbols'])}**")
    lines.append(f"- Явных планов: **{len(inventory['plans'])}**")
    lines.append("")
    return "\n".join(lines)


def render_telegram_modules(inventory: dict[str, Any]) -> str:
    modules = []
    for module in inventory["modules"]:
        telegram = module.get("telegram")
        if not telegram:
            continue
        modules.append(
            {
                "code": telegram["code"],
                "name": telegram["name"],
                "status": telegram["status"],
                "module_id": module["id"],
                "card": module["card"],
                "order": telegram["order"],
            }
        )
    modules.sort(key=lambda item: (item["order"], item["code"]))
    return json.dumps(
        {"schema_version": SCHEMA_VERSION, "modules": modules},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def changed_paths(repo: Path, base: str, head: str | None, working_tree: bool) -> list[str]:
    if working_tree:
        changed = _run_git(repo, "diff", "--name-only", base)
        changed.extend(_run_git(repo, "ls-files", "--others", "--exclude-standard"))
        return sorted({posix_path(path) for path in changed})
    if not head:
        raise InventoryError("--head is required unless --working-tree is used")
    return sorted({posix_path(path) for path in _run_git(repo, "diff", "--name-only", base, head)})


def impact_report(registry: dict[str, Any], changed: Iterable[str]) -> list[str]:
    changed_set = set(changed)
    report: list[str] = []
    for module in registry["modules"]:
        for source in module.get("sources", []):
            path = posix_path(source.get("path", ""))
            affected = path in changed_set or any(item.startswith(f"{path.rstrip('/')}/") for item in changed_set)
            if not affected:
                continue
            consumers = sorted(source.get("consumers", []))
            report.append(
                f"IMPACT {path} ({source.get('role')}, owner={module['id']}): "
                f"review {', '.join(consumers) if consumers else module['id']}"
            )
    return report


def write_or_check(repo: Path, registry: dict[str, Any], inventory: dict[str, Any], check: bool) -> list[str]:
    errors: list[str] = []
    rendered = {
        "docs/generated/module-inventory.json": render_json(inventory),
        "docs/generated/module-map.md": render_markdown(inventory),
        "telegram-bot/service/app/telegram-global-modules.json": render_telegram_modules(inventory),
    }
    declared = set(registry["derived_outputs"])
    if set(rendered) != declared:
        errors.append(
            "derived_outputs must be exactly: " + ", ".join(sorted(rendered))
        )
        return errors
    for relative_path, content in rendered.items():
        path = repo / relative_path
        if check:
            if not path.is_file():
                errors.append(f"Generated artifact is missing: {relative_path}")
            elif path.read_text(encoding="utf-8") != content:
                errors.append(f"Generated artifact is stale: {relative_path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="Validate without changing generated files")
    parser.add_argument("--base", help="Explicit Git base for the impact report")
    parser.add_argument("--head", help="Explicit Git head for the impact report")
    parser.add_argument("--working-tree", action="store_true", help="Compare base with index/worktree/untracked files")
    parser.add_argument(
        "--tracked-only",
        action="store_true",
        help="Build from the checked-out Git commit, ignoring host-local untracked files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    try:
        if (args.head or args.working_tree) and not args.base:
            raise InventoryError("--base is required with --head or --working-tree")
        if args.head and args.working_tree:
            raise InventoryError("Use either --head or --working-tree, not both")
        registry = load_registry(repo)
        inventory, errors = build_inventory(
            repo,
            registry,
            include_untracked=not args.tracked_only,
        )
        if not errors:
            errors.extend(write_or_check(repo, registry, inventory, args.check))
        report: list[str] = []
        if args.base:
            report = impact_report(registry, changed_paths(repo, args.base, args.head, args.working_tree))
        for line in report:
            print(line)
        if errors:
            for error in errors:
                print(f"ERROR {error}", file=sys.stderr)
            print(f"Module inventory failed with {len(errors)} error(s).", file=sys.stderr)
            return 1
        action = "checked" if args.check else "generated"
        print(
            f"Module inventory {action}: {len(inventory['modules'])} modules, "
            f"{len(inventory['files'])} files, {len(inventory['routes'])} routes, "
            f"{len(inventory['tables'])} table declarations, {len(inventory['symbols'])} symbols."
        )
        return 0
    except InventoryError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
