import os
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.auth import require_admin  # noqa: E402
from app.app_auth import create_placement_token  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.masterclass_routes import current_required_step_ids  # noqa: E402
from app.legal_service import LEGAL_DOCUMENTS  # noqa: E402
from app.masterclass_offer_catalog import OFFER_CARD_COPY, OFFER_PRODUCTS  # noqa: E402
from app.course_structure_service import (  # noqa: E402
    course_context,
    effective_required_check_ids,
)
from app.masterclass_article_components import render_masterclass_component  # noqa: E402
from app.models import (  # noqa: E402
    ContentItem, ContentItemVersion, ContentSource,
    MasterclassDayProgress, MasterclassEvent, MasterclassNotification,
    MessengerAccount, MessengerLinkToken, OfferCheckout, OfferStage, Payment, Product,
    QuestionnaireAnswer, QuestionnaireRun, Resource, User, UserAccess, UserEmail,
    UserLegalAcceptance, UserOffer,
)
from scripts.generate_masterclass_offer_simulator import (  # noqa: E402
    course_offer_scenarios,
    render_simulator,
)


TEST_SETTINGS = Settings(
    database_url="sqlite+pysqlite:///:memory:",
    admin_password="test-app-secret",
    app_auth_secret="test-client-session-secret",
    telegram_test_bot_username="EdabalansTestBot",
)


def teardown_function() -> None:
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def test_optional_course_steps_do_not_block_required_progression():
    _, factory = setup()
    with factory() as db:
        context = course_context(db)
        required = {
            day: [
                index for index, step in enumerate(context.days[day]["steps"])
                if step.get("required", True)
                and not step.get("hidden", False)
                and not step.get("locked", False)
            ]
            for day in (7, 8, 9, 15, 16)
        }
    assert required[7] == [0, 1]
    assert required[8] == [0]
    assert required[9] == []
    assert required[15] == [0, 1, 3]
    assert required[16] == [0]
    assert current_required_step_ids(context, 9) == []

    old_progress = MasterclassDayProgress(
        day_number=9,
        structure_revision_no=1,
        required_step_ids=["day-09-article-01"],
        required_check_ids=[],
        checkmarks={},
    )
    assert effective_required_step_ids(context, old_progress, 9) == []


def test_course_structure_editor_publishes_one_version_and_runtime_uses_it():
    client, _ = setup()
    response = client.get("/admin/api/courses/masterclass-21/structure")
    assert response.status_code == 200
    payload = response.json()
    manifest = payload["active"]["manifest"]
    original_title = manifest["days"][0]["title"]
    manifest["days"][0]["title"] = "Новое название первого дня"
    manifest["days"][8]["steps"][0]["locked"] = True
    manifest["days"][8]["steps"][0]["badge"] = "Скоро"

    saved = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": payload["active"]["version"], "manifest": manifest},
    )
    assert saved.status_code == 200
    assert saved.json()["active"]["version"] == payload["active"]["version"] + 1
    assert saved.json()["active"]["manifest"]["days"][0]["steps"][1][
        "contentPageTitle"
    ] == "Как вести дневник питания"
    assert saved.json()["active"]["manifest"]["days"][8]["steps"][0]["locked"] is True
    assert saved.json()["active"]["manifest"]["days"][8]["steps"][0]["badge"] == "Скоро"

    runtime = client.get(
        "/api/masterclass/course/manifest?email=member@example.test"
    )
    assert runtime.status_code == 200
    assert runtime.json()["days"][0]["title"] == "Новое название первого дня"

    conflict_manifest = payload["active"]["manifest"]
    conflict_manifest["days"][0]["title"] = original_title
    conflict = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": payload["active"]["version"], "manifest": conflict_manifest},
    )
    assert conflict.status_code == 409


def test_locked_course_step_is_not_delivered_or_completable_and_rejoins_after_unlock():
    client, _ = setup()
    editor = client.get("/admin/api/courses/masterclass-21/structure").json()
    manifest = editor["active"]["manifest"]
    step = manifest["days"][0]["steps"][1]
    step_id = step["id"]

    published = client.put(
        f"/admin/api/courses/masterclass-21/materials/{step_id}",
        json={"expected_version": 0, "content": "Тестовый материал", "format": "markdown"},
    )
    assert published.status_code == 200

    step["locked"] = True
    step["badge"] = "Скоро"
    locked = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert locked.status_code == 200
    assert locked.json()["active"]["manifest"]["days"][0]["steps"][1]["locked"] is True

    materials = client.get(
        "/api/masterclass/course/materials?email=member@example.test"
    )
    assert materials.status_code == 200
    assert step_id not in materials.json()["materials"]

    first = client.post(
        "/api/masterclass/course/days/1/steps/0/complete",
        json={"email": "member@example.test"},
    )
    assert first.status_code == 200
    rejected = client.post(
        "/api/masterclass/course/days/1/steps/1/complete",
        json={"email": "member@example.test"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["reason"] == "step_locked"

    current = locked.json()
    unlocked_manifest = current["active"]["manifest"]
    unlocked_step = unlocked_manifest["days"][0]["steps"][1]
    unlocked_step["locked"] = False
    unlocked = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={
            "expected_version": current["active"]["version"],
            "manifest": unlocked_manifest,
        },
    )
    assert unlocked.status_code == 200
    active = unlocked.json()["active"]
    reopened_step = active["manifest"]["days"][0]["steps"][1]
    assert reopened_step["requiredForAllAfterRevision"] == active["version"]
    after_unlock = client.get(
        "/api/masterclass/course?email=member@example.test"
    ).json()["days"][0]
    assert after_unlock["required_steps_total"] >= 2


def test_course_structure_history_restore_keeps_new_check_hidden_and_stable():
    client, _ = setup()
    initial = client.get("/admin/api/courses/masterclass-21/structure").json()
    manifest = initial["active"]["manifest"]
    original_title = manifest["days"][0]["title"]
    manifest["days"][0]["title"] = "Временная редакция"
    manifest["days"][0]["checks"].append({
        "id": None,
        "text": "Новый пункт",
        "required": True,
        "hidden": False,
    })
    published = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": initial["active"]["version"], "manifest": manifest},
    )
    assert published.status_code == 200
    new_check_id = published.json()["active"]["manifest"]["days"][0]["checks"][-1]["id"]

    restored = client.post(
        "/admin/api/courses/masterclass-21/structure/versions/1/restore",
        json={"expected_version": published.json()["active"]["version"]},
    )
    assert restored.status_code == 200
    body = restored.json()
    assert body["active"]["manifest"]["days"][0]["title"] == original_title
    restored_check = next(
        item for item in body["active"]["manifest"]["days"][0]["checks"]
        if item["id"] == new_check_id
    )
    assert restored_check["hidden"] is True
    assert [item["version"] for item in body["history"]][:3] == [3, 2, 1]
    assert sum(1 for item in body["history"] if item["active"]) == 1


def test_assignment_check_ids_survive_reorder_hide_and_reactivation():
    client, factory = setup()
    before = client.get("/api/masterclass/course?email=member@example.test").json()
    assert before["days"][0]["opened"] is True
    editor = client.get("/admin/api/courses/masterclass-21/structure").json()
    manifest = editor["active"]["manifest"]
    checks = manifest["days"][0]["checks"]
    first_id = checks[0]["id"]
    checks.append({"id": None, "text": "Новый пункт", "required": True, "hidden": False})
    checks[0]["hidden"] = True
    checks[0], checks[1] = checks[1], checks[0]
    changed = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert changed.status_code == 200
    changed_body = changed.json()
    changed_checks = changed_body["active"]["manifest"]["days"][0]["checks"]
    assert next(item for item in changed_checks if item["id"] == first_id)["hidden"] is True
    new_id = next(item["id"] for item in changed_checks if item["text"] == "Новый пункт")
    assert new_id.startswith("day-1-check-")

    old_participant = client.get(
        "/api/masterclass/course?email=member@example.test"
    ).json()["days"][0]
    assert old_participant["check_count"] == len(changed_checks)
    with factory() as db:
        progress = db.scalar(select(MasterclassDayProgress).where(
            MasterclassDayProgress.day_number == 1
        ))
        required = effective_required_check_ids(course_context(db), progress, 1)
        assert first_id not in required
        assert new_id not in required

    next(item for item in changed_checks if item["id"] == first_id)["hidden"] = False
    reactivated = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={
            "expected_version": changed_body["active"]["version"],
            "manifest": changed_body["active"]["manifest"],
        },
    )
    assert reactivated.status_code == 200
    visible_first = next(
        item for item in reactivated.json()["active"]["manifest"]["days"][0]["checks"]
        if item["id"] == first_id
    )
    assert visible_first["requiredForAllAfterRevision"] == reactivated.json()["active"]["version"]
    with factory() as db:
        progress = db.scalar(select(MasterclassDayProgress).where(
            MasterclassDayProgress.day_number == 1
        ))
        assert first_id in effective_required_check_ids(course_context(db), progress, 1)


def test_editor_sanitizes_allowed_html_fragments():
    client, _ = setup()
    editor = client.get("/admin/api/courses/masterclass-21/structure").json()
    manifest = editor["active"]["manifest"]
    manifest["days"][0]["intro"] = (
        '<strong onclick="alert(1)">Важно</strong>'
        '<script>alert(2)</script>'
        '<a href="javascript:alert(3)">ссылка</a>'
    )
    saved = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert saved.status_code == 200
    sanitized = saved.json()["active"]["manifest"]["days"][0]["intro"]
    assert sanitized == "<strong>Важно</strong><a>ссылка</a>"


