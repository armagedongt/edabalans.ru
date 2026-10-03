import copy
from datetime import datetime, timezone

from test_masterclass_journey import setup, teardown_function
import pytest
from sqlalchemy import select

from app.course_structure_service import (
    active_course_version, DOCUMENT_TYPE, DOCUMENT_KEY, MANAGED_SCHEMA_VERSION,
)
from app.managed_documents import publish_document
from app.course_material_service import publish_material
from app.models import Resource, UserAccess, UserEmail
from app.masterclass_routes import manifest_for_resources

PARENT = "day-15-recipes-part-2"
CHILD = "day-15-recipe-caesar"
FREE = "day-15-test-free-article"


@pytest.mark.parametrize("parent_flag", ["hidden", "locked"])
def test_day15_recipe_catalog_keeps_paid_access_and_direct_nested_links(parent_flag):
    client, factory = setup()
    with factory() as db:
        user_id = db.scalar(select(UserEmail.user_id).where(
            UserEmail.email_normalized == "member@example.test"))
        current = active_course_version(db)
        payload = copy.deepcopy(current.payload)
        before_day7 = manifest_for_resources(payload, {"ACCESS_MASTERCLASS"})["days"][6]
        day = payload["days"][14]
        # Exercise the catalog boundary independently of any existing day-wide gate.
        day.pop("accessResource", None)
        day.pop("accessCode", None)
        parent = next(s for s in day["steps"] if s["id"] == PARENT)
        parent.update(kind="article", code="recipes-part-2", contentKind="text",
                      accessResource="ACCESS_RECIPES", hidden=False, locked=False,
                      required=False, status="ready")
        day["steps"].extend([
            dict(id=FREE, kind="article", contentKind="text", title="Кухня", required=False),
            dict(id=CHILD, kind="article", contentKind="text", title="Цезарь", required=False,
                 nested=True, parentStepId=PARENT, accessResource="ACCESS_RECIPES"),
        ])
        publish_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
                         schema_version=MANAGED_SCHEMA_VERSION, payload=payload,
                         expected_version=current.version_no, admin="test")
        for step_id in (PARENT, CHILD, FREE):
            publish_material(db, step_id=step_id, content="Текст " + step_id,
                             content_format="markdown", expected_version=0, admin="test")
        assert manifest_for_resources(payload, {"ACCESS_MASTERCLASS"})["days"][6] == before_day7
    assert client.put(f"/admin/api/users/{user_id}/course-policies/ACCESS_MASTERCLASS",
                      json={"unlock_mode":"fully_unlocked"}).status_code == 200
    assert client.post("/api/masterclass/course/days/15/open",
                       json={"email":"member@example.test"}).status_code == 200
    params = {"email":"member@example.test"}
    manifest = client.get("/api/masterclass/course/manifest", params=params).json()
    steps = {s["id"]:s for s in manifest["days"][14]["steps"]}
    assert steps[PARENT]["kind"] == "recipes-part-2" and steps[PARENT]["accessGate"]
    assert steps[CHILD]["hidden"] and not steps[FREE].get("hidden")
    materials = client.get("/api/masterclass/course/materials", params=params).json()["materials"]
    assert FREE in materials and PARENT not in materials and CHILD not in materials
    for step_id in (PARENT, CHILD):
        result = client.get("/api/account/resource-link", params={"target":"masterclass-21:"+step_id}).json()
        assert result["action"] == "offer" and result["product_code"] == "recipes"
    with factory() as db:
        resource = db.scalar(select(Resource).where(Resource.code == "ACCESS_RECIPES"))
        db.add(UserAccess(user_id=user_id, resource_id=resource.id, source="test",
                          granted_at=datetime.now(timezone.utc)))
        db.commit()
    result = client.get("/api/account/resource-link", params={"target":"masterclass-21:"+CHILD}).json()
    assert result["action"] == "open" and result["params"] == {"course_day":15,"course_material":CHILD}
    materials = client.get("/api/masterclass/course/materials", params={**params,"step_id":CHILD}).json()["materials"]
    assert materials[CHILD]["html"] == "<p>Текст " + CHILD + "</p>"
    with factory() as db:
        current = active_course_version(db)
        payload = copy.deepcopy(current.payload)
        next(s for s in payload["days"][14]["steps"] if s["id"] == PARENT)[parent_flag] = True
        publish_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
                         schema_version=MANAGED_SCHEMA_VERSION, payload=payload,
                         expected_version=current.version_no, admin="test")
    assert client.get("/api/masterclass/course/materials", params={**params,"step_id":CHILD}).json()["materials"] == {}
    assert client.get("/api/account/resource-link", params={"target":"masterclass-21:"+CHILD}).json()["action"] == "unavailable"
