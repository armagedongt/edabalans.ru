from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import markdown
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_admin


router = APIRouter()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs"
PROJECT_MAP_PATH = DOCS_ROOT / "generated" / "module-inventory.json"
PROJECT_MAP_SCHEMA_VERSION = 1
PROJECT_MAP_ARRAY_FIELDS = (
    "modules",
    "relations",
    "files",
    "routes",
    "tables",
    "symbols",
    "derived_outputs",
    "plans",
    "cross_project_plans",
)
MODULE_ARRAY_FIELDS = (
    "capabilities",
    "truths",
    "runtime_services",
    "admin_urls",
    "public_urls",
    "sources",
    "files",
    "routes",
    "tables",
    "symbols",
    "plans",
)
MODULE_RELATION_FIELDS = (
    "reads_from",
    "writes_to",
    "depends_on",
    "events_in",
    "events_out",
)

STATUS_RE = re.compile(r"^Статус:\s*`?([^`\n]+)`?", re.MULTILINE | re.IGNORECASE)
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
def grouped_paths() -> list[tuple[str, str, Path, list[Path]]]:
    knowledge_root = DOCS_ROOT / "knowledge-base"
    plans_root = DOCS_ROOT / "plans"
    start_files = [
        PROJECT_ROOT / "PROJECT_CONTEXT.md",
        PROJECT_ROOT / "ARCHITECTURE.md",
        DOCS_ROOT / "README.md",
    ]
    working_files = sorted(
        path for path in DOCS_ROOT.glob("*.md") if path.name != "README.md"
    )
    return [
        ("start", "С чего начать", PROJECT_ROOT, [path for path in start_files if path.is_file()]),
        ("knowledge", "База знаний", knowledge_root, sorted(knowledge_root.rglob("*.md"))),
        ("working", "Проект и эксплуатация", DOCS_ROOT, working_files),
        ("plans", "Планы", plans_root, sorted(plans_root.rglob("*.md"))),
    ]


def document_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def document_meta(path: Path, root: Path, query: str = "") -> dict[str, object] | None:
    content = path.read_text(encoding="utf-8")
    title_match = TITLE_RE.search(content)
    status_match = STATUS_RE.search(content)
    title = title_match.group(1).strip() if title_match else path.stem.replace("_", " ").title()
    relative_parts = list(path.relative_to(root).parts)
    if relative_parts and relative_parts[-1].lower() == "readme.md":
        relative_parts[-1] = "Обзор"
    else:
        relative_parts[-1] = title

    match = ""
    if query:
        folded = query.casefold()
        haystack = f"{title}\n{document_path(path)}\n{content}".casefold()
        if folded not in haystack:
            return None
        for line in content.splitlines():
            if folded in line.casefold():
                match = re.sub(r"[`*_>#\[\]]", "", line).strip()[:240]
                break

    return {
        "path": document_path(path),
        "title": title,
        "status": status_match.group(1).strip() if status_match else "",
        "parts": relative_parts,
        "match": match,
    }


def catalog(query: str = "") -> list[dict[str, object]]:
    sections = []
    for code, title, root, paths in grouped_paths():
        documents = [document_meta(path, root, query) for path in paths]
        visible = [item for item in documents if item is not None]
        if visible:
            sections.append({"code": code, "title": title, "documents": visible})
    return sections


def allowed_documents() -> dict[str, Path]:
    return {
        document_path(path): path
        for _, _, _, paths in grouped_paths()
        for path in paths
    }


def read_project_map(path: Path | None = None) -> dict[str, Any]:
    """Read the generated map without scanning the repository at request time."""
    source = path or PROJECT_MAP_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="project map is temporarily unavailable",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail="project map has an invalid format")
    if payload.get("schema_version") != PROJECT_MAP_SCHEMA_VERSION:
        raise HTTPException(status_code=503, detail="project map schema is not supported")
    if any(not isinstance(payload.get(field), list) for field in PROJECT_MAP_ARRAY_FIELDS):
        raise HTTPException(status_code=503, detail="project map has an invalid format")
    modules = payload["modules"]

    module_ids: set[str] = set()
    for module in modules:
        if not isinstance(module, dict):
            raise HTTPException(status_code=503, detail="project map has an invalid format")
        module_id = module.get("id")
        if not isinstance(module_id, str) or not module_id or module_id in module_ids:
            raise HTTPException(status_code=503, detail="project map has an invalid format")
        if module.get("parent") is not None and not isinstance(module.get("parent"), str):
            raise HTTPException(status_code=503, detail="project map has an invalid format")
        if any(not isinstance(module.get(field), str) for field in (
            "card", "title", "summary", "boundary", "document_status", "implementation_status"
        )):
            raise HTTPException(status_code=503, detail="project map has an invalid format")
        if any(not isinstance(module.get(field), list) for field in MODULE_ARRAY_FIELDS):
            raise HTTPException(status_code=503, detail="project map has an invalid format")
        relations = module.get("relations")
        if not isinstance(relations, dict) or any(
            not isinstance(relations.get(field), list)
            for field in MODULE_RELATION_FIELDS
        ):
            raise HTTPException(status_code=503, detail="project map has an invalid format")
        module_ids.add(module_id)

    return payload


@router.get("/admin/api/knowledge-base")
def knowledge_catalog(
    q: str = Query(default="", max_length=120),
    _: str = Depends(require_admin),
) -> dict[str, object]:
    sections = catalog(q.strip())
    return {
        "sections": sections,
        "count": sum(len(section["documents"]) for section in sections),
        "query": q.strip(),
        "all_paths": sorted(allowed_documents()),
    }


@router.get("/admin/api/project-map")
def project_map(
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    return read_project_map()


@router.get("/admin/api/knowledge-base/document")
def knowledge_document(
    path: str = Query(min_length=1, max_length=500),
    _: str = Depends(require_admin),
) -> dict[str, str]:
    source = allowed_documents().get(path)
    if source is None:
        raise HTTPException(status_code=404, detail="document not found")
    content = source.read_text(encoding="utf-8")
    meta = document_meta(source, source.parent)
    # Markdown comes only from the private, version-controlled repository and is
    # available only through the admin session. Raw HTML is therefore trusted here.
    html = markdown.markdown(content, extensions=["extra", "sane_lists", "toc"])
    return {
        "path": path,
        "title": str(meta["title"]),
        "status": str(meta["status"]),
        "html": html,
    }