def test_editor_hides_material_without_reindexing_and_rejects_addition():
    client, _ = setup()
    before = client.get(
        "/api/masterclass/course?email=member@example.test"
    ).json()["days"][0]
    editor = client.get("/admin/api/courses/masterclass-21/structure").json()
    manifest = editor["active"]["manifest"]
    first_id = manifest["days"][0]["steps"][0]["id"]
    second_id = manifest["days"][0]["steps"][1]["id"]
    manifest["days"][0]["steps"][0]["hidden"] = True
    hidden = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert hidden.status_code == 200
    active_steps = hidden.json()["active"]["manifest"]["days"][0]["steps"]
    assert active_steps[0]["id"] == first_id
    assert active_steps[1]["id"] == second_id

    after = client.get(
        "/api/masterclass/course?email=member@example.test"
    ).json()["days"][0]
    assert after["required_steps_total"] == before["required_steps_total"] - 1
    hidden_complete = client.post(
        "/api/masterclass/course/days/1/steps/0/complete",
        json={"email": "member@example.test"},
    )
    assert hidden_complete.status_code == 404

    current = hidden.json()
    invalid = current["active"]["manifest"]
    invalid["days"][0]["steps"].append(dict(invalid["days"][0]["steps"][1]))
    invalid["days"][0]["steps"][-1]["id"] = "day-01-new-material"
    rejected = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": current["active"]["version"], "manifest": invalid},
    )
    assert rejected.status_code == 422

    reordered = current["active"]["manifest"]
    reordered["days"][0]["steps"][0], reordered["days"][0]["steps"][1] = (
        reordered["days"][0]["steps"][1],
        reordered["days"][0]["steps"][0],
    )
    rejected = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": current["active"]["version"], "manifest": reordered},
    )
    assert rejected.status_code == 422


def test_editor_rejects_material_asset_edit_and_unsafe_media_url():
    client, _ = setup()
    editor = client.get("/admin/api/courses/masterclass-21/structure").json()
    manifest = editor["active"]["manifest"]
    manifest["days"][0]["steps"][1]["contentAsset"] = "missing-material.txt"
    broken = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert broken.status_code == 422
    assert "нельзя менять" in broken.json()["detail"]

    manifest = client.get(
        "/admin/api/courses/masterclass-21/structure"
    ).json()["active"]["manifest"]
    manifest["days"][0]["image"] = 'https://example.test/a.jpg" onerror="alert(1)'
    unsafe = client.put(
        "/admin/api/courses/masterclass-21/structure",
        json={"expected_version": editor["active"]["version"], "manifest": manifest},
    )
    assert unsafe.status_code == 422
    assert "Недопустимые символы" in unsafe.json()["detail"]


def test_course_material_publisher_preserves_article_semantics_and_runtime_override():
    client, factory = setup()
    listed = client.get("/admin/api/courses/masterclass-21/materials")
    assert listed.status_code == 200
    listed_ids = {item["step_id"] for item in listed.json()["materials"]}
    with factory() as db:
        context = course_context(db)
        expected_ids = {
            step["id"]
            for day in context.days.values()
            for step in day.get("steps", [])
            if step.get("kind") == "article"
            and step.get("contentKind") != "tutorial"
        }
    assert listed_ids == expected_ids
    assert "day-01-article-02" in listed_ids
    assert "day-01-article-tutorial" in listed_ids
    assert "day-01-questionnaire" not in listed_ids

    current = client.get(
        "/admin/api/courses/masterclass-21/materials/day-01-article-02"
    )
    assert current.status_code == 200
    assert current.json()["version"] == 0
    assert current.json()["published"] is False
    assert current.json()["html"]

    source = (
        '<h2>Что важно</h2><p>Абзац <strong>с акцентом</strong> и '
        '<a href="https://example.test/read" onclick="bad()">ссылкой</a>.</p>'
        '<ul><li>Первый пункт.</li><li>Второй пункт.</li></ul>'
        '<blockquote>Сильная самостоятельная мысль.</blockquote>'
        '<aside class="made-up"><strong>Важно</strong><p>Один тип плашки.</p></aside>'
        '<figure><img src="https://cdn.example.test/plate.jpg" alt="Тарелка" '
        'onerror="bad()"><figcaption>Пример тарелки</figcaption></figure>'
        '<section class="article-gallery" data-gallery="true" '
        'data-component="image-slider"><button class="gallery-next" '
        'data-slide="1">Подмена компонента</button></section>'
        '<script>alert(1)</script>'
    )
    published = client.put(
        "/admin/api/courses/masterclass-21/materials/day-01-article-02",
        json={"expected_version": 0, "content": source, "format": "html"},
    )
    assert published.status_code == 200
    body = published.json()
    assert body["version"] == 1
    assert body["published"] is True
    assert '<aside class="editorial-note">' in body["html"]
    assert 'target="_blank" rel="noopener"' in body["html"]
    assert 'loading="lazy"' in body["html"]
    assert "onclick" not in body["html"]
    assert "onerror" not in body["html"]
    assert "script" not in body["html"]
    assert 'class="article-gallery"' not in body["html"]
    assert "data-gallery" not in body["html"]
    assert "data-component" not in body["html"]
    assert "data-slide" not in body["html"]

    denied = client.get(
        "/api/masterclass/course/materials?email=other@example.test"
    )
    assert denied.status_code == 403
    runtime = client.get(
        "/api/masterclass/course/materials?email=member@example.test"
    )
    assert runtime.status_code == 200
    assert runtime.json()["materials"]["day-01-article-02"]["html"] == body["html"]
    with factory() as db:
        source_row = db.scalar(select(ContentSource).where(
            ContentSource.account_key == "masterclass-course-materials"
        ))
        item = db.scalar(select(ContentItem).where(
            ContentItem.source_id == source_row.id,
            ContentItem.external_id == "day-01-article-02",
        ))
        version = db.get(ContentItemVersion, item.latest_version_id)
        assert version.blocks == [{"type": "article_html", "html": body["html"]}]

    stale = client.put(
        "/admin/api/courses/masterclass-21/materials/day-01-article-02",
        json={"expected_version": 0, "content": "Новая версия", "format": "markdown"},
    )
    assert stale.status_code == 409


