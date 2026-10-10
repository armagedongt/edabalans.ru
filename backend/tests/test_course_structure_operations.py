from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import io
import pytest
from PIL import Image
from sqlalchemy import select
from test_masterclass_journey import setup, teardown_function
from app import course_structure_service as native
from app import course_material_service as material
from app import course_structure_operations as operations
from app.main import app
from app.blog_draft_routes import require_blog_mutation
from app.managed_documents import document_hash
from app.models import (User, MasterclassDayProgress, MasterclassStepProgress, CourseStepProgress,
                        ContentItemVersion, CourseStageProgress, CourseEvent)

ENDPOINT = "/admin/api/courses/masterclass-21/structure/operations/"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def course(monkeypatch):
    client, factory = setup()
    app.dependency_overrides[require_blog_mutation] = lambda: "test-admin"
    import app.blog_draft_routes as boundary
    monkeypatch.setattr(boundary, "admin_identity", lambda request, credentials: "test-admin")
    with factory() as db:
        context = native.course_context(db)
        structure = deepcopy(context.manifest)
        for day in structure["days"]:
            day["steps"] = []
        structure["days"][0]["steps"] = [
            {"id": "a", "kind": "article", "title": "Первая", "required": True},
            {"id": "b", "kind": "article", "title": "Вторая", "required": True},
        ]
        structure["days"][1]["steps"] = [{"id": "c", "kind": "article", "title": "Третья", "required": True}]
        context.revision.payload = native.normalize_seed(structure)
        context.revision.content_hash = document_hash(context.revision.payload)
        db.commit()
        material.publish_material(db, step_id="a", content="Первый авторский текст.", content_format="markdown",
                                  expected_version=0, admin="test")
        user = db.scalar(select(User))
        db.add_all([
            MasterclassDayProgress(user_id=user.id, day_number=1, first_opened_at=NOW,
                                  required_step_ids=["a", "b"], required_check_ids=[], structure_revision_no=1),
            MasterclassDayProgress(user_id=user.id, day_number=2, first_opened_at=NOW,
                                  required_step_ids=["c"], required_check_ids=[], structure_revision_no=1,
                                  completed_at=NOW),
            MasterclassStepProgress(user_id=user.id, day_number=1, step_index=0,
                                   step_id="a", step_kind="article", completed_at=NOW),
        ])
        db.commit()
    yield client, factory
    teardown_function()


def request(client, operation, *, version=1, action="apply"):
    return client.post(ENDPOINT + action, json={"expected_version": version, "operation": operation})


def test_reorder_preview_apply_noop_and_stale_client_preserve_material_and_progress(course):
    client, factory = course
    operation = {"type": "reorder", "unit": 1, "ids": ["b", "a"]}
    preview = request(client, operation, action="preview")
    assert preview.status_code == 200, preview.text
    with factory() as db:
        assert native.active_course_version(db).version_no == 1
        assert db.scalar(select(MasterclassStepProgress)).step_index == 0
    response = request(client, operation)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    with factory() as db:
        progress = db.scalar(select(MasterclassStepProgress))
        assert progress.step_id == "a" and progress.step_index == 1
        assert progress.completed_at.replace(tzinfo=timezone.utc) == NOW
        assert material.get_material(db, "a")["version"] == 1
        assert db.scalar(select(MasterclassDayProgress).where(MasterclassDayProgress.day_number == 2)).completed_at is not None
    path = "/api/masterclass/course/days/1/steps/0/complete"
    assert client.post(path, json={"email": "member@example.test"}).status_code == 409
    assert client.post(path, json={"email": "member@example.test", "structure_version": 1, "step_id": "a"}).status_code == 409
    assert client.post(path, json={"email": "member@example.test", "structure_version": 2, "step_id": "a"}).status_code == 409
    accepted = client.post(path, json={"email": "member@example.test", "structure_version": 2, "step_id": "b"})
    assert accepted.status_code == 200, accepted.text
    assert request(client, operation, version=2).json()["changed"] is False
    assert request(client, operation).status_code == 409


