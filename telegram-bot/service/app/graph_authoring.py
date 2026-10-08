"""Faithful authoring of existing version-pinned sequence tables; never sends."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.graph import graph_issues
from app.models import ContentItem, Sequence, SequenceEdge, SequenceStep, SequenceVersion

EDITABLE_CODES = frozenset({"welcome_intensive", "prepurchase_nurture"})
METADATA_KEY = "_editorial_graph"
MAX_SOURCE_BYTES = 500_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SequenceSource(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None
    status: Literal["published"]


class StepSource(StrictModel):
    step_key: str = Field(min_length=1, max_length=120)
    position: StrictInt = Field(ge=1, le=2_147_483_647)
    kind: Literal["MESSAGE", "PHOTO", "VIDEO", "VIDEO_NOTE", "VOICE", "DELAY", "WAIT_BUTTON", "CONDITION", "DB_READ", "DB_WRITE", "GOTO", "STOP"]
    label: str = Field(max_length=255)
    content_code: str | None = Field(max_length=120)
    delay_seconds: StrictInt | None = Field(ge=0, le=2_147_483_647)
    next_step_key: str | None = Field(max_length=120)
    configuration: dict
    enabled: StrictBool


class EdgeSource(StrictModel):
    from_step_key: str = Field(min_length=1, max_length=120)
    to_step_key: str | None = Field(max_length=120)
    target_sequence_code: str | None = Field(max_length=100)
    branch_key: str = Field(min_length=1, max_length=40)
    label: str | None = Field(max_length=255)
    condition: dict
    priority: StrictInt = Field(ge=-2_147_483_648, le=2_147_483_647)
    enabled: StrictBool


class GraphSource(StrictModel):
    schema_version: Literal[1]
    sequence: SequenceSource
    steps: list[StepSource] = Field(min_length=1, max_length=1000)
    edges: list[EdgeSource] = Field(max_length=4000)


class GraphRevision(StrictModel):
    version: StrictInt = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class GraphDraftIn(StrictModel):
    source: str = Field(max_length=MAX_SOURCE_BYTES)
    expected_published: GraphRevision
    expected_draft: GraphRevision | None


class GraphPublishIn(StrictModel):
    expected_published: GraphRevision
    expected_draft: GraphRevision


def is_editorial_owned(session: Session, sequence_id: str) -> bool:
    # Historical ownership survives rollback. Draft creation alone never switches ownership.
    rows = session.scalars(select(SequenceStep.configuration).join(
        SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id
    ).where(SequenceVersion.sequence_id == sequence_id,
            SequenceVersion.status.in_(["published", "archived"])))
    return any(isinstance(config.get(METADATA_KEY), dict)
               and config[METADATA_KEY].get("owner") == "messaging.telegram.engine"
               and config[METADATA_KEY].get("published_owner") is True for config in rows)


def _sequence(session: Session, code: str, *, lock: bool = False) -> Sequence:
    if code not in EDITABLE_CODES:
        raise HTTPException(404, "Sequence source is not editable")
    query = select(Sequence).where(Sequence.code == code)
    sequence = session.scalar((query.with_for_update() if lock else query).execution_options(populate_existing=True))
    if not sequence:
        raise HTTPException(404, "Sequence not found")
    return sequence


def _version(session: Session, sequence: Sequence, status: str) -> SequenceVersion | None:
    return session.scalar(select(SequenceVersion).where(
        SequenceVersion.sequence_id == sequence.id, SequenceVersion.status == status
    ).order_by(SequenceVersion.version_no.desc()))


def document(session: Session, sequence: Sequence, version: SequenceVersion) -> dict:
    rows = session.execute(select(SequenceStep, ContentItem.code).outerjoin(
        ContentItem, ContentItem.id == SequenceStep.content_item_id
    ).where(SequenceStep.sequence_version_id == version.id).order_by(SequenceStep.position)
        .execution_options(populate_existing=True)).all()
    metadata = (rows[0][0].configuration or {}).get(METADATA_KEY, {}) if rows else {}
    sequence_data = metadata.get("sequence", {}) if isinstance(metadata, dict) else {}
    result = {"schema_version": 1, "sequence": sequence_data or {
        "code": sequence.code, "name": sequence.name, "description": sequence.description,
        "status": sequence.status,
    }, "steps": [], "edges": []}
    for step, code in rows:
        result["steps"].append({
            "step_key": step.step_key, "position": step.position, "kind": step.kind,
            "label": step.label, "content_code": code, "delay_seconds": step.delay_seconds,
            "next_step_key": step.next_step_key, "configuration": deepcopy(step.configuration),
            "enabled": step.enabled,
        })
    edges = session.scalars(select(SequenceEdge).where(
        SequenceEdge.sequence_version_id == version.id
    ).order_by(SequenceEdge.from_step_key, SequenceEdge.branch_key, SequenceEdge.priority)
        .execution_options(populate_existing=True))
    for edge in edges:
        result["edges"].append({name: deepcopy(getattr(edge, name)) for name in (
            "from_step_key", "to_step_key", "target_sequence_code", "branch_key", "label",
            "condition", "priority", "enabled",
        )})
    return result


def source_hash(data: dict) -> str:
    data = deepcopy(data)
    data["steps"].sort(key=lambda step: step["position"])
    data["edges"].sort(key=lambda edge: (edge["from_step_key"], edge["branch_key"], edge["priority"]))
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def semantic_hash(data: dict) -> str:
    """Compare complete execution data, excluding the reserved inert ownership metadata."""
    data = deepcopy(data)
    for step in data["steps"]:
        step["configuration"].pop(METADATA_KEY, None)
    return source_hash(data)


def _payload(session: Session, sequence: Sequence, version: SequenceVersion | None) -> dict | None:
    if version is None:
        return None
    data = document(session, sequence, version)
    return {"version": version.version_no, "version_id": version.id, "status": version.status,
            "sha256": source_hash(data), "semantic_sha256": semantic_hash(data),
            "source": json.dumps(data, ensure_ascii=False, indent=2) + "\n", "document": data}


def load_source(session: Session, code: str) -> dict:
    sequence = _sequence(session, code)
    return {"ok": True, "code": code, "published": _payload(session, sequence, _version(session, sequence, "published")),
            "draft": _payload(session, sequence, _version(session, sequence, "draft")),
            "editorial_owned": is_editorial_owned(session, sequence.id)}


def _check(session: Session, sequence: Sequence, status: str, expected: GraphRevision | None) -> SequenceVersion | None:
    current = _version(session, sequence, status)
    payload = _payload(session, sequence, current)
    if (payload is None) != (expected is None) or (payload is not None and (
        expected is None or expected.version != payload["version"] or expected.sha256 != payload["sha256"]
    )):
        raise HTTPException(409, {"message": "Graph revision conflict", "status": status,
                                  "current": None if payload is None else {"version": payload["version"], "sha256": payload["sha256"]}})
    return current


def parse_source(source: str, code: str) -> GraphSource:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Graph source exceeds 500 KB")
    value = source.replace("\r\n", "\n").strip()
    if value.startswith("```json\n") and value.endswith("\n```"):
        value = value[8:-4]

    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = item
        return result

    data = json.loads(value, object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {value}")))
    parsed = GraphSource.model_validate(data)
    if parsed.sequence.code != code:
        raise ValueError("Sequence code cannot change")
    if len({step.step_key for step in parsed.steps}) != len(parsed.steps) or len({step.position for step in parsed.steps}) != len(parsed.steps):
        raise ValueError("Duplicate step key or position")
    edge_keys = [(edge.from_step_key, edge.branch_key, edge.priority) for edge in parsed.edges]
    if len(set(edge_keys)) != len(edge_keys):
        raise ValueError("Duplicate edge branch and priority")
    keys = {step.step_key for step in parsed.steps}
    delivery_keys = {step.step_key for step in parsed.steps if step.kind in {"MESSAGE", "PHOTO", "VIDEO", "VIDEO_NOTE", "VOICE"}}
    positions = {step.step_key: step.position for step in parsed.steps}
    for step in parsed.steps:
        if step.next_step_key is not None and step.next_step_key not in keys:
            raise ValueError("Unknown next_step_key")
        if step.kind == "DELAY" and step.delay_seconds is None:
            raise ValueError("DELAY requires delay_seconds")
        for reference in ("true_step", "false_step", "timeout_step", "step_key"):
            target = step.configuration.get(reference)
            if target is not None and (not isinstance(target, str) or target not in keys):
                raise ValueError(f"Unknown configuration reference: {reference}")
        anchor = step.configuration.get("anchor_step")
        if anchor is not None and (not isinstance(anchor, str) or (anchor != "run_started_at" and anchor not in keys)):
            raise ValueError("Unknown delay anchor")
        if anchor is not None and anchor != "run_started_at" and anchor not in delivery_keys:
            raise ValueError("Delay anchor must be a message delivery step")
        if anchor is not None and anchor != "run_started_at" and positions[anchor] >= step.position:
            raise ValueError("Delay anchor must precede the delay in the sequence")
        for reference in ("target_sequence", "true_sequence", "false_sequence", "condition", "key", "callback_data"):
            target = step.configuration.get(reference)
            if target is not None and (not isinstance(target, str) or not target):
                raise ValueError(f"Configuration {reference} must be a nonempty string")
        for field in ("template_values", "context_values"):
            if field in step.configuration and not isinstance(step.configuration[field], dict):
                raise ValueError(f"Configuration {field} must be an object")
        for field in ("timeout_seconds", "delivery_ttl_seconds", "day", "personal_intensive_day"):
            value = step.configuration.get(field)
            if value is not None and (type(value) is not int or value < 0 or value > 2_147_483_647):
                raise ValueError(f"Configuration {field} must be a nonnegative integer")
        if "buttons" in step.configuration:
            buttons = step.configuration["buttons"]
            if not isinstance(buttons, list) or any(not isinstance(button, dict) or not isinstance(button.get("text"), str)
                or any(key in button and not isinstance(button[key], str) for key in ("url", "callback_data")) for button in buttons):
                raise ValueError("Configuration buttons must contain text and string targets")
        if step.kind == "DB_WRITE" and not step.configuration.get("key"):
            raise ValueError("DB_WRITE requires key")
        marker = step.configuration.get(METADATA_KEY)
        if marker is not None and (not isinstance(marker, dict) or marker.get("owner") != "messaging.telegram.engine" or marker.get("schema_version") != 1):
            raise ValueError("Reserved graph metadata namespace")
    for edge in parsed.edges:
        if edge.from_step_key not in keys or (edge.to_step_key is not None and edge.to_step_key not in keys):
            raise ValueError("Unknown edge step")
        if (edge.to_step_key is None) == (edge.target_sequence_code is None):
            raise ValueError("Edge requires exactly one target")
    return parsed


def _validate_references(session: Session, data: GraphSource) -> dict[str, str]:
    content_ids = {}
    for step in data.steps:
        if step.content_code is not None:
            item = session.scalar(select(ContentItem).where(ContentItem.code == step.content_code))
            if not item:
                raise ValueError(f"Unknown content code: {step.content_code}")
            content_ids[step.content_code] = item.id
        if step.kind in {"MESSAGE", "PHOTO", "VIDEO", "VIDEO_NOTE", "VOICE"} and step.content_code is None:
            raise ValueError("Message step requires content_code")
        for reference in ("target_sequence", "true_sequence", "false_sequence"):
            target = step.configuration.get(reference)
            if target and not session.scalar(select(Sequence.id).where(Sequence.code == target)):
                raise ValueError("Unknown configuration target sequence")
    for edge in data.edges:
        if edge.target_sequence_code and not session.scalar(select(Sequence.id).where(Sequence.code == edge.target_sequence_code)):
            raise ValueError("Unknown target sequence")
    return content_ids


def _validate_topology(session: Session, version: SequenceVersion) -> None:
    errors = [issue for issue in graph_issues(session, version) if issue["severity"] == "error"]
    if errors:
        raise ValueError("; ".join(issue["message"] for issue in errors))


def save_draft(session: Session, code: str, body: GraphDraftIn) -> dict:
    try:
        sequence = _sequence(session, code, lock=True)
        _check(session, sequence, "published", body.expected_published)
        previous_draft = _check(session, sequence, "draft", body.expected_draft)
        data = parse_source(body.source, code)
        content_ids = _validate_references(session, data)
        last = session.scalar(select(SequenceVersion.version_no).where(
            SequenceVersion.sequence_id == sequence.id).order_by(SequenceVersion.version_no.desc()).limit(1)) or 0
        version = SequenceVersion(sequence_id=sequence.id, version_no=last + 1, status="draft")
        session.add(version)
        session.flush()
        steps = sorted(data.steps, key=lambda step: step.position)
        for index, step in enumerate(steps):
            values = step.model_dump()
            content_code = values.pop("content_code")
            config = deepcopy(values["configuration"])
            # Metadata shares the same version and is inert to the existing engine.
            config.pop(METADATA_KEY, None)
            if index == 0:
                config[METADATA_KEY] = {"schema_version": 1, "owner": "messaging.telegram.engine",
                                        "published_owner": False, "sequence": data.sequence.model_dump(),
                                        "base_published": body.expected_published.model_dump()}
            values["configuration"] = config
            session.add(SequenceStep(sequence_version_id=version.id,
                                     content_item_id=content_ids.get(content_code), **values))
        for edge in data.edges:
            session.add(SequenceEdge(sequence_version_id=version.id, **edge.model_dump()))
        session.flush()
        _validate_topology(session, version)
        if previous_draft:
            previous_draft.status = "archived"
        session.commit()
        return load_source(session, code)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Graph revision conflict") from error
    except Exception:
        session.rollback()
        raise


def publish_draft(session: Session, code: str, body: GraphPublishIn) -> dict:
    try:
        sequence = _sequence(session, code, lock=True)
        _check(session, sequence, "published", body.expected_published)
        draft = _check(session, sequence, "draft", body.expected_draft)
        data = parse_source(_payload(session, sequence, draft)["source"], code)
        _validate_references(session, data)
        _validate_topology(session, draft)
        first = session.scalar(select(SequenceStep).where(
            SequenceStep.sequence_version_id == draft.id).order_by(SequenceStep.position))
        if first.configuration.get(METADATA_KEY, {}).get("base_published") != body.expected_published.model_dump():
            raise HTTPException(409, "Draft was created against another published graph; merge changes first")
        first.configuration = {**first.configuration, METADATA_KEY: {
            **first.configuration[METADATA_KEY], "published_owner": True,
        }}
        # Sequence is a shared registry row. Editable labels live in this version's
        # metadata; changing the shared row would rewrite unmarked historical exports.
        for active in session.scalars(select(SequenceVersion).where(
            SequenceVersion.sequence_id == sequence.id, SequenceVersion.status == "published"
        )):
            active.status = "archived"
        draft.status = "published"
        draft.published_at = datetime.now(UTC)
        session.commit()
        return load_source(session, code)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Graph revision conflict") from error
    except Exception:
        session.rollback()
        raise