def test_course_material_publisher_supports_markdown_history_restore_and_blocks_special_steps():
    client, _ = setup()
    endpoint = "/admin/api/courses/masterclass-21/materials/day-03-article-02"
    first = client.put(
        endpoint,
        json={
            "expected_version": 0,
            "format": "markdown",
            "content": (
                "# Заголовок карточки\n\n## Раздел\n\n### Подраздел\n\n"
                "Абзац с **жирным** и *курсивом*.\n\n"
                "Источник: систематический обзор.\n\n"
                "- Первый пункт.\n- Второй пункт.\n\n1. Сначала.\n2. Затем.\n\n"
                "> Цитата.\n\n[Смежный материал](/apps/recipes-part-1.html)\n\n"
                "![Схема](https://cdn.example.test/schema.png \"Подпись\")\n\n"
                "![Локальная схема](/assets/course/schema.png)"
            ),
        },
    )
    assert first.status_code == 200
    assert "<h1>" not in first.json()["html"]
    assert "<h2>Раздел</h2>" in first.json()["html"]
    assert "<h3>Подраздел</h3>" in first.json()["html"]
    assert "<strong>жирным</strong>" in first.json()["html"]
    assert "<em>курсивом</em>" in first.json()["html"]
    assert "<p>Источник: систематический обзор.</p>" in first.json()["html"]
    assert "<ul><li>Первый пункт.</li><li>Второй пункт.</li></ul>" in first.json()["html"]
    assert "<ol><li>Сначала.</li><li>Затем.</li></ol>" in first.json()["html"]
    assert "<blockquote>Цитата.</blockquote>" in first.json()["html"]
    assert 'href="/apps/recipes-part-1.html"' in first.json()["html"]
    assert "<figcaption>Подпись</figcaption>" in first.json()["html"]
    assert 'src="/assets/course/schema.png"' in first.json()["html"]
    locked_runtime = client.get(
        "/api/masterclass/course/materials?email=member@example.test"
    )
    assert locked_runtime.status_code == 200
    assert "day-03-article-02" not in locked_runtime.json()["materials"]

    second = client.put(
        endpoint,
        json={"expected_version": 1, "format": "markdown", "content": "## Второй текст"},
    )
    assert second.status_code == 200
    versions = client.get(endpoint + "/versions")
    assert [row["version"] for row in versions.json()["versions"]] == [2, 1]

    restored = client.post(
        endpoint + "/versions/1/restore",
        json={"expected_version": 2},
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert restored.json()["html"] == first.json()["html"]
    stale_restore = client.post(
        endpoint + "/versions/2/restore",
        json={"expected_version": 2},
    )
    assert stale_restore.status_code == 409

    empty = client.put(
        "/admin/api/courses/masterclass-21/materials/day-03-article-03",
        json={"expected_version": 0, "format": "html", "content": "<p></p><br>"},
    )
    assert empty.status_code == 422

    rejected = client.put(
        "/admin/api/courses/masterclass-21/materials/day-01-questionnaire",
        json={"expected_version": 0, "format": "markdown", "content": "Текст"},
    )
    assert rejected.status_code == 422
    assert "специальным модулем" in rejected.json()["detail"]

    first_article = client.put(
        "/admin/api/courses/masterclass-21/materials/day-01-article-tutorial",
        json={"expected_version": 0, "format": "markdown", "content": "## Текст"},
    )
    assert first_article.status_code == 200
    assert first_article.json()["published"] is True


def test_course_material_markdown_blocks_notes_and_dqs_components():
    client, _ = setup()
    endpoint = "/admin/api/courses/masterclass-21/materials/day-04-article-01"
    content = """<!-- редакторский комментарий -->
## Раздел

Это одна мягко перенесённая
строка абзаца.

> Первая строка цитаты.
> Вторая строка цитаты.

:::note [Ориентир]
Первый абзац плашки.

Второй абзац плашки.
:::

dqs_score_table(
unhealthy
)

slider(
https://cdn.example.test/one.jpg
/assets/course/two.jpg
)

spoiler(
Составы и граммовки
**Овсянка:** хлопья — 50 г; банан — 70 г; мёд — 5 г.
)
"""
    response = client.put(
        endpoint,
        json={"expected_version": 0, "format": "markdown", "content": content},
    )
    assert response.status_code == 200
    html = response.json()["html"]
    assert "редакторский комментарий" not in html
    assert "<p>Это одна мягко перенесённая строка абзаца.</p>" in html
    assert "<blockquote>Первая строка цитаты.<br>Вторая строка цитаты.</blockquote>" in html
    assert '<aside class="editorial-note"><strong>Ориентир</strong>' in html
    assert '<table class="dqs-score-table">' in html
    assert 'data-component="image-slider"' in html
    assert html.count('class="gallery-slide"') == 2
    assert '<details class="article-spoiler">' in html
    assert "<summary>Составы и граммовки</summary>" in html
    assert "<p><strong>Овсянка:</strong> хлопья — 50 г; банан — 70 г; мёд — 5 г.</p>" in html
    course_ui = (Path(__file__).parents[1] / "app/static/masterclass-first-days-preview.html").read_text(encoding="utf-8")
    assert "closest('[data-component=\"image-slider\"]')" in course_ui
    assert '/course-assets/masterclass/article-components.css' in course_ui
    assert '/course-assets/masterclass/article-components.js' in course_ui
    assert "function bindGallery" not in course_ui
    component_css = client.get("/course-assets/masterclass/article-components.css")
    component_js = client.get("/course-assets/masterclass/article-components.js")
    assert component_css.status_code == 200
    assert ".dqs-score-table-wrap" in component_css.text
    assert ".gallery-track" in component_css.text
    assert ".article-spoiler" in component_css.text
    assert component_js.status_code == 200
    assert "global.bindGallery = bindGallery" in component_js.text

    unknown = client.put(
        endpoint,
        json={
            "expected_version": 1,
            "format": "markdown",
            "content": "unknown_component(\nvalue\n)",
        },
    )
    assert unknown.status_code == 422
    assert "Неизвестный компонент" in unknown.json()["detail"]

    unclosed = client.put(
        endpoint,
        json={
            "expected_version": 1,
            "format": "markdown",
            "content": ":::note\nТекст без закрытия",
        },
    )
    assert unclosed.status_code == 422
    assert "Незакрытая directive" in unclosed.json()["detail"]

    replacement = client.put(
        endpoint,
        json={
            "expected_version": 1,
            "format": "markdown",
            "content": "## Временная версия\n\nБез компонентов.",
        },
    )
    assert replacement.status_code == 200
    restored = client.post(
        endpoint + "/versions/1/restore",
        json={"expected_version": 2},
    )
    assert restored.status_code == 200
    restored_html = restored.json()["html"]
    assert restored_html == html
    assert '<table class="dqs-score-table">' in restored_html
    assert 'data-component="image-slider"' in restored_html
    assert 'class="gallery-arrow gallery-next"' in restored_html


def test_masterclass_component_registry_enforces_all_variants_and_slider_bounds():
    expected_rows = {
        "full": 17,
        "plants": 3,
        "protein": 2,
        "fats": 3,
        "side-dishes": 4,
        "unhealthy": 5,
    }
    for name, rows in expected_rows.items():
        rendered = render_masterclass_component("dqs_score_table", [name])
        assert rendered.count("<tr>") == rows + 1

    for image_count in (2, 20):
        arguments = [f"https://cdn.example.test/{index}.jpg" for index in range(image_count)]
        rendered = render_masterclass_component("slider", arguments)
        assert rendered.count('class="gallery-slide"') == image_count

    rendered_spoiler = render_masterclass_component(
        "spoiler", ["Расчёт", "**Овсянка:** хлопья — 50 г; банан — 70 г; мёд — 5 г."]
    )
    assert '<details class="article-spoiler">' in rendered_spoiler
    assert "<strong>Овсянка:</strong>" in rendered_spoiler

    invalid_calls = [
        ("dqs_score_table", ["missing"]),
        ("slider", ["https://cdn.example.test/one.jpg"]),
        ("slider", [f"https://cdn.example.test/{index}.jpg" for index in range(21)]),
        ("slider", ["https://cdn.example.test/one.jpg", "javascript:alert(1)"]),
        ("spoiler", ["Только заголовок"]),
        ("unknown", ["value"]),
    ]
    for component, arguments in invalid_calls:
        with pytest.raises(Exception) as raised:
            render_masterclass_component(component, arguments)
        assert getattr(raised.value, "status_code", None) == 422


def placement_token(placement: str) -> str:
    return create_placement_token(placement, TEST_SETTINGS)


def placement_query(placement: str) -> str:
    return f"placement={placement}&placement_token={placement_token(placement)}"


def test_masterclass_migration_avoids_sqlalchemy_bind_like_json_literals():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260822_0015_masterclass_journey.py"
    ).read_text(encoding="utf-8")
    assert "json_build_object('single',2900" in migration
    assert '\":2900' not in migration


def test_messenger_link_migration_stores_only_token_hash():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260823_0016_messenger_link_tokens.py"
    ).read_text(encoding="utf-8")
    assert "token_hash varchar(64) NOT NULL UNIQUE" in migration
    assert "token varchar" not in migration


def test_offer_window_migration_changes_only_future_early_duration():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260825_0023_masterclass_offer_windows.py"
    ).read_text(encoding="utf-8")
    assert "SET duration_hours = 72" in migration
    assert "duration_hours = 96" in migration
    assert "UPDATE user_offers" not in migration


def test_site_short_migration_sets_each_approved_consultation_addon():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260825_0025_site_short_offer_presentation.py"
    ).read_text(encoding="utf-8")
    for stage_code, amount in {
        "early": 7000,
        "second": 7000,
        "review": 7200,
        "last_week": 7900,
    }.items():
        assert f'"{stage_code}": {amount}' in migration
    assert "jsonb_set" in migration
    assert 'down_revision = "20260825_0024"' in migration


def setup():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def override():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    app.dependency_overrides[get_settings] = lambda: TEST_SETTINGS
    with factory() as db:
        user = User(display_name="Участник", status="active")
        db.add(user); db.flush()
        db.add(UserEmail(user_id=user.id, email_original="member@example.test", email_normalized="member@example.test", is_primary=True, source="test"))
        product = Product(code="MASTERCLASS_RECIPES", name="Мастер-класс · Стандартный", status="active")
        db.add(product); db.flush()
        db.add(Payment(
            user_id=user.id,
            product_id=product.id,
            source="test",
            external_order_id="test-masterclass-order",
            email_at_purchase="member@example.test",
            product_name_raw="Сырой параметр оплаты",
            currency="RUB",
            payment_status="paid",
            paid_at=datetime.now(timezone.utc),
        ))
        resources = {}
        for code in ("ACCESS_MASTERCLASS", "ACCESS_RECIPES", "ACCESS_CONSULTATION"):
            resources[code] = Resource(code=code, name=code, status="active")
            db.add(resources[code])
        db.flush()
        db.add(UserAccess(user_id=user.id, resource_id=resources["ACCESS_MASTERCLASS"].id, source="test", granted_at=datetime.now(timezone.utc)))
        db.add_all([
            UserLegalAcceptance(
                user_id=user.id,
                document_code=item["code"],
                document_version=item["version"],
                source="test",
            )
            for item in LEGAL_DOCUMENTS
        ])
        stages = [
            ("early", 72, {"single": 2900, "bundle": {"2": 3900, "4": 7900}, "site_short": {"consultation_addon": 7000}}),
            ("second", 72, {"single": 3300, "bundle": {"2": 4900, "4": 9900}, "site_short": {"consultation_addon": 7000}}),
            ("review", 72, {"single": 3500, "consultation": 7500, "bundle": {"2": 5700, "4": 11300}, "site_short": {"consultation_addon": 7200}}),
            ("last_week", 168, {"single": 3800, "consultation": 8400, "bundle": {"2": 7000, "4": 13800}, "site_short": {"consultation_addon": 7900}}),
            ("standard", None, {"single": 3900, "consultation": 8900, "bundle": {"2": 7800, "4": 15600}, "site_short": {}}),
        ]
        for code, hours, pricing in stages: db.add(OfferStage(code=code, name=code, duration_hours=hours, pricing=pricing, status="active"))
        db.commit()
    return TestClient(app), factory


def test_masterclass_personal_data_uses_tilda_email_and_server_access():
    client, _ = setup()
    response = client.get(
        "/api/masterclass/questionnaires/onboarding?email=member@example.test"
    )
    assert response.status_code == 200
    denied = client.get(
        "/api/masterclass/questionnaires/onboarding?email=other@example.test"
    )
    assert denied.status_code == 403


def test_questionnaire_autosaves_each_answer_and_submit_is_idempotent():
    client, factory = setup()
    opened = client.get("/api/masterclass/questionnaires/onboarding?email=member@example.test")
    assert opened.status_code == 200
    assert len(opened.json()["questions"]) == 15
    payload = {"email": "member@example.test", "question_code": "main_request", "answer_text": "Хочу наладить питание"}
    assert client.put("/api/masterclass/questionnaires/onboarding/answer", json=payload).status_code == 200
    assert client.put("/api/masterclass/questionnaires/onboarding/answer", json={**payload, "answer_text": "Обновлённый ответ"}).status_code == 200
    assert client.post("/api/masterclass/questionnaires/onboarding/submit", json={"email": "member@example.test"}).status_code == 200
    assert client.post("/api/masterclass/questionnaires/onboarding/submit", json={"email": "member@example.test"}).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count(QuestionnaireAnswer.id))) == 1
        assert db.scalar(select(QuestionnaireAnswer.answer_text)) == "Обновлённый ответ"
        assert db.scalar(select(func.count(MasterclassEvent.id))) == 1


