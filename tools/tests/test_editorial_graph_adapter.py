from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.editorial_graph_adapter import discover, normalize, parse, publish, read


def original(code="welcome_intensive"):
    return {"schema_version": 1, "sequence": {"code": code, "name": "Оригинальная цепочка", "description": None,
        "status": "published"}, "steps": [{"step_key": "stop", "position": 1, "kind": "STOP", "label": "Финал",
        "content_code": None, "delay_seconds": None, "next_step_key": None,
        "configuration": {"opaque": {"list": [None, False, 0]}}, "enabled": True}], "edges": []}


def canonical(data):
    data = deepcopy(data)
    data["steps"].sort(key=lambda step: step["position"])
    data["edges"].sort(key=lambda edge: (edge["from_step_key"], edge["branch_key"], edge["priority"]))
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def edition(data, version, status="published"):
    source = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    semantic = deepcopy(data)
    for step in semantic["steps"]:
        step["configuration"].pop("_editorial_graph", None)
    return {"version": version, "version_id": f"version-{version}", "status": status,
        "sha256": hashlib.sha256(canonical(data).encode()).hexdigest(),
        "semantic_sha256": hashlib.sha256(canonical(semantic).encode()).hexdigest(),
        "source": source, "document": deepcopy(data)}


def revision(raw):
    return {"version": raw["version"], "sha256": raw["sha256"]}


class FakeGraphAPI:
    def __init__(self):
        self.states = {code: {"ok": True, "code": code, "published": edition(original(code), 7),
            "draft": None, "editorial_owned": False} for code in ("welcome_intensive", "prepurchase_nurture")}
        self.calls = []
        self.counter = 12  # Existing archived drafts make the next publication jump.
        self.lose = None
        self.fail_before = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        code = path.split("/")[3]
        state = self.states[code]
        if method == "GET":
            return deepcopy(state)
        if self.fail_before == method:
            raise TimeoutError("Request not accepted")
        assert payload["expected_published"] == revision(state["published"])
        if method == "PUT":
            assert payload["expected_draft"] is None and state["draft"] is None
            data = json.loads(payload["source"])
            self.counter += 4
            data["steps"][0]["configuration"]["_editorial_graph"] = {
                "owner": "messaging.telegram.engine", "schema_version": 1, "published_owner": False,
                "sequence": deepcopy(data["sequence"]), "base_published": revision(state["published"]),
            }
            state["draft"] = edition(data, self.counter, "draft")
        else:
            assert method == "POST"
            assert payload["expected_draft"] == revision(state["draft"])
            data = deepcopy(state["draft"]["document"])
            assert data["steps"][0]["configuration"]["_editorial_graph"]["base_published"] == revision(state["published"])
            data["steps"][0]["configuration"]["_editorial_graph"]["published_owner"] = True
            state["published"] = edition(data, state["draft"]["version"])
            state["draft"] = None
            state["editorial_owned"] = True
        if self.lose == method:
            self.lose = None
            raise TimeoutError("Accepted response lost")
        return deepcopy(state)


@pytest.fixture
def context():
    api = FakeGraphAPI()
    item = {"code": "welcome_intensive", "kind": "graph"}
    remote = read(api, item)
    data = parse(remote["text"])
    data["steps"][0]["label"] = "Редакция владельца"
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return api, item, remote, text


def writes(api):
    return [call for call in api.calls if call[0] != "GET"]


def test_discovery_is_fixed_two_actual_originals_with_readable_json_fence():
    api = FakeGraphAPI()
    items = discover(api)
    assert set(items) == {"graph:welcome_intensive", "graph:prepurchase_nurture"}
    assert len(api.calls) == 2
    for item in items.values():
        result = read(api, item)
        assert result["version"] == revision(api.states[item["code"]]["published"])
        assert result["text"].startswith("---\ncode:")
        assert "```json\n" in result["text"]
        assert parse(result["text"]) == original(item["code"])
        assert result["pending_draft"] is None