@pytest.mark.parametrize("all_existing", [False, True])
def test_move_transfers_stable_mark_obligation_without_reopening_completed_day(course, all_existing):
    client, factory = course
    response = request(client, {"type": "move", "unit": 2, "id": "a", "before_id": "c",
                                "required_for_existing": all_existing})
    assert response.status_code == 200, response.text
    with factory() as db:
        mark = db.scalar(select(MasterclassStepProgress))
        assert (mark.step_id, mark.day_number, mark.step_index) == ("a", 2, 0)
        days = {row.day_number: row for row in db.scalars(select(MasterclassDayProgress))}
        assert days[1].required_step_ids == ["b"]
        assert days[2].required_step_ids == ["c", "a"]
        assert days[2].completed_at.replace(tzinfo=timezone.utc) == NOW
        assert days[2].first_opened_at.replace(tzinfo=timezone.utc) == NOW
        step = native.course_context(db).days[2]["steps"][0]
        assert step["requiredForAllAfterRevision"] == (2 if all_existing else 0)
        item = material.material_item(db, "a")
        assert "course_day=2" in item.canonical_url and "day-2" in item.source_tags
        assert material.get_material(db, "a")["version"] == 1


@pytest.mark.parametrize("all_existing", [False, True])
def test_add_article_body_is_atomic_and_requiredness_is_explicit(course, all_existing):
    client, factory = course
    operation = {"type": "add_article", "unit": 1, "id": "new-article", "title": "Новая статья",
                 "content": "Новый авторский текст.", "required": True, "required_for_existing": all_existing}
    response = request(client, operation)
    assert response.status_code == 200, response.text
    with factory() as db:
        context = native.course_context(db)
        step = context.days[1]["steps"][-1]
        assert step["id"] == "new-article" and "contentAsset" not in step
        row = db.scalar(select(MasterclassDayProgress).where(MasterclassDayProgress.day_number == 1))
        assert ("new-article" in native.effective_required_step_ids(context, row, 1)) == all_existing
        assert material.get_material(db, "new-article")["source_content"] == operation["content"]
    assert request(client, operation, version=2).status_code == 422


def test_add_picture_and_forced_body_failure_rolls_back_structure_marks_and_media(course, monkeypatch):
    client, factory = course
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, format="PNG")
    raw = output.getvalue()
    name = hashlib.sha256(raw).hexdigest() + ".png"
    from app.editorial_media import image_url
    operation = {"type": "add_article", "unit": 1, "id": "new-picture", "title": "Фото",
        "content": f"![Фото]({image_url('course:masterclass-21:new-picture', name)})\n",
        "required": False, "required_for_existing": False,
        "media": [{"name": name, "content_base64": base64.b64encode(raw).decode(), "alt": "Фото", "provenance": "owner-upload"}]}
    original = material.publish_material
    def failure(*args, **kwargs):
        raise ValueError("Forced body error")
    monkeypatch.setattr(material, "publish_material", failure)
    with pytest.raises(ValueError):
        request(client, operation)
    with factory() as db:
        assert native.active_course_version(db).version_no == 1
        assert db.scalar(select(MasterclassStepProgress)).step_index == 0
        assert material.material_item(db, "new-picture") is None
        from app.models import ManagedDocumentVersion
        assert not list(db.scalars(select(ManagedDocumentVersion).where(ManagedDocumentVersion.document_type == "editorial-image")))
    monkeypatch.setattr(material, "publish_material", original)
    accepted = request(client, operation)
    assert accepted.status_code == 200, accepted.text
    with factory() as db:
        assert name in material.get_material(db, "new-picture")["html"]


def test_invalid_permutation_anchor_and_special_move_have_no_effect(course):
    client, factory = course
    for operation in [
        {"type": "reorder", "unit": 1, "ids": ["a", "a"]},
        {"type": "reorder", "unit": 1, "ids": ["a"]},
        {"type": "move", "unit": 2, "id": "a", "required_for_existing": False, "before_id": "missing"},
        {"type": "move", "unit": 1, "id": "c"},
    ]:
        assert request(client, operation).status_code == 422
    with factory() as db:
        assert native.active_course_version(db).version_no == 1
    before = {"days": [{"number": 1, "steps": [{"id": "dqs", "kind": "dqs"}]}, {"number": 2, "steps": []}]}
    with pytest.raises(Exception) as error:
        operations.build(before, {"type": "move", "unit": 2, "id": "dqs", "required_for_existing": False}, 2)
    assert error.value.status_code == 422