def test_current_diet_questionnaire_saves_categories_and_queues_one_telegram_result():
    client, factory = setup()
    opened = client.get(
        "/api/masterclass/questionnaires/current-diet?email=member@example.test"
    )
    assert opened.status_code == 200
    questions = opened.json()["questions"]
    assert len(questions) == 16
    assert questions[0]["title"] == "Цельнозерновые крупы и хлеб"
    assert questions[-1]["title"] == "Вода и несладкие напитки"

    payload = {
        "email": "member@example.test",
        "question_code": "vegetables",
        "answer_text": "Огурцы и помидоры почти каждый день",
    }
    assert client.put(
        "/api/masterclass/questionnaires/current-diet/answer", json=payload
    ).status_code == 200
    for _ in range(2):
        assert client.post(
            "/api/masterclass/questionnaires/current-diet/submit",
            json={"email": "member@example.test"},
        ).status_code == 200

    with factory() as db:
        run = db.scalar(
            select(QuestionnaireRun).where(QuestionnaireRun.kind == "current-diet")
        )
        assert run is not None
        assert run.status == "submitted"
        assert db.scalar(
            select(QuestionnaireAnswer.answer_text).where(
                QuestionnaireAnswer.run_id == run.id,
                QuestionnaireAnswer.question_code == "vegetables",
            )
        ) == "Огурцы и помидоры почти каждый день"
        notifications = list(db.scalars(select(MasterclassNotification)))
        assert len(notifications) == 1
        assert notifications[0].notification_kind == "current_diet_questionnaire"
        assert notifications[0].content_code == "tpl_postpurchase_current_diet"
        assert db.scalar(
            select(func.count(MasterclassEvent.id)).where(
                MasterclassEvent.event_type == "current_diet_questionnaire_completed"
            )
        ) == 1


def test_admin_offer_client_preview_searches_by_email_then_reads_by_user_id_without_writes():
    client, factory = setup()
    search = client.get("/api/masterclass/admin/offer-preview/clients?q=member")
    assert search.status_code == 200
    selected = search.json()["clients"]
    assert len(selected) == 1
    assert selected[0]["email"] == "member@example.test"
    with factory() as db:
        user = db.get(User, uuid.UUID(selected[0]["user_id"]))
        db.add(MasterclassDayProgress(user_id=user.id, day_number=6))
        db.add(MasterclassEvent(
            user_id=user.id,
            event_key="course:day:6:offer-opened",
            event_type="recipes_part_1_offer_opened",
            placement="recipes-part-1-gate",
            details={"day": 6},
        ))
        now = datetime.now(timezone.utc)
        db.add(UserOffer(
            user_id=user.id,
            stage_code="early",
            started_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=71),
            snapshot={"created_by": "recipes-part-1-gate"},
        ))
        db.commit()
        before = db.scalar(select(func.count(UserOffer.id)))
    context = client.get(
        f"/api/masterclass/admin/offer-preview/clients/{selected[0]['user_id']}"
    )
    assert context.status_code == 200
    assert context.json()["state"] == "offer"
    assert context.json()["client"]["user_id"] == selected[0]["user_id"]
    assert context.json()["placement"] == "recipes-part-1-gate"
    assert context.json()["offer"]["stage"] == "early"
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == before


def test_admin_offer_client_preview_keeps_review_to_last_week_transition_readonly():
    client, factory = setup()
    search = client.get("/api/masterclass/admin/offer-preview/clients?q=member")
    user_id = uuid.UUID(search.json()["clients"][0]["user_id"])
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.get(User, user_id)
        db.add(MasterclassDayProgress(user_id=user.id, day_number=19))
        db.add(MasterclassEvent(
            user_id=user.id,
            event_key="course:day:19:offer-opened",
            event_type="closing_review_offer_opened",
            placement="day-19-offer",
            details={"day": 19},
        ))
        review = UserOffer(
            user_id=user.id,
            stage_code="review",
            started_at=now - timedelta(hours=73),
            expires_at=now - timedelta(hours=1),
            snapshot={"created_by": "day-19-offer"},
        )
        db.add(review)
        notification = MasterclassNotification(
            user_id=user.id,
            notification_kind="offer_last_chance",
            content_code="review",
            deduplication_key="test-review-last-chance",
            due_at=now - timedelta(hours=25),
            status="cancelled",
            payload={"stage": "review", "note": "keep"},
        )
        db.add(notification)
        db.commit()
        before_offers = db.scalar(select(func.count(UserOffer.id)))
        before_notifications = db.scalar(select(func.count(MasterclassNotification.id)))
        before_review = (review.started_at, review.expires_at, review.status, review.snapshot.copy())
        before_notification = (
            notification.due_at, notification.status, notification.payload.copy(),
            notification.content_code, notification.sent_at,
        )
    response = client.get(f"/api/masterclass/admin/offer-preview/clients/{user_id}")
    assert response.status_code == 200
    assert response.json()["state"] == "offer"
    assert response.json()["offer"]["stage"] == "last_week"
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == before_offers
        assert db.scalar(select(func.count(MasterclassNotification.id))) == before_notifications
        review_after = db.scalar(select(UserOffer).where(UserOffer.user_id == user_id, UserOffer.stage_code == "review"))
        notification_after = db.scalar(select(MasterclassNotification).where(
            MasterclassNotification.user_id == user_id,
            MasterclassNotification.deduplication_key == "test-review-last-chance",
        ))
        assert (
            aware(review_after.started_at), aware(review_after.expires_at),
            review_after.status, review_after.snapshot,
        ) == (
            aware(before_review[0]), aware(before_review[1]),
            before_review[2], before_review[3],
        )
        assert (
            aware(notification_after.due_at), notification_after.status, notification_after.payload,
            notification_after.content_code, notification_after.sent_at,
        ) == (
            aware(before_notification[0]), before_notification[1], before_notification[2],
            before_notification[3], before_notification[4],
        )


def test_onboarding_can_generate_only_one_active_short_lived_telegram_link():
    client, factory = setup()
    status = client.get(
        "/api/masterclass/messenger-links/status?email=member@example.test&platform=telegram"
    )
    assert status.status_code == 200
    assert status.json()["linked"] is False
    first = client.post("/api/masterclass/messenger-links", json={
        "email": "member@example.test",
        "platform": "telegram",
    })
    assert first.status_code == 200
    first_payload = first.json()["deep_link"].split("?start=", 1)[1]
    assert first.json()["deep_link"].startswith("https://t.me/EdabalansTestBot?start=M")
    assert len(first_payload) <= 32
    assert "=" not in first_payload

    second = client.post("/api/masterclass/messenger-links", json={
        "email": "member@example.test",
        "platform": "telegram",
    })
    assert second.status_code == 200
    second_payload = second.json()["deep_link"].split("?start=", 1)[1]
    assert second_payload != first_payload

    with factory() as db:
        rows = list(db.scalars(select(MessengerLinkToken).order_by(MessengerLinkToken.created_at)))
        assert len(rows) == 2
        assert rows[0].token_hash == hashlib.sha256(first_payload.encode("ascii")).hexdigest()
        assert rows[1].token_hash == hashlib.sha256(second_payload.encode("ascii")).hexdigest()
        assert first_payload not in {row.token_hash for row in rows}
        now = datetime.now(timezone.utc)
        first_expiry = rows[0].expires_at.replace(tzinfo=timezone.utc) if rows[0].expires_at.tzinfo is None else rows[0].expires_at
        second_expiry = rows[1].expires_at.replace(tzinfo=timezone.utc) if rows[1].expires_at.tzinfo is None else rows[1].expires_at
        assert first_expiry <= now
        assert second_expiry > now
        user_id = db.scalar(select(User.id))
        db.add(MessengerAccount(
            user_id=user_id,
            platform="telegram",
            platform_user_id="42",
            username="member",
            linked_at=now,
            source="test",
        ))
        db.commit()

    linked = client.get(
        "/api/masterclass/messenger-links/status?email=member@example.test&platform=telegram"
    )
    assert linked.status_code == 200
    assert linked.json()["linked"] is True
    assert "username" not in linked.json()


def test_dqs_material_queues_a_link_only_for_linked_telegram():
    client, factory = setup()
    with factory() as db:
        db.execute(text(
            "CREATE TABLE tg_contacts (user_id VARCHAR(36), status VARCHAR(32))"
        ))
        db.commit()
    missing = client.post(
        "/api/masterclass/dqs/link-to-telegram",
        json={"email": "member@example.test"},
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["reason"] == "telegram_not_linked"

    with factory() as db:
        user_id = db.scalar(select(User.id))
        db.add(MessengerAccount(
            user_id=user_id,
            platform="telegram",
            platform_user_id="42",
            username="member",
            linked_at=datetime.now(timezone.utc),
            source="test",
        ))
        db.execute(text(
            "INSERT INTO tg_contacts (user_id, status) VALUES (:user_id, 'active')"
        ), {"user_id": str(user_id)})
        db.commit()

    queued = client.post(
        "/api/masterclass/dqs/link-to-telegram",
        json={"email": "member@example.test"},
    )
    assert queued.status_code == 200
    assert queued.json() == {"ok": True, "status": "queued"}
    with factory() as db:
        notification = db.scalar(select(MasterclassNotification).where(
            MasterclassNotification.notification_kind == "dqs_app_link"
        ))
        assert notification is not None
        assert notification.content_code == "tpl_postpurchase_dqs_app_link"
        assert db.scalar(select(MasterclassEvent).where(
            MasterclassEvent.event_type == "dqs_app_link_requested"
        )) is not None


def test_offer_excludes_owned_product_and_checkout_rechecks_server_price():
    client, factory = setup()
    offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-1-gate")
    )
    assert offer.status_code == 200
    data = offer.json()
    assert data["stage"] == "early"
    assert data["expires_at"]
    assert data["offers"][0]["price"] == 2900
    checkout = client.post("/api/masterclass/checkout", json={
        "email": "member@example.test",
        "placement": "recipes-part-1-gate",
        "placement_token": placement_token("recipes-part-1-gate"),
        "offer_code": data["offers"][0]["code"],
    })
    assert checkout.status_code == 200
    assert checkout.json()["cart_command"].startswith("#order:")
    assert " · №" in checkout.json()["cart_command"]
    assert "EB-" not in checkout.json()["cart_command"]
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 1
        assert db.scalar(select(func.count(OfferCheckout.id))) == 1


