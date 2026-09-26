from datetime import datetime, timezone

from sqlalchemy import select

from test_recipe_calculator import grant_user, make_client, sign_in
from app.course_material_service import publish_material
from app.models import Resource, UserAccess, UserCoursePolicy
from app.recipe_course_service import GROUPS, PLACEHOLDERS


def test_standalone_recipe_course_uses_own_right_and_shared_published_materials():
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
        assert data["days"][-1]["steps"][-1]["locked"] is True

        state = client.get("/api/recipes/course")
        assert state.status_code == 200
        assert state.json()["fully_unlocked"] is True

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
    finally:
        client.close()
        factory.kw["bind"].dispose()