def test_nested_group_moves_whole_and_partial_permutation_is_rejected():
    root = {"id": "parent", "kind": "article", "title": "Список"}
    child = {"id": "child", "kind": "article", "parentStepId": "parent", "nested": True, "required": False}
    before = {"days": [{"number": 1, "steps": [root, child, {"id": "other", "kind": "article"}]}, {"number": 2, "steps": []}]}
    after, source, moved = operations.build(before, {"type": "move", "id": "parent", "unit": 2, "required_for_existing": False}, 2)
    assert source == 1 and moved == ["parent", "child"]
    assert after["days"][1]["steps"][1] == child
    assert before["days"][0]["steps"] == [root, child, {"id": "other", "kind": "article"}]
    with pytest.raises(Exception):
        operations.build(before, {"type": "reorder", "unit": 1, "ids": ["parent", "other", "child"]}, 2)


def test_calorie_swap_and_cross_stage_move_preserve_collision_sensitive_rows_and_events(course):
    _, factory = course
    from app import calorie_course_service as calorie
    from app import calorie_course_material_service as calorie_material
    with factory() as db:
        context = calorie.course_context(db)
        before = deepcopy(context.manifest)
        first, second = before["days"][0]["steps"][:2]
        user = db.scalar(select(User))
        for index, step in enumerate((first, second)):
            db.add(CourseStepProgress(user_id=user.id, course_code="calories", stage_number=1,
                                     step_index=index, step_kind="article", completed_at=NOW))
            db.add(CourseEvent(user_id=user.id, course_code="calories", event_key=f"stage:1:step:{index}:completed",
                               event_type="calories_material_completed", details={"stage": 1, "step_index": index, "step_id": step["id"]}))
        db.commit()
        ids = [step["id"] for step in before["days"][0]["steps"]]
        ids[:2] = reversed(ids[:2])
        response = operations.apply(db, "calories", 1, {"type": "reorder", "unit": 1, "ids": ids}, "test")
        assert response["version"] == 2
        events = {event.details["step_id"]: event for event in db.scalars(select(CourseEvent))}
        assert events[first["id"]].event_key == "stage:1:step:1:completed"
        assert events[second["id"]].event_key == "stage:1:step:0:completed"
        response = operations.apply(db, "calories", 2, {"type": "move", "unit": 2, "id": first["id"], "required_for_existing": False}, "test")
        assert response["version"] == 3
        event = db.scalar(select(CourseEvent).where(CourseEvent.id == events[first["id"]].id))
        assert event.details["stage"] == 2 and event.event_key.startswith("stage:2:")
        assert event.occurred_at is not None


def test_operation_authentication_origin_and_stream_limit(course, monkeypatch):
    client, factory = course
    import app.blog_draft_routes as boundary
    app.dependency_overrides.pop(require_blog_mutation)
    operation = {"type": "reorder", "unit": 1, "ids": ["b", "a"]}
    monkeypatch.setattr(boundary, "admin_identity", lambda request, credentials: None)
    assert request(client, operation).status_code == 401
    monkeypatch.setattr(boundary, "admin_identity", lambda request, credentials: "test-admin")
    assert client.post(ENDPOINT + "apply", json={"expected_version": 1, "operation": operation},
                       headers={"Origin": "https://foreign.example"}).status_code == 403
    assert client.post(ENDPOINT + "apply", content=b"x" * (8 * 1024 * 1024 + 1),
                       headers={"Authorization": "Basic Zml4dHVyZTpmaXh0dXJl", "Content-Type": "application/json"}).status_code == 413
    with factory() as db:
        assert native.active_course_version(db).version_no == 1


def test_recipe_nested_positions_follow_reorder_without_reset(course):
    _, factory = course
    root={"id":"day-15-recipes-part-2","kind":"article"}
    children=[{"id":ident,"kind":"article","nested":True,"parentStepId":root["id"]} for ident in ("day-15-recipe-one","day-15-recipe-two")]
    before={"days":[{"number":15,"steps":[root,*children]}]}
    after,_,_=operations.build(before,{"type":"reorder","unit":15,"ids":[root["id"],children[1]["id"],children[0]["id"]]},2)
    old,new=operations.recipe_positions(before),operations.recipe_positions(after)
    with factory() as db:
        user=db.scalar(select(User))
        db.add(CourseStepProgress(user_id=user.id,course_code="recipes",stage_number=old[children[0]["id"]][0],
             step_index=old[children[0]["id"]][1],step_kind="article",completed_at=NOW))
        db.commit()
        operations.remap_rows(db,"recipes",before,after,coordinate_maps=(old,new))
        db.commit()
        row=db.scalar(select(CourseStepProgress).where(CourseStepProgress.course_code=="recipes"))
        assert (row.stage_number,row.step_index)==new[children[0]["id"]]
        assert row.completed_at.replace(tzinfo=timezone.utc)==NOW