def test_day_one_offer_shows_early_price_without_starting_countdown():
    client, factory = setup()
    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "early"
    assert response.json()["expires_at"] is None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 0

    triggered = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-1-gate")
    )
    reopened = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    assert triggered.json()["expires_at"] is not None
    assert reopened.json()["expires_at"] is None
    assert reopened.json()["offers"][0]["composition"] == "single"
    assert reopened.json()["offers"][0]["details"] == []
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 1

    for later_placement in ("recipes-part-2-gate", "day-19-offer"):
        later_client, _ = setup()
        later = later_client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(later_placement)
        )
        day_one = later_client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query("day-1-offer")
        )
        assert later.json()["expires_at"] is not None
        assert day_one.json()["expires_at"] is None


def test_single_offers_stay_concise_and_bundles_list_their_products():
    def assert_composition(payload):
        single_cards = [
            card for card in payload["offers"] if card["code"].startswith("single:")
        ]
        assert single_cards
        for card in single_cards:
            assert card["composition"] == "single"
            assert card["details"] == []

        for card in payload["offers"]:
            if card["code"].startswith("bundle:"):
                assert card["composition"] == "bundle"
                assert card["details"]

    client, _ = setup()
    standard = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert standard.status_code == 200
    assert_composition(standard.json())

    early = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    bundle = next(
        card for card in early.json()["offers"]
        if card["code"] == "bundle:digital"
    )
    assert bundle["composition"] == "bundle"
    assert bundle["details"]

    remaining_client, factory = setup()
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        for code in ("ACCESS_RECIPES", "ACCESS_CALORIES"):
            resource = db.scalar(select(Resource).where(Resource.code == code))
            if resource is None:
                resource = Resource(code=code, name=code, status="active")
                db.add(resource)
                db.flush()
            db.add(UserAccess(
                user_id=user.id,
                resource_id=resource.id,
                source="test",
                granted_at=datetime.now(timezone.utc),
            ))
        db.commit()
    remaining = remaining_client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert remaining.status_code == 200
    assert {card["code"] for card in remaining.json()["offers"]} == {
        "single:consultation"
    }
    assert_composition(remaining.json())
    owned_names = {
        product["name"] for product in remaining.json()["owned_products"]
    }
    assert "Мастер-класс по изменению питания и пищевых привычек" in owned_names
    assert "Система рецептов" in owned_names
    assert "Мини-курс «Калорийный»" in owned_names


def test_bundle_rows_use_the_same_catalog_fields_as_single_cards():
    client, _ = setup()
    early = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    ).json()
    digital_bundle = next(
        card for card in early["offers"] if card["code"] == "bundle:digital"
    )
    assert digital_bundle["title"] == OFFER_CARD_COPY["digital_bundle"]["title"]
    assert digital_bundle["details"] == [
        {
            "code": code,
            "name": early["product_presentations"][code]["name"],
            "description": early["product_presentations"][code]["description"],
        }
        for code in digital_bundle["items"]
    ]

    review = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    ).json()
    consultation_bundle = next(
        card for card in review["offers"]
        if card["code"] == "bundle:site-short-consultation"
    )
    assert consultation_bundle["details"] == [
        {
            "code": code,
            "name": review["product_presentations"][code]["name"],
            "description": review["product_presentations"][code]["description"],
        }
        for code in consultation_bundle["items"]
    ]

    single_cards = [
        *[card for card in early["offers"] if card["composition"] == "single"],
        *[card for card in review["offers"] if card["composition"] == "single"],
    ]
    assert single_cards
    for card in single_cards:
        code = card["items"][0]
        payload = early if card in early["offers"] else review
        presentation = payload["product_presentations"][code]
        assert card["title"] == presentation["name"]
        assert card["description"] == presentation["description"]
        assert card["long_description"] == OFFER_PRODUCTS[code]["long_description"]


def test_partial_bundle_keeps_the_temporary_full_program_name():
    client, _ = setup()
    response = client.post(
        "/api/masterclass/admin/offer-preview",
        json={
            "stage_code": "review",
            "placement": "day-19-offer",
            "owned_product_codes": ["recipes"],
            "tariff_name": "Минимальный",
            "remaining_hours": 48,
        },
    )
    assert response.status_code == 200
    card = next(
        item for item in response.json()["offers"]
        if item["code"] == "bundle:site-short-consultation"
    )
    assert card["title"] == OFFER_CARD_COPY["consultation_bundle"]["title"]


def test_offer_product_catalog_has_one_complete_card_contract():
    required_fields = {
        "name",
        "description",
        "long_description",
        "resource",
        "standard",
        "status",
        "features",
        "presentation_intro",
        "presentation_program",
    }
    assert OFFER_PRODUCTS
    assert all(set(product) == required_fields for product in OFFER_PRODUCTS.values())
    assert all(product["name"] for product in OFFER_PRODUCTS.values())
    assert all(product["description"] for product in OFFER_PRODUCTS.values())
    assert all(product["resource"] for product in OFFER_PRODUCTS.values())
    assert all(product["standard"] > 0 for product in OFFER_PRODUCTS.values())
    assert all(product["presentation_intro"] for product in OFFER_PRODUCTS.values())
    assert all(product["presentation_program"] for product in OFFER_PRODUCTS.values())
    assert all(
        all(item["title"] and item["description"] for item in product["presentation_program"])
        for product in OFFER_PRODUCTS.values()
    )


def test_offer_payload_links_product_presentations_to_current_checkout_cards():
    client, _ = setup()
    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-1-offer")
    )
    assert response.status_code == 200
    payload = response.json()
    recipes = payload["product_presentations"]["recipes"]
    assert recipes["name"]
    assert recipes["description"].startswith("Как")
    assert recipes["intro"]
    assert recipes["program"]
    assert all(set(item) == {"title", "description"} for item in recipes["program"])
    actions = payload["product_offer_actions"]["recipes"]
    assert {action["offer_code"] for action in actions} == {
        "single:recipes", "bundle:digital"
    }
    assert {action["composition"] for action in actions} == {"single", "bundle"}


