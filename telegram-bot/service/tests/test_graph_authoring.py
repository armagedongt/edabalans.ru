from copy import deepcopy
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import Base, make_engine, get_db
from app.engine import start_run
from app.graph_authoring import (
    GraphDraftIn, GraphPublishIn, document, load_source, parse_source, publish_draft,
    save_draft, semantic_hash,
)
from app.models import BotInstance, Contact, Sequence, SequenceEdge, SequenceRun, SequenceStep, SequenceVersion, StepDelivery
from app.seed import PREPURCHASE_CODE, WELCOME_CODE, seed_defaults


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'graphs.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        seed_defaults(session, "TetrisgfgfgfBot")
        yield session
    engine.dispose()


def revision(payload):
    return {"version": payload["version"], "sha256": payload["sha256"]}


def draft_body(state, data=None):
    return GraphDraftIn(source=json.dumps(data) if data is not None else state["published"]["source"],
                        expected_published=revision(state["published"]),
                        expected_draft=revision(state["draft"]) if state["draft"] else None)


def publish_body(state):
    return GraphPublishIn(expected_published=revision(state["published"]),
                          expected_draft=revision(state["draft"]))


@pytest.mark.parametrize("code", [WELCOME_CODE, PREPURCHASE_CODE])
def test_seed_graph_roundtrip_changes_no_execution_fields(session, code):
    before = load_source(session, code)
    saved = save_draft(session, code, draft_body(before))
    assert saved["published"] == before["published"]
    assert saved["draft"]["semantic_sha256"] == before["published"]["semantic_sha256"]
    assert not saved["editorial_owned"]
    published = publish_draft(session, code, publish_body(saved))
    assert published["published"]["semantic_sha256"] == before["published"]["semantic_sha256"]
    assert published["draft"] is None
    assert published["editorial_owned"]
    versions = session.scalars(select(SequenceVersion).where(SequenceVersion.sequence_id ==
        session.scalar(select(Sequence.id).where(Sequence.code == code)))).all()
    assert [version.status for version in versions] == ["archived", "published"]


def test_roundtrip_preserves_disabled_records_nulls_priorities_nested_config_and_next(session):
    before = load_source(session, WELCOME_CODE)
    data = deepcopy(before["published"]["document"])
    data["steps"].append({"step_key": "disabled-original", "position": 1000, "kind": "STOP",
        "label": "Disabled", "content_code": "tpl_hard_sale_1", "delay_seconds": 13,
        "next_step_key": data["steps"][0]["step_key"],
        "configuration": {"opaque": {"items": [None, False, 0, "text"]}}, "enabled": False})
    data["edges"].append({"from_step_key": "disabled-original", "to_step_key": data["steps"][0]["step_key"],
        "target_sequence_code": None, "branch_key": "custom", "label": None,
        "condition": {"allow_cycle": True, "opaque": [None, 3]}, "priority": -3, "enabled": False})
    state = save_draft(session, WELCOME_CODE, draft_body(before, data))
    assert state["draft"]["semantic_sha256"] == semantic_hash(data)
    assert state["draft"]["document"]["steps"][-1] == data["steps"][-1]
    assert data["edges"][-1] in state["draft"]["document"]["edges"]


@pytest.mark.parametrize("bad", ["duplicate_step", "duplicate_position", "duplicate_edge", "unknown_content",
    "unknown_step", "unknown_target", "unknown_kind", "negative_delay", "missing_field", "wrong_code", "invalid_anchor", "non_delivery_anchor", "future_anchor"])
def test_invalid_import_rolls_back_all_rows(session, bad):
    state = load_source(session, WELCOME_CODE)
    data = deepcopy(state["published"]["document"])
    if bad == "duplicate_step": data["steps"].append(deepcopy(data["steps"][0]))
    elif bad == "duplicate_position": data["steps"][1]["position"] = data["steps"][0]["position"]
    elif bad == "duplicate_edge": data["edges"].append(deepcopy(data["edges"][0]))
    elif bad == "unknown_content": data["steps"][0]["content_code"] = "missing"
    elif bad == "unknown_step": data["edges"][0]["to_step_key"] = "missing"
    elif bad == "unknown_target": data["edges"][0].update(to_step_key=None, target_sequence_code="missing")
    elif bad == "unknown_kind": data["steps"][0]["kind"] = "DO_SOMETHING"
    elif bad == "negative_delay": data["steps"][1]["delay_seconds"] = -1
    elif bad == "missing_field": del data["steps"][0]["enabled"]
    elif bad == "wrong_code": data["sequence"]["code"] = "postpurchase_masterclass"
    elif bad == "invalid_anchor": data["steps"][1]["configuration"]["anchor_step"] = "missing"
    elif bad == "non_delivery_anchor":
        delay = next(step for step in data["steps"] if step["kind"] == "DELAY")
        delay["configuration"]["anchor_step"] = delay["step_key"]
    elif bad == "future_anchor":
        delay = next(step for step in data["steps"] if step["kind"] == "DELAY")
        delay["configuration"]["anchor_step"] = "welcome_day2"
    before = session.scalar(select(func.count(SequenceVersion.id)))
    with pytest.raises(ValueError):
        save_draft(session, WELCOME_CODE, draft_body(state, data))
    assert session.scalar(select(func.count(SequenceVersion.id))) == before
    assert load_source(session, WELCOME_CODE) == state


