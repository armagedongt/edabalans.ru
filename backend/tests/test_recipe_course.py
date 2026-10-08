from datetime import datetime, timezone
from copy import deepcopy

from sqlalchemy import select

from test_recipe_calculator import grant_user, make_client, sign_in
from app.course_material_service import publish_material
from app.models import CourseStepProgress, Resource, UserAccess, UserCoursePolicy
from app.recipe_course_service import GROUPS, PLACEHOLDERS
from app.course_structure_service import course_context, DOCUMENT_TYPE, DOCUMENT_KEY, MANAGED_SCHEMA_VERSION
from app.managed_documents import publish_document


def test_standalone_recipe_course_uses_own_right_and_shared_published_materials(monkeypatch, tmp_path):
    import app.course_material_service as material_service
    monkeypatch.setattr(material_service, "COURSE_CONTENT_ROOT", tmp_path)
    client, factory = make_client()
    try:
        with factory() as db:
            user = grant_user(db, "recipes-only@example.test")
            db.query(UserAccess).filter(UserAccess.user_id == user.id).delete()
            resource = Resource(code="ACCESS_RECIPES", name="Система рецептов", status="active")
            db.add(resource)
            db.flush()
            db.add(UserAccess(
                user_id=user.id,
                resource_id=resource.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            ))
            db.add(UserCoursePolicy(
                user_id=user.id,
                resource_id=resource.id,
                start_mode="auto",
                source="test",
            ))
            context = course_context(db)
            structure = deepcopy(context.revision.payload)
            day = structure["days"][14]
            catalog = next(s for s in day["steps"] if s["id"] == "day-15-recipes-part-2")
            catalog.update(kind="article", contentKind="text", locked=False, placeholder=False,
                           hidden=False, status="ready", code="recipes-part-2")
            for sid, flags in (("day-15-recipe-caesar", {}),
                               ("day-15-recipe-unpublished", {}),
                               ("day-15-recipe-hidden", {"hidden": True})):
                day["steps"].append(dict(id=sid, kind="article", contentKind="text",
                                         title=sid, nested=True, required=False,
                                         parentStepId=catalog["id"], **flags))
            publish_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
                             schema_version=MANAGED_SCHEMA_VERSION, payload=structure,
                             expected_version=context.revision.version_no, admin="test")
            publish_material(db, step_id="day-15-recipe-caesar", content="## Общий рецепт\n\nЦезарь",
                             content_format="markdown", expected_version=0, admin="test")
            publish_material(db, step_id="day-15-recipe-hidden", content="## Скрытый рецепт",
                             content_format="markdown", expected_version=0, admin="test")
            db.add(CourseStepProgress(user_id=user.id, course_code="recipes", stage_number=1,
                                      step_index=0, step_kind="article"))
            for _, step_ids in GROUPS:
                for step_id in step_ids:
                    if step_id not in PLACEHOLDERS:
                        publish_material(
                            db,
                            step_id=step_id,
                            content=f"## Общий материал\n\n{step_id}",
                            content_format="markdown",
                            expected_version=0,
                            admin="test",
                        )
            db.commit()
        sign_in(client, "recipes-only@example.test")

        manifest = client.get("/api/recipes/course/manifest")
        assert manifest.status_code == 200, manifest.text
        data = manifest.json()
        assert data["title"] == "Система рецептов"
        assert data["sourceCourse"] == "masterclass-21"
        assert data["days"][0]["steps"][0]["id"] == "day-15-recipes-part-2"
        assert data["days"][0]["steps"][0]["locked"] is False
        assert data["days"][-1]["steps"][-1]["locked"] is True

        state = client.get("/api/recipes/course")
        assert state.status_code == 200
        assert state.json()["fully_unlocked"] is True
        assert state.json()["days"][1]["completed_steps"] == [0]
        assert state.json()["days"][0]["required_steps_total"] == 1

        first_step = data["days"][0]["steps"][0]["id"]
        material = client.get("/api/recipes/course/materials", params={"step_id": first_step})
        assert material.status_code == 200
        assert first_step in material.json()["materials"]

        link = client.get("/api/account/resource-link", params={"target": f"recipes:{first_step}"})
        assert link.status_code == 200
        assert link.json()["app"] == "recipes-course"
        assert link.json()["params"]["recipes_material"] == first_step

        assert client.get("/apps/recipes-course.html").status_code == 200
        assert "/api/recipes/course" in client.get("/apps/recipes-course.html").text
        recipe = client.get("/api/recipes/course/materials", params={"step_id": "day-15-recipe-caesar"})
        assert recipe.status_code == 200, recipe.text
        assert "Общий рецепт" in recipe.json()["materials"]["day-15-recipe-caesar"]["html"]
        link = client.get("/api/account/resource-link", params={"target": "recipes:day-15-recipe-caesar"})
        assert link.json()["params"] == {"recipes_section": 1, "recipes_material": "day-15-recipe-caesar"}
        for sid in ("day-15-recipe-hidden", "day-15-recipe-unpublished", "day-07-store-food", "day-01-article-01"):
            assert client.get("/api/recipes/course/materials", params={"step_id": sid}).status_code == 404
        assert client.post("/api/recipes/course/days/2/steps/1/complete", json={}).status_code == 200
        with factory() as db:
            assert db.scalar(select(CourseStepProgress).where(
                CourseStepProgress.course_code == "recipes", CourseStepProgress.stage_number == 1,
                CourseStepProgress.step_index == 1)) is not None
        for flag in ("hidden", "locked", "placeholder"):
            with factory() as db:
                context = course_context(db)
                structure = deepcopy(context.revision.payload)
                parent = next(s for s in structure["days"][14]["steps"] if s["id"] == "day-15-recipes-part-2")
                parent.update(hidden=False, locked=False, placeholder=False)
                parent[flag] = True
                publish_document(db, document_type=DOCUMENT_TYPE, document_key=DOCUMENT_KEY,
                                 schema_version=MANAGED_SCHEMA_VERSION, payload=structure,
                                 expected_version=context.revision.version_no, admin="test")
            assert client.get("/api/recipes/course/materials", params={"step_id": "day-15-recipe-caesar"}).status_code == 404
            assert client.get("/api/account/resource-link", params={"target": "recipes:day-15-recipe-caesar"}).json()["action"] == "unavailable"
        with factory() as db:
            db.query(UserAccess).filter(UserAccess.user_id == user.id).update({"revoked_at": datetime.now(timezone.utc)})
            db.commit()
        assert client.get("/api/recipes/course/materials", params={"step_id": "day-15-recipe-caesar"}).status_code == 403
    finally:
        client.close()
        factory.kw["bind"].dispose()