def test_account_offer_entry_prioritises_selected_product_without_resetting_window():
    client, factory = setup()
    triggered = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-1-gate")
    )
    assert triggered.status_code == 200
    with factory() as db:
        offer_before = db.scalar(select(UserOffer))
        assert offer_before is not None
        started_before = offer_before.started_at
        expires_before = offer_before.expires_at

    response = client.get(
        "/api/masterclass/account-offers?email=member@example.test&"
        "focus_product_code=calories"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["focus_product_code"] == "calories"
    assert [card["code"] for card in payload["offers"]][:2] == [
        "single:calories", "bundle:digital"
    ]
    consultation = client.get(
        "/api/masterclass/account-offers?email=member@example.test&"
        "focus_product_code=consultation"
    )
    assert consultation.status_code == 200
    assert consultation.json()["offers"][0]["code"] == "single:consultation"
    assert consultation.json()["offers"][0]["price"] >= 7000
    with factory() as db:
        offer_after = db.scalar(select(UserOffer))
        assert offer_after.started_at == started_before
        assert offer_after.expires_at == expires_before

    checkout = client.post("/api/masterclass/account-offers/checkout", json={
        "email": "member@example.test",
        "focus_product_code": "calories",
        "offer_code": "single:calories",
    })
    assert checkout.status_code == 200
    assert checkout.json()["cart_command"].startswith("#order:")
    assert " · №" in checkout.json()["cart_command"]
    assert "EB-" not in checkout.json()["cart_command"]
    repeated_checkout = client.post("/api/masterclass/account-offers/checkout", json={
        "email": "member@example.test",
        "focus_product_code": "calories",
        "offer_code": "single:calories",
    })
    assert repeated_checkout.status_code == 200
    assert repeated_checkout.json()["cart_command"] == checkout.json()["cart_command"]
    with factory() as db:
        assert db.scalar(select(func.count(OfferCheckout.id))) == 1
    rejected = client.get(
        "/api/masterclass/account-offers?email=member@example.test&"
        "focus_product_code=training"
    )
    assert rejected.status_code == 409


def test_offer_simulator_is_generated_from_runtime_css_and_product_catalog():
    rendered = render_simulator()
    runtime_css = (
        Path(__file__).parents[1] / "app" / "static" / "masterclass.css"
    ).read_text(encoding="utf-8")
    runtime_js = (
        Path(__file__).parents[1] / "app" / "static" / "masterclass.js"
    ).read_text(encoding="utf-8")
    assert runtime_css in rendered
    assert runtime_js in rendered
    assert "class=\"mc-offer-card\"" in rendered
    assert "productPresentationMarkup" in rendered
    assert "headerMarkup:offerPageHeaderMarkup" in rendered
    assert "var back=ctx.accountOffer?" in rendered
    assert "account-offers/checkout" in rendered
    assert "${window.EdabalansMasterclassOfferView.headerMarkup()}${window.EdabalansMasterclassOfferView.markup(data)}" in rendered
    assert "data-product-info" in rendered
    assert "__COURSE_CSS__" not in rendered
    assert "__COURSE_JS__" not in rendered
    assert "__PRODUCTS_JSON__" not in rendered
    catalog_json = json.dumps(
        OFFER_PRODUCTS, ensure_ascii=False, separators=(",", ":")
    )
    assert rendered.count(catalog_json) == 1
    assert "/api/masterclass/admin/offer-preview" in rendered
    assert "EdabalansMasterclassOfferView.markup(data)" in rendered


def test_offer_simulator_lists_every_current_course_checkpoint_in_order():
    manifest = json.loads(
        (
            Path(__file__).parents[2]
            / "content"
            / "masterclass"
            / "course"
            / "course.json"
        ).read_text(encoding="utf-8")
    )
    checkpoints = [
        (day["number"], step["placement"], step["event"])
        for day in manifest["days"]
        for step in day["steps"]
        if step["kind"] == "offer"
    ]
    assert checkpoints == [
        (1, "day-1-offer", "day_1_offer_opened"),
        (6, "recipes-part-1-gate", "recipes_part_1_offer_opened"),
        (7, "recipes-part-1-gate", "recipes_part_1_offer_reopened"),
        (8, "recipes-part-1-gate", "recipes_part_1_last_day_opened"),
        (14, "recipes-part-2-gate", "recipes_part_2_offer_opened"),
        (15, "recipes-part-2-gate", "recipes_part_2_offer_reopened"),
        (16, "recipes-part-2-gate", "recipes_part_2_last_day_opened"),
        (19, "day-19-offer", "day_19_offer_opened"),
        (21, "day-21-offer", "day_21_offer_opened"),
    ]
    rendered = render_simulator()
    for _, placement, event in checkpoints:
        assert placement in rendered
    for event in {
        "day_1_offer_opened", "day_19_offer_opened", "day_21_offer_opened",
    }:
        assert event in rendered
    scenarios = course_offer_scenarios()
    assert list(scenarios) == [
        "day1", "day6", "day7", "day8", "day14", "day15", "day16",
        "day19", "day21Review", "day21LastWeek", "standard",
    ]
    for day_number, placement, event in checkpoints:
        matching = [
            item for item in scenarios.values()
            if item["placement"] == placement and item["event"] == event
        ]
        assert matching, f"day {day_number} is absent from simulator scenarios"
    assert 'const stages={"day1"' in rendered


def test_admin_offer_preview_uses_production_offer_builder() -> None:
    client, _ = setup()
    response = client.post(
        "/api/masterclass/admin/offer-preview",
        json={
            "stage_code": "early",
            "placement": "recipes-part-1-gate",
            "owned_product_codes": ["recipes"],
            "tariff_name": "С рецептами",
            "remaining_hours": 48,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "early"
    assert payload["owned_products"][0]["tariff"] == "С рецептами"
    assert payload["owned_products"][1]["code"] == "recipes"
    assert payload["offers"][0]["code"] == "single:calories"
    assert payload["offers"][1]["code"] == "bundle:site-short-consultation"
    assert payload["expires_at"] is not None


def test_site_short_offer_presentation_has_the_approved_six_stage_grid():
    expected = {
        "day-1-offer": (["single:recipes", "bundle:digital"], [2900, 3900]),
        "recipes-part-1-gate": (
            ["single:recipes", "bundle:digital", "bundle:site-short-consultation"],
            [2900, 3900, 10900],
        ),
        "recipes-part-2-gate": (
            ["single:recipes", "bundle:digital", "bundle:site-short-consultation"],
            [3300, 4900, 11900],
        ),
        "day-19-offer": (
            ["bundle:digital", "bundle:site-short-consultation", "single:consultation"],
            [5700, 12900, 7500],
        ),
        "day-21-offer": (
            ["single:recipes", "bundle:digital", "bundle:site-short-consultation"],
            [3800, 7000, 14900],
        ),
        "offers-hub": (
            ["single:recipes", "single:calories", "single:consultation"],
            [3900, 3900, 8900],
        ),
    }
    for placement, (codes, prices) in expected.items():
        client, factory = setup()
        if placement == "day-21-offer":
            now = datetime.now(timezone.utc)
            with factory() as db:
                user = db.scalar(select(User).where(User.display_name == "Участник"))
                db.add(UserOffer(
                    user_id=user.id,
                    stage_code="review",
                    started_at=now - timedelta(hours=80),
                    expires_at=now - timedelta(hours=8),
                    snapshot={},
                ))
                db.commit()
        response = client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(placement)
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["presentation"] == "site_short_v1"
        assert [card["code"] for card in payload["offers"]] == codes
        assert [card["price"] for card in payload["offers"]] == prices
        assert all(
            item not in {"training", "recordings"}
            for card in payload["offers"]
            for item in card["items"]
        )


def test_site_short_presentation_recalculates_the_third_tariff_for_recipes_owner():
    client, _ = setup()
    response = client.post(
        "/api/masterclass/admin/offer-preview",
        json={
            "stage_code": "review",
            "placement": "day-19-offer",
            "owned_product_codes": ["recipes"],
            "tariff_name": "С рецептами",
            "remaining_hours": 48,
        },
    )
    assert response.status_code == 200
    assert [(card["code"], card["price"], card["items"]) for card in response.json()["offers"]] == [
        ("single:calories", 3500, ["calories"]),
        ("bundle:site-short-consultation", 10700, ["calories", "consultation"]),
        ("single:consultation", 7500, ["consultation"]),
    ]


def test_site_short_recipes_tariff_has_the_approved_six_stage_grid():
    client, _ = setup()
    expected = [
        ("early", "day-1-offer", [2900]),
        ("early", "recipes-part-1-gate", [2900, 9900]),
        ("second", "recipes-part-2-gate", [3300, 10300]),
        ("review", "day-19-offer", [3500, 10700, 7500]),
        ("last_week", "day-21-offer", [3800, 11700]),
        ("standard", "offers-hub", [3900, 8900]),
    ]
    for stage, placement, prices in expected:
        response = client.post(
            "/api/masterclass/admin/offer-preview",
            json={
                "stage_code": stage,
                "placement": placement,
                "owned_product_codes": ["recipes"],
                "tariff_name": "С рецептами",
                "remaining_hours": 48 if stage != "standard" else None,
            },
        )
        assert response.status_code == 200
        assert [card["price"] for card in response.json()["offers"]] == prices


def test_site_short_combined_tariff_is_rechecked_and_saved_by_checkout():
    client, factory = setup()
    offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-1-gate")
    ).json()
    combined = next(
        card for card in offer["offers"]
        if card["code"] == "bundle:site-short-consultation"
    )
    checkout = client.post("/api/masterclass/checkout", json={
        "email": "member@example.test",
        "placement": "recipes-part-1-gate",
        "placement_token": placement_token("recipes-part-1-gate"),
        "offer_code": combined["code"],
    })
    assert checkout.status_code == 200
    with factory() as db:
        saved = db.scalar(select(OfferCheckout))
        assert saved.amount == 10900
        assert saved.items == ["recipes", "calories", "consultation"]


def test_offer_placement_cannot_be_forged_by_tilda_client():
    client, factory = setup()
    forged = client.get(
        "/api/masterclass/offers?email=member@example.test&placement=closing-review"
        "&placement_token=" + placement_token("day-2-offer")
    )
    assert forged.status_code == 403

    unknown = client.get(
        "/api/masterclass/offers?email=member@example.test&placement=made-up"
        "&placement_token=" + placement_token("made-up")
    )
    assert unknown.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 0


def test_checkout_rejects_token_from_another_offer_stage():
    client, factory = setup()
    response = client.post("/api/masterclass/checkout", json={
        "email": "member@example.test",
        "placement": "closing-review",
        "placement_token": placement_token("day-2-offer"),
        "offer_code": "single:recipes",
    })
    assert response.status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count(OfferCheckout.id))) == 0


def test_old_tilda_lecture_never_returns_an_earlier_discount_stage():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add_all([
            UserOffer(
                user_id=user.id,
                stage_code="early",
                started_at=now - timedelta(hours=12),
                expires_at=now + timedelta(hours=84),
                snapshot={},
            ),
            UserOffer(
                user_id=user.id,
                stage_code="review",
                started_at=now - timedelta(hours=1),
                expires_at=now + timedelta(hours=71),
                snapshot={},
            ),
        ])
        db.commit()

    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-2-offer")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "review"
    assert response.json()["expires_at"] is not None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "second")) == 0


def test_expired_price_advances_but_next_timer_waits_for_real_checkpoint():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(UserOffer(
            user_id=user.id,
            stage_code="early",
            started_at=now - timedelta(days=5),
            expires_at=now - timedelta(hours=1),
            snapshot={},
        ))
        db.commit()

    passive = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert passive.status_code == 200
    assert passive.json()["stage"] == "second"
    assert passive.json()["expires_at"] is None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "second")) == 0

    checkpoint = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-2-gate")
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["stage"] == "second"
    assert checkpoint.json()["expires_at"] is not None
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "second")) == 1


def test_recipe_windows_start_once_and_repeat_without_moving_due_time():
    client, factory = setup()
    for placement, stage_code in (
        ("recipes-part-1-gate", "early"),
        ("recipes-part-2-gate", "second"),
    ):
        first = client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(placement)
        )
        assert first.status_code == 200
        with factory() as db:
            window = db.scalar(
                select(UserOffer).where(UserOffer.stage_code == stage_code)
            )
            due = db.scalar(
                select(MasterclassNotification)
                .join(MasterclassEvent, MasterclassEvent.id == MasterclassNotification.event_id)
                .where(
                    MasterclassNotification.notification_kind == "sales_last_chance_due",
                    MasterclassEvent.event_key == f"offer:{stage_code}:started",
                )
            )
            original = (aware(window.started_at), aware(window.expires_at), aware(due.due_at))
            assert original[1] - original[0] == timedelta(hours=72)
            assert original[1] - original[2] == timedelta(hours=24)

        repeated = client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(placement)
        )
        assert repeated.status_code == 200
        with factory() as db:
            window = db.scalar(
                select(UserOffer).where(UserOffer.stage_code == stage_code)
            )
            due = db.scalar(
                select(MasterclassNotification)
                .join(MasterclassEvent, MasterclassEvent.id == MasterclassNotification.event_id)
                .where(
                    MasterclassNotification.notification_kind == "sales_last_chance_due",
                    MasterclassEvent.event_key == f"offer:{stage_code}:started",
                )
            )
            assert (aware(window.started_at), aware(window.expires_at), aware(due.due_at)) == original
            assert db.scalar(
                select(func.count(UserOffer.id)).where(UserOffer.stage_code == stage_code)
            ) == 1


def test_late_repeat_uses_the_original_course_checkpoint_time():
    client, factory = setup()
    opened_at = datetime.now(timezone.utc) - timedelta(hours=24)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(MasterclassEvent(
            user_id=user.id,
            event_key="course:day:6:step:2:completed",
            event_type="recipes_part_1_offer_opened",
            placement="recipes-part-1-gate",
            occurred_at=opened_at,
            details={"day": 6, "step_index": 2},
        ))
        db.commit()

    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-1-gate")
    )
    assert response.status_code == 200
    with factory() as db:
        window = db.scalar(select(UserOffer).where(UserOffer.stage_code == "early"))
        assert abs((aware(window.started_at) - opened_at).total_seconds()) < 1
        assert aware(window.expires_at) == aware(window.started_at) + timedelta(hours=72)