def test_conflicts_prevent_stale_draft_save_and_publication(session):
    original = load_source(session, WELCOME_CODE)
    first = save_draft(session, WELCOME_CODE, draft_body(original))
    with pytest.raises(HTTPException) as conflict:
        save_draft(session, WELCOME_CODE, draft_body(original))
    assert conflict.value.status_code == 409
    second = save_draft(session, WELCOME_CODE, draft_body(first))
    with pytest.raises(HTTPException) as conflict:
        publish_draft(session, WELCOME_CODE, publish_body(first))
    assert conflict.value.status_code == 409
    current = publish_draft(session, WELCOME_CODE, publish_body(second))
    with pytest.raises(HTTPException) as conflict:
        save_draft(session, WELCOME_CODE, draft_body(second))
    assert conflict.value.status_code == 409
    assert load_source(session, WELCOME_CODE) == current


def test_published_original_survives_seed_and_keeps_active_run_pin_and_archived_steps(session, monkeypatch):
    from app import engine as runtime
    from app import telegram
    monkeypatch.setattr(runtime, "advance_run", lambda *args, **kwargs: pytest.fail("Import must not advance"))
    monkeypatch.setattr(runtime, "start_run", lambda *args, **kwargs: pytest.fail("Import must not start"))
    monkeypatch.setattr(telegram.TelegramClient, "send_content", lambda *args, **kwargs: pytest.fail("Import must not send"))
    state = load_source(session, WELCOME_CODE)
    bot = session.scalar(select(BotInstance))
    contact = Contact(bot_instance_id=bot.id, telegram_user_id="original-pin", chat_id="original-pin")
    session.add(contact); session.flush()
    run = start_run(session, contact.id, WELCOME_CODE)
    run.status = "waiting"
    run.context = {"keep": True}
    session.commit()
    session.refresh(run)
    pin = (run.sequence_version_id, run.current_step_key, run.next_action_at, deepcopy(run.context), run.status)
    old_version = session.get(SequenceVersion, pin[0])
    sequence = session.get(Sequence, old_version.sequence_id)
    old_link = session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id == old_version.id,
        SequenceStep.step_key == "welcome_day2"))
    old_link.configuration = {"buttons": [{"text": "Archived original", "url": "https://example.com/original"}]}
    session.commit()
    state = load_source(session, WELCOME_CODE)
    old_rows = document(session, sequence, old_version)
    data = deepcopy(state["published"]["document"])
    data["sequence"]["name"] = "Original edited name"
    data["sequence"]["description"] = "Original edited description"
    data["steps"] = [{"step_key": "owner-stop", "position": 1, "kind": "STOP", "label": "Original stop",
        "content_code": None, "delay_seconds": None, "next_step_key": None, "configuration": {}, "enabled": True}]
    data["edges"] = []
    draft = save_draft(session, WELCOME_CODE, draft_body(state, data))
    published = publish_draft(session, WELCOME_CODE, publish_body(draft))
    assert published["published"]["document"]["sequence"] == data["sequence"]
    assert document(session, sequence, old_version) == old_rows
    for _ in range(2):
        seed_defaults(session, "TetrisgfgfgfBot", enable_subscription_checks=True)
        assert load_source(session, WELCOME_CODE) == published
        session.refresh(run)
        assert (run.sequence_version_id, run.current_step_key, run.next_action_at, run.context, run.status) == pin
        archived = document(session, sequence, old_version)
        assert archived == old_rows
    assert session.scalar(select(func.count(StepDelivery.id))) == 0
    assert session.scalar(select(func.count(SequenceRun.id))) == 1
    # Even returning publication to an older edition must not restore seed ownership.
    session.get(SequenceVersion, published["published"]["version_id"]).status = "archived"
    old_version.status = "published"
    session.commit()
    before = load_source(session, WELCOME_CODE)
    seed_defaults(session, "TetrisgfgfgfBot", enable_subscription_checks=True)
    assert load_source(session, WELCOME_CODE) == before
    assert before["published"]["document"] == old_rows