def test_normalization_strips_only_header_and_reserved_inert_stamp(context):
    api, item, remote, text = context
    stamped = parse(remote["text"])
    stamped["steps"][0]["configuration"]["_editorial_graph"] = {
        "owner": "messaging.telegram.engine", "schema_version": 1, "published_owner": True,
        "base_published": remote["version"], "sequence": stamped["sequence"],
    }
    assert normalize(json.dumps(stamped)) == normalize(remote["text"])
    assert normalize(remote["text"].replace("version: 7", "version: 42").replace("\n", "\r\n")) == normalize(remote["text"])
    stamped["steps"][0]["configuration"]["opaque"]["list"].append("new runtime original")
    assert normalize(json.dumps(stamped)) != normalize(remote["text"])


def test_publishes_then_verifies_without_assuming_counter_plus_one(context):
    api, item, remote, text = context
    verified = publish(api, item, text, remote)
    assert verified["version"]["version"] == 16
    assert verified["version"]["version"] != remote["version"]["version"] + 1
    assert verified["editorial_owned"]
    assert normalize(verified["text"]) == normalize(text)
    assert [call[0] for call in writes(api)] == ["PUT", "POST"]
    assert api.calls[-1][0] == "GET"


def test_identical_original_can_transition_to_canonical_ownership_without_behavior_change(context):
    api, item, remote, _ = context
    result = publish(api, item, remote["text"], remote)
    assert result["editorial_owned"]
    assert normalize(result["text"]) == normalize(remote["text"])
    publish(api, item, remote["text"], remote)
    assert [call[0] for call in writes(api)] == ["PUT", "POST"]


def test_matching_existing_draft_is_reused_and_full_revision_is_returned(context):
    api, item, remote, text = context
    api.request("PUT", "/bot-api/sequences/welcome_intensive/source/draft", {
        "source": text, "expected_published": remote["version"], "expected_draft": None,
    })
    pending = read(api, item)
    assert pending["pending_draft"] == pending["draft"]["version"]
    assert pending["draft_base"] == remote["version"]
    assert pending["draft"]["document"] == api.states[item["code"]]["draft"]["document"]
    api.calls.clear()
    assert publish(api, item, text, pending)["editorial_owned"]
    assert [call[0] for call in writes(api)] == ["POST"]


@pytest.mark.parametrize("case", ["different", "stale", "missing_base"])
def test_other_or_stale_server_draft_is_preserved(context, case):
    api, item, remote, text = context
    api.request("PUT", "/bot-api/sequences/welcome_intensive/source/draft", {
        "source": text, "expected_published": remote["version"], "expected_draft": None,
    })
    state = api.states[item["code"]]
    data = deepcopy(state["draft"]["document"])
    if case == "different": data["steps"][0]["label"] = "Другой автор"
    elif case == "stale": data["steps"][0]["configuration"]["_editorial_graph"]["base_published"]["version"] = 1
    else: del data["steps"][0]["configuration"]["_editorial_graph"]["base_published"]
    state["draft"] = edition(data, 16, "draft")
    before = deepcopy(state)
    api.calls.clear()
    with pytest.raises(ValueError, match="черновик"):
        publish(api, item, text, remote)
    assert writes(api) == []
    assert state == before


@pytest.mark.parametrize("method", ["PUT", "POST"])
def test_lost_accepted_response_recovers_without_duplicate_submission(context, method):
    api, item, remote, text = context
    api.lose = method
    accepted = publish(api, item, text, remote)
    assert normalize(accepted["text"]) == normalize(text)
    publish(api, item, text, remote)
    assert [call[0] for call in writes(api)] == ["PUT", "POST"]


def test_unaccepted_request_is_not_blindly_retried(context):
    api, item, remote, text = context
    api.fail_before = "PUT"
    with pytest.raises(TimeoutError):
        publish(api, item, text, remote)
    assert [call[0] for call in writes(api)] == ["PUT"]
    assert api.states[item["code"]]["draft"] is None