def test_admin_can_generate_signed_tokens_for_tilda_placements():
    client, _ = setup()
    response = client.get("/api/masterclass/admin/embed-tokens")
    assert response.status_code == 200
    placements = response.json()["placements"]
    assert set(placements) >= {
        "day-1-offer",
        "day-2-offer",
        "day-15-offer",
        "day-17-offer",
        "day-19-offer",
        "day-21-offer",
        "recipes-part-1-gate",
        "recipes-part-2-gate",
        "closing-review",
        "offers-hub",
    }
    assert all(len(token) > 20 for token in placements.values())


def test_admin_offer_stages_explain_the_runtime_window_rules():
    client, _ = setup()
    response = client.get("/api/masterclass/admin/offer-stages")
    assert response.status_code == 200
    rules = {row["code"]: row["runtime_rule"] for row in response.json()["stages"]}
    assert "День 6" in rules["early"] and "дни 7–8" in rules["early"]
    assert "День 14" in rules["second"] and "дни 15–16" in rules["second"]
    assert "review.expires_at" in rules["last_week"]
    assert "день 21" in rules["last_week"]

    rejected = client.put("/api/masterclass/admin/offer-stages/early", json={
        "duration_hours": 96,
        "single": 2900,
        "consultation": None,
        "bundle": {"1": 1900, "2": 3900, "3": 5900, "4": 7900},
    })
    assert rejected.status_code == 422

    updated = client.put("/api/masterclass/admin/offer-stages/early", json={
        "duration_hours": 72,
        "single": 2950,
        "consultation": None,
        "bundle": {"1": 1900, "2": 3950, "3": 5900, "4": 7900},
    })
    assert updated.status_code == 200
    stage = next(
        item for item in client.get("/api/masterclass/admin/offer-stages").json()["stages"]
        if item["code"] == "early"
    )
    assert stage["pricing"]["site_short"]["consultation_addon"] == 7000


def test_current_21_day_offer_placements_select_expected_stages():
    expected = {
        "day-1-offer": "early",
        "recipes-part-1-gate": "early",
        "recipes-part-2-gate": "second",
        "day-19-offer": "review",
        "day-21-offer": "standard",
    }
    for placement, stage in expected.items():
        client, _ = setup()
        response = client.get(
            "/api/masterclass/offers?email=member@example.test&"
            + placement_query(placement)
        )
        assert response.status_code == 200
        assert response.json()["stage"] == stage


def test_course_progress_is_server_side_and_steps_are_strictly_sequential():
    client, factory = setup()
    manifest = client.get(
        "/api/masterclass/course/manifest?email=member@example.test"
    )
    assert manifest.status_code == 200
    manifest_data = manifest.json()
    assert len(manifest_data["days"]) == 21
    assert manifest_data["title"] == (
        "Мастер-класс по изменению питания и пищевых привычек"
    )
    assert manifest_data["days"][0]["title"] == "Добро пожаловать!"
    durations = [
        step.get("durationMinutes") for step in manifest_data["days"][0]["steps"]
    ]
    assert all(isinstance(minutes, int) and minutes > 0 for minutes in durations)
    day_steps = manifest_data["days"][0]["steps"]
    offer_index = next(
        index for index, step in enumerate(day_steps) if step["id"] == "day-01-offer"
    )
    assert offer_index == len(day_steps) - 1

    account = client.get("/api/account?email=member@example.test")
    assert account.status_code == 200
    assert account.json()["courses"][0]["tariff"] == "Стандартный"
    assert account.json()["purchased_products"][0]["product_code"] == "MASTERCLASS_RECIPES"

    state = client.get("/api/masterclass/course?email=member@example.test")
    assert state.status_code == 200
    assert state.json()["masterclass_tariff"] == "Стандартный"
    day = state.json()["days"][0]
    assert day["opened"] is True
    assert day["steps_total"] == len(day_steps)
    assert day["completed_steps"] == []
    assert day["task_unlocked"] is False
    assert day["offer"] is None

    skipped = client.post(
        "/api/masterclass/course/days/1/steps/1/complete",
        json={"email": "member@example.test"},
    )
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["reason"] == "previous_step_not_completed"

    for index in range(offer_index):
        completed = client.post(
            f"/api/masterclass/course/days/1/steps/{index}/complete",
            json={"email": "member@example.test"},
        )
        assert completed.status_code == 200
    before_offer = completed.json()["days"][0]
    assert before_offer["next_step"] == offer_index
    assert before_offer["offer"]["placement"] == "day-1-offer"
    assert len(before_offer["offer"]["placement_token"]) > 20
    assert before_offer["task_unlocked"] is False
    task_before_offer = client.post(
        "/api/masterclass/course/days/1/task/open",
        json={"email": "member@example.test"},
    )
    assert task_before_offer.status_code == 409
    assert task_before_offer.json()["detail"]["reason"] == "materials_not_completed"

    offer = client.post(
        f"/api/masterclass/course/days/1/steps/{offer_index}/complete",
        json={"email": "member@example.test"},
    )
    assert offer.status_code == 200
    assert offer.json()["days"][0]["task_unlocked"] is True
    assert client.post(
        "/api/masterclass/course/days/1/task/open",
        json={"email": "member@example.test"},
    ).status_code == 200

    for index in range(4):
        checked = client.put(
            f"/api/masterclass/course/days/1/checks/{index}",
            json={"email": "member@example.test", "checked": True},
        )
        assert checked.status_code == 200
    assert checked.json()["days"][0]["completed"] is True

    unchecked = client.put(
        "/api/masterclass/course/days/1/checks/0",
        json={"email": "member@example.test", "checked": False},
    )
    assert unchecked.status_code == 200
    assert unchecked.json()["days"][0]["checkmarks"]["0"] is False
    assert unchecked.json()["days"][0]["completed"] is True

    with factory() as db:
        reminder = db.scalar(select(MasterclassNotification).where(
            MasterclassNotification.notification_kind == "course_day_unopened_18h"
        ))
        assert reminder is not None
        assert reminder.payload["day"] == 2
        assert reminder.payload["day_title"]

    too_early = client.post(
        "/api/masterclass/course/days/2/open",
        json={"email": "member@example.test"},
    )
    assert too_early.status_code == 409
    assert too_early.json()["detail"]["reason"] == "timer"

    with factory() as db:
        progress = db.scalar(
            select(MasterclassDayProgress).where(
                MasterclassDayProgress.day_number == 1
            )
        )
        progress.first_opened_at = datetime.now(timezone.utc) - timedelta(days=2)
        progress.completed_at = datetime.now(timezone.utc) - timedelta(days=2)
        db.commit()
    opened = client.post(
        "/api/masterclass/course/days/2/open",
        json={"email": "member@example.test"},
    )
    assert opened.status_code == 200
    assert opened.json()["days"][1]["opened"] is True

    repeated = client.post(
        "/api/masterclass/course/days/2/open",
        json={"email": "member@example.test"},
    )
    assert repeated.status_code == 200
    with factory() as db:
        stalled = list(db.scalars(
            select(MasterclassNotification).where(
                MasterclassNotification.notification_kind == "course_stalled_72h"
            )
        ))
        assert stalled
        assert all(row.content_code == "tpl_postpurchase_tempo_late" for row in stalled)
        pending_stall = next(row for row in stalled if row.status == "pending")
        due = pending_stall.due_at.replace(tzinfo=timezone.utc) if pending_stall.due_at.tzinfo is None else pending_stall.due_at
        assert timedelta(hours=71, minutes=59) < due - datetime.now(timezone.utc) <= timedelta(hours=72)
        assert db.scalar(
            select(func.count(MasterclassEvent.id)).where(
                MasterclassEvent.event_key == "course:day:2:opened"
            )
        ) == 1


def test_course_api_uses_tilda_email_but_still_requires_server_access():
    client, factory = setup()
    opened = client.get(
        "/api/masterclass/course?email=member@example.test",
        headers={},
    )
    assert opened.status_code == 200
    with factory() as db:
        without_access = User(display_name="Участник без покупки", status="active")
        db.add(without_access)
        db.flush()
        db.add(UserEmail(
            user_id=without_access.id,
            email_original="known-without-access@example.test",
            email_normalized="known-without-access@example.test",
            is_primary=True,
            source="test",
        ))
        db.add_all([
            UserLegalAcceptance(
                user_id=without_access.id,
                document_code=item["code"],
                document_version=item["version"],
                source="test",
            )
            for item in LEGAL_DOCUMENTS
        ])
        db.commit()
    denied = client.get(
        "/api/masterclass/course?email=known-without-access@example.test"
    )
    assert denied.status_code == 403


def test_admin_can_enable_isolated_accelerated_course_profile():
    client, _ = setup()
    enabled = client.put(
        "/api/masterclass/admin/test-profile",
        json={
            "email": "member@example.test",
            "enabled": True,
            "day_interval_seconds": 20,
            "notification_delay_seconds": 10,
        },
    )
    assert enabled.status_code == 200
    state = client.get("/api/masterclass/course?email=member@example.test")
    assert state.status_code == 200
    payload = state.json()
    opened = datetime.fromisoformat(payload["days"][0]["first_opened_at"])
    unlock = datetime.fromisoformat(payload["days"][0]["next_day_unlock_at"])
    assert payload["accelerated_test"] is True
    assert (unlock - opened).total_seconds() == 20


def test_closing_review_queues_three_review_week_messages_once():
    client, factory = setup()
    enabled = client.put(
        "/api/masterclass/admin/test-profile",
        json={
            "email": "member@example.test",
            "enabled": True,
            "day_interval_seconds": 20,
            "notification_delay_seconds": 10,
        },
    )
    assert enabled.status_code == 200
    first = client.get("/api/masterclass/questionnaires/closing-review?email=member@example.test")
    second = client.get("/api/masterclass/questionnaires/closing-review?email=member@example.test")
    assert first.status_code == second.status_code == 200
    with factory() as db:
        rows = list(db.scalars(
            select(MasterclassNotification)
            .where(MasterclassNotification.notification_kind.like("post_review_day_%"))
            .order_by(MasterclassNotification.due_at)
        ))
        assert [row.notification_kind for row in rows] == [
            "post_review_day_2", "post_review_day_4", "post_review_day_7"
        ]
        assert [row.content_code for row in rows] == [
            "tpl_postpurchase_review_week_1",
            "tpl_postpurchase_review_week_2",
            "tpl_postpurchase_review_week_3",
        ]
        assert [row.payload["day"] for row in rows] == [2, 4, 7]