def test_source_accepts_json_fence_but_rejects_duplicate_json_fields_and_nan(session):
    source = load_source(session, WELCOME_CODE)["published"]["source"]
    assert parse_source("```json\n" + source.rstrip() + "\n```", WELCOME_CODE)
    assert parse_source(("```json\n" + source.rstrip() + "\n```").replace("\n", "\r\n"), WELCOME_CODE)
    with pytest.raises(ValueError):
        parse_source(source.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'), WELCOME_CODE)
    with pytest.raises(ValueError):
        parse_source(source.replace('"schema_version": 1', '"schema_version": NaN'), WELCOME_CODE)


@pytest.mark.parametrize("config", [{"true_step": []}, {"anchor_step": {}}, {"target_sequence": []},
    {"timeout_seconds": "soon"}, {"buttons": None}, {"buttons": [{"text": "Open", "url": []}]},
    {"context_values": []}, {"_editorial_graph": {"owner": "other"}}])
def test_malformed_runtime_configuration_is_rejected_without_partial_draft(session, config):
    state = load_source(session, WELCOME_CODE)
    data = deepcopy(state["published"]["document"])
    data["steps"][0]["configuration"].update(config)
    with pytest.raises(ValueError):
        save_draft(session, WELCOME_CODE, draft_body(state, data))
    assert load_source(session, WELCOME_CODE) == state


def test_new_draft_does_not_claim_seed_ownership_and_expected_hash_is_required(session):
    state = load_source(session, WELCOME_CODE)
    data = deepcopy(state["published"]["document"])
    data["sequence"]["name"] = "Only a draft"
    saved = save_draft(session, WELCOME_CODE, draft_body(state, data))
    assert saved["published"] == state["published"]
    assert saved["draft"]["document"]["sequence"]["name"] == "Only a draft"
    assert not saved["editorial_owned"]
    seed_defaults(session, "TetrisgfgfgfBot")
    assert load_source(session, WELCOME_CODE) == saved
    body = publish_body(saved)
    body.expected_draft.sha256 = "0" * 64
    with pytest.raises(HTTPException) as conflict:
        publish_draft(session, WELCOME_CODE, body)
    assert conflict.value.status_code == 409
    assert load_source(session, WELCOME_CODE) == saved


def test_source_body_byte_limit_applies_before_database_writes(session):
    state = load_source(session, WELCOME_CODE)
    body = draft_body(state)
    body.source = "я" * 250_001
    with pytest.raises(ValueError, match="500 KB"):
        save_draft(session, WELCOME_CODE, body)
    assert load_source(session, WELCOME_CODE) == state


def test_stale_draft_base_cannot_publish_with_refetched_current_revision(session):
    original = load_source(session, WELCOME_CODE)
    saved = save_draft(session, WELCOME_CODE, draft_body(original))
    draft_id = saved["draft"]["version_id"]
    # The existing unmarked bootstrap can publish a new runtime edition while a draft exists.
    seed_defaults(session, "TetrisgfgfgfBot", enable_subscription_checks=True)
    current = load_source(session, WELCOME_CODE)
    assert current["published"]["version"] != original["published"]["version"]
    assert current["draft"]["version_id"] == draft_id
    before = deepcopy(current)
    with pytest.raises(HTTPException) as conflict:
        publish_draft(session, WELCOME_CODE, publish_body(current))
    assert conflict.value.status_code == 409
    assert load_source(session, WELCOME_CODE) == before


def test_source_api_auth_allowlist_and_revision_conflict(session, monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings, "admin_username", "graph-owner")
    monkeypatch.setattr(main.settings, "admin_password", "graph-test-password")
    main.app.dependency_overrides[get_db] = lambda: session
    client = TestClient(main.app)
    base = f"/bot-api/sequences/{WELCOME_CODE}/source"
    try:
        assert client.get(base).status_code == 401
        client.auth = ("graph-owner", "graph-test-password")
        response = client.get(base)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        state = response.json()
        body = draft_body(state).model_dump()
        draft = client.put(base + "/draft", json=body)
        assert draft.status_code == 200
        assert client.put(base + "/draft", json=body).status_code == 409
        assert client.post(base + "/publish", json=publish_body(draft.json()).model_dump()).status_code == 200
        assert client.get("/bot-api/sequences/postpurchase_masterclass/source").status_code == 404
        invalid = draft_body(client.get(base).json()).model_dump()
        invalid["source"] = "not JSON"
        assert client.put(base + "/draft", json=invalid).status_code == 422
    finally:
        main.app.dependency_overrides.clear()