def test_concurrent_published_original_is_never_overwritten(context):
    api, item, remote, text = context
    newer = original()
    newer["steps"][0]["label"] = "Независимые изменения"
    api.states[item["code"]]["published"] = edition(newer, 13)
    with pytest.raises(ValueError, match="изменился"):
        publish(api, item, text, remote)
    assert writes(api) == []


def test_api_source_integrity_and_cross_flow_identity_are_verified(context):
    api, item, _, _ = context
    api.states[item["code"]]["published"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Хеш"):
        read(api, item)
    with pytest.raises(ValueError, match="не поддерживается"):
        read(api, {"code": "postpurchase_masterclass"})


def test_missing_publication_is_not_replaced_by_a_draft(context):
    api, item, _, _ = context
    api.states[item["code"]]["draft"] = edition(original(), 8, "draft")
    api.states[item["code"]]["published"] = None
    with pytest.raises(ValueError, match="нет опубликованного"):
        read(api, item)


def test_wrong_local_flow_fails_before_writing(context):
    api, item, remote, _ = context
    with pytest.raises(ValueError, match="не совпадает"):
        publish(api, item, json.dumps(original("prepurchase_nurture")), remote)
    assert writes(api) == []


def test_real_bot_api_roundtrip_matches_adapter_and_keeps_run_pin(tmp_path):
    # Isolate the Telegram `app` package from the backend package used by other tool tests.
    script = r'''
import json, sys
from copy import deepcopy
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import main
from app.database import Base, make_engine, get_db
from app.engine import start_run
from app.models import BotInstance, Contact, SequenceRun, StepDelivery
from app.seed import seed_defaults
from tools.editorial_graph_adapter import read, publish, normalize, parse

engine = make_engine('sqlite:///' + sys.argv[1])
Base.metadata.create_all(engine)
with Session(engine, expire_on_commit=False) as session:
    seed_defaults(session, 'TetrisgfgfgfBot')
    bot = session.scalar(select(BotInstance))
    contact = Contact(bot_instance_id=bot.id, telegram_user_id='graph-adapter-pin', chat_id='graph-adapter-pin')
    session.add(contact); session.flush()
    run = start_run(session, contact.id, 'welcome_intensive')
    session.commit(); session.refresh(run)
    before = (run.sequence_version_id, run.current_step_key, run.next_action_at, deepcopy(run.context), run.status)
    main.settings.admin_username = 'graph-adapter-owner'
    main.settings.admin_password = 'local-test-password'
    main.app.dependency_overrides[get_db] = lambda: session
    client = TestClient(main.app)
    client.auth = ('graph-adapter-owner', 'local-test-password')
    class Transport:
        def __init__(self): self.calls = []
        def request(self, method, path, payload=None):
            self.calls.append((method, path))
            response = client.request(method, path, json=payload)
            if response.status_code != 200: raise RuntimeError(response.text)
            return response.json()
    api = Transport()
    for code in ('welcome_intensive', 'prepurchase_nurture'):
        item = {'code': code}
        remote = read(api, item)
        accepted = publish(api, item, remote['text'], remote)
        assert accepted['editorial_owned']
        assert normalize(accepted['text']) == normalize(remote['text'])
        marker = min(parse(accepted['text'])['steps'], key=lambda step: step['position'])['configuration']['_editorial_graph']
        assert marker['base_published'] == remote['version']
        writes = len([call for call in api.calls if call[0] != 'GET'])
        publish(api, item, remote['text'], remote)
        assert len([call for call in api.calls if call[0] != 'GET']) == writes
    seed_defaults(session, 'TetrisgfgfgfBot', enable_subscription_checks=True)
    session.refresh(run)
    assert (run.sequence_version_id, run.current_step_key, run.next_action_at, run.context, run.status) == before
    assert len(session.scalars(select(SequenceRun)).all()) == 1
    assert not session.scalars(select(StepDelivery)).all()
    main.app.dependency_overrides.clear()
engine.dispose()
'''
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(root / "telegram-bot/service"),
           "DATABASE_URL": "sqlite+pysqlite:///:memory:"}
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path / "real-api.sqlite")],
                               cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