def test_course_content_uses_the_same_member_session():
    client, _ = setup()
    imported = client.get(
        "/api/masterclass/course/content/extracted-2026-08-23.json"
        "?email=member@example.test"
    )
    assert imported.status_code == 200
    assert imported.json()["pages"]
    response = client.get(
        "/api/masterclass/course/content/31-satiety-habits.txt"
        "?email=member@example.test"
    )
    assert response.status_code == 200
    assert response.text.strip()
    assert response.headers["cache-control"] == "private, no-cache"
    assert client.get(
        "/api/masterclass/course/content/not-allowed.txt?email=member@example.test"
    ).status_code == 404


def test_recipe_gate_uses_access_and_records_open_once():
    client, factory = setup()
    denied = client.get(
        "/api/masterclass/gate/1?email=member@example.test&placement_token="
        + placement_token("recipes-part-1-gate")
    ).json()
    assert denied["allowed"] is False
    assert denied["state"] == "offer"
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        recipes = db.scalar(select(Resource).where(Resource.code == "ACCESS_RECIPES"))
        db.add(UserAccess(user_id=user.id, resource_id=recipes.id, source="test", granted_at=datetime.now(timezone.utc)))
        db.commit()
    allowed = client.get(
        "/api/masterclass/gate/1?email=member@example.test&placement_token="
        + placement_token("recipes-part-1-gate")
    ).json()
    assert allowed["allowed"] is True
    assert allowed["state"] == "content"
    assert allowed["title"] == "Рецепты · часть 1"
    with factory() as db:
        assert db.scalar(select(func.count(MasterclassEvent.id)).where(
            MasterclassEvent.event_type == "recipes_part_1_opened"
        )) == 1
        assert db.scalar(select(func.count(MasterclassNotification.id)).where(
            MasterclassNotification.notification_kind == "recipes_followup"
        )) == 0
        assert db.scalar(select(func.count(MasterclassNotification.id)).where(
            MasterclassNotification.notification_kind == "sales_last_chance_due"
        )) == 1
    queue = client.get("/api/masterclass/admin/notifications")
    assert queue.status_code == 200
    assert queue.json()["notifications"][0]["kind"] == "sales_last_chance_due"


def test_admin_preview_lists_only_masterclass_users_with_primary_email():
    client, _ = setup()
    response = client.get("/api/masterclass/admin/users")
    assert response.status_code == 200
    assert response.json()["users"] == [{
        "id": response.json()["users"][0]["id"],
        "display_name": "Участник",
        "email": "member@example.test",
    }]


def test_site_short_consultation_is_separate_only_on_day_19_or_standard_prices():
    client, factory = setup()
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        now = datetime.now(timezone.utc)
        db.add(UserOffer(user_id=user.id, stage_code="second", started_at=now - timedelta(days=4), expires_at=now - timedelta(hours=1), snapshot={}))
        db.commit()

    recipe_offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("recipes-part-2-gate")
    ).json()
    assert recipe_offer["stage"] == "standard"
    assert all(card["code"] != "single:consultation" for card in recipe_offer["offers"])

    review_offer = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    ).json()
    assert review_offer["stage"] == "review"
    assert any(card["code"] == "single:consultation" for card in review_offer["offers"])
    assert review_offer["offers"][1]["code"] == "bundle:site-short-consultation"
    assert "consultation" in review_offer["offers"][1]["items"]


def test_review_expiry_automatically_starts_final_week_before_day_21():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        review = UserOffer(
            user_id=user.id,
            stage_code="review",
            started_at=now - timedelta(hours=80),
            expires_at=now - timedelta(hours=8),
            snapshot={},
        )
        db.add(review)
        db.commit()
    passive = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert passive.status_code == 200
    assert passive.json()["stage"] == "last_week"
    assert passive.json()["expires_at"] is not None
    assert [card["code"] for card in passive.json()["offers"]] == [
        "single:recipes",
        "bundle:digital",
        "bundle:site-short-consultation",
    ]
    with factory() as db:
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert final is not None
        final_started = aware(final.started_at)
        final_expires = aware(final.expires_at)
        assert final_started == aware(review.expires_at)
        assert final_expires - final_started == timedelta(hours=168)
        original_times = (final_started, final_expires)

    checkpoint = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-21-offer")
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["stage"] == "last_week"
    assert checkpoint.json()["expires_at"] is not None
    with factory() as db:
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert (aware(final.started_at), aware(final.expires_at)) == original_times
        due = db.scalar(select(MasterclassNotification).where(
            MasterclassNotification.notification_kind == "sales_last_chance_due"
        ))
        assert due is not None
        assert due.payload["stage"] == "last_week"


def test_site_short_day_21_shows_standard_consultation_after_final_week():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(UserOffer(
            user_id=user.id,
            stage_code="review",
            started_at=now - timedelta(days=12),
            expires_at=now - timedelta(days=12) + timedelta(hours=72),
            snapshot={},
        ))
        db.add(UserOffer(
            user_id=user.id,
            stage_code="last_week",
            started_at=now - timedelta(days=9),
            expires_at=now - timedelta(hours=1),
            snapshot={},
        ))
        db.commit()
    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-21-offer")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "standard"
    assert [card["code"] for card in response.json()["offers"]] == [
        "single:recipes", "single:calories", "single:consultation"
    ]

def test_day_19_fixes_review_and_last_week_timeline_once():
    client, factory = setup()
    first = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    )
    repeated = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    )
    assert first.status_code == repeated.status_code == 200
    with factory() as db:
        review = db.scalar(select(UserOffer).where(UserOffer.stage_code == "review"))
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert aware(review.expires_at) - aware(review.started_at) == timedelta(hours=72)
        assert aware(final.started_at) == aware(review.expires_at)
        assert aware(final.expires_at) - aware(final.started_at) == timedelta(days=7)
        assert db.scalar(select(func.count(UserOffer.id))) == 2
        assert db.scalar(
            select(func.count(MasterclassNotification.id)).where(
                MasterclassNotification.notification_kind == "sales_last_chance_due"
            )
        ) == 2


def test_day_21_during_review_only_shows_its_existing_remainder():
    client, factory = setup()
    started = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-19-offer")
    )
    assert started.status_code == 200
    with factory() as db:
        review = db.scalar(select(UserOffer).where(UserOffer.stage_code == "review"))
        original = (aware(review.started_at), aware(review.expires_at))

    day_21 = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("day-21-offer")
    )
    assert day_21.status_code == 200
    assert day_21.json()["stage"] == "review"
    assert datetime.fromisoformat(day_21.json()["expires_at"]) == original[1]
    with factory() as db:
        review = db.scalar(select(UserOffer).where(UserOffer.stage_code == "review"))
        final = db.scalar(select(UserOffer).where(UserOffer.stage_code == "last_week"))
        assert (aware(review.started_at), aware(review.expires_at)) == original
        assert aware(final.started_at) == original[1]
        assert db.scalar(select(func.count(UserOffer.id))) == 2


def test_offers_hub_does_not_resurrect_final_discount_after_week_has_elapsed():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add_all([
            UserOffer(
                user_id=user.id,
                stage_code="review",
                started_at=now - timedelta(days=12),
                expires_at=now - timedelta(days=9),
                snapshot={},
            ),
            UserOffer(
                user_id=user.id,
                stage_code="last_week",
                started_at=now - timedelta(days=9),
                expires_at=now - timedelta(days=2),
                snapshot={},
            ),
        ])
        db.commit()

    response = client.get(
        "/api/masterclass/offers?email=member@example.test&"
        + placement_query("offers-hub")
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "standard"
    assert response.json()["expires_at"] is None
    assert len(response.json()["offers"]) == 3
    assert all(card["code"].startswith("single:") for card in response.json()["offers"])
    assert all(card["price"] == card["standard_price"] for card in response.json()["offers"])
    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code == "last_week")) == 1


def test_admin_lists_personal_offer_window_with_effective_expired_status():
    client, factory = setup()
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = db.scalar(select(User).where(User.display_name == "Участник"))
        db.add(UserOffer(
            user_id=user.id,
            stage_code="early",
            started_at=now - timedelta(days=5),
            expires_at=now - timedelta(days=1),
            status="active",
            snapshot={},
        ))
        db.commit()

    response = client.get("/api/masterclass/admin/user-offers")
    assert response.status_code == 200
    assert response.json()["offers"][0]["email"] == "member@example.test"
    assert response.json()["offers"][0]["stage_code"] == "early"
    assert response.json()["offers"][0]["status"] == "expired"


def test_crm_card_contains_masterclass_answers_events_and_offer_windows():
    client, factory = setup()
    payload = {
        "email": "member@example.test",
        "question_code": "main_request",
        "answer_text": "Хочу выстроить питание",
    }
    assert client.put("/api/masterclass/questionnaires/onboarding/answer", json=payload).status_code == 200
    assert client.get(
        "/api/masterclass/gate/1?email=member@example.test&placement_token="
        + placement_token("recipes-part-1-gate")
    ).status_code == 200
    with factory() as db:
        user_id = db.scalar(select(User.id).where(User.display_name == "Участник"))

    response = client.get(f"/admin/api/users/{user_id}")
    assert response.status_code == 200
    data = response.json()["masterclass"]
    assert data["questionnaires"][0]["answers"][0]["title"] == "Главный запрос, с которым вы пришли"
    assert data["questionnaires"][0]["answers"][0]["answer"] == "Хочу выстроить питание"
    assert "recipes_part_1_opened" in {event["type"] for event in data["events"]}
    assert data["offers"][0]["stage"] == "early"
