from __future__ import annotations

import json
import os
import pytest
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import MasterclassStepProgress, User
from app.masterclass_routes import manifest_for_resources
from scripts.bootstrap_masterclass_editorial import parse_program
from scripts.publish_masterclass_editorial import (
    apply_day_copy,
    compile_manifest,
    dqs_application_definition,
    editorial_body,
    migrate_step_progress,
    special_prelude,
    questionnaire_definition,
)


ROOT = Path(__file__).resolve().parents[2]


def test_editorial_program_compiles_to_runtime_titles_and_visible_steps() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )

    compiled, _ = compile_manifest(manifest, next_version=12)

    assert len(compiled["days"]) == 20
    assert compiled["days"][5]["title"] == "Опорные точки в питании"
    assert compiled["days"][5]["tocSummary"] == ""
    assert [
        step["id"]
        for step in compiled["days"][6]["steps"]
        if not step.get("hidden", False) and not step.get("nested", False)
    ] == [
        "day-06-article-03",
        "day-07-video-01",
        "day-07-recipes-part-1",
    ]
    assert [
        step["id"]
        for step in compiled["days"][7]["steps"]
        if not step.get("hidden", False)
    ] == ["day-07-store-food"]
    assert next(
        step
        for step in compiled["days"][5]["steps"]
        if step["id"] == "day-06-article-04"
    )["hidden"] is True
    cycles = next(
        step
        for step in compiled["days"][16]["steps"]
        if step["id"] == "day-17-article-04"
    )
    assert cycles["hidden"] is True
    guide = next(
        step
        for step in compiled["days"][7]["steps"]
        if step["id"] == "day-07-store-food"
    )
    assert guide["locked"] is True
    assert guide["badge"] == "Скоро"
    assert guide["contentKind"] == "placeholder"
    assert compiled["days"][2]["video"] == 29
    assert compiled["days"][3]["video"] == 18.3
    assert compiled["days"][6]["accessResource"] == "ACCESS_RECIPES"
    assert compiled["days"][7]["accessResource"] == "ACCESS_RECIPES"
    assert compiled["days"][14]["accessResource"] == "ACCESS_RECIPES"
    nested = [step for step in compiled["days"][6]["steps"] if step.get("nested")]
    assert [step["id"] for step in nested] == [
        "day-07-recipe-author-oatmeal",
        "day-07-recipe-red-lentils",
        "day-07-recipe-broccoli",
        "day-07-recipe-marinara",
        "day-07-recipe-white-sauce",
        "day-07-recipe-lazy-khachapuri",
        "day-07-recipe-caesar",
        "day-07-recipe-tuna-family",
    ]
    assert all(step["parentStepId"] == "day-07-recipes-part-1" for step in nested)
    assert all(step["required"] is False and step["hidden"] is False for step in nested)
    zero_time_steps = {
        "day-01-messenger-link",
        "day-01-questionnaire",
        "day-01-offer",
        "day-02-current-diet",
        "day-04-dqs",
    }
    assert {
        step["id"]
        for day in compiled["days"][:4]
        for step in day["steps"]
        if step["id"] in zero_time_steps and step["durationMinutes"] == 0
    } == zero_time_steps


def test_recipe_days_hide_articles_behind_one_access_gate() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    compiled, _ = compile_manifest(manifest, next_version=12)
    for day_number in (7, 8, 15):
        compiled["days"][day_number - 1]["accessGateTitle"] = (
            "Приобрести доступ к «Системе рецептов»"
        )

    locked = manifest_for_resources(compiled, {"ACCESS_MASTERCLASS"})
    for day_number in (7, 8, 15):
        day = locked["days"][day_number - 1]
        visible = [step for step in day["steps"] if not step.get("hidden")]
        assert day["accessDenied"] is True
        assert len(visible) == 1
        assert visible[0]["accessGate"] is True
        assert visible[0]["kind"] == "offer"
        expected_part = 2 if day_number == 15 else 1
        assert visible[0]["placement"] == f"recipes-part-{expected_part}-gate"
        assert "contentAsset" not in visible[0]

    allowed = manifest_for_resources(
        compiled, {"ACCESS_MASTERCLASS", "ACCESS_RECIPES"}
    )
    assert allowed["days"][6]["accessDenied"] is False
    assert [
        step["id"]
        for step in allowed["days"][6]["steps"]
        if not step.get("hidden") and not step.get("nested")
    ] == ["day-06-article-03", "day-07-video-01", "day-07-recipes-part-1"]
    assert len(
        [
            step
            for step in allowed["days"][6]["steps"]
            if step.get("nested") and not step.get("hidden")
        ]
    ) == 8


def test_plain_messenger_step_is_safe_for_editorial_bootstrap(tmp_path, monkeypatch) -> None:
    from scripts import bootstrap_masterclass_editorial as bootstrap

    days, materials = bootstrap.parse_program()
    messenger = materials["day-01-messenger-link"]
    assert messenger["path"] is None
    assert messenger["duration"] == 0

    bootstrap.write_material(messenger, force=True)
    monkeypatch.setattr(bootstrap, "EDITORIAL", tmp_path)
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    bootstrap.write_day(days[0], manifest["days"][0], force=True)
    rendered = next((tmp_path / "days").glob("01-*.md")).read_text(encoding="utf-8")
    assert "3. Подключить мессенджер · ≈ 0 мин" in rendered


def test_editorial_validator_accepts_plain_messenger_step(capsys) -> None:
    from scripts import validate_masterclass_editorial as validator

    validator.main()

    assert "OK: 20 дней" in capsys.readouterr().out


def test_editorial_validator_rejects_other_pathless_materials(monkeypatch) -> None:
    from scripts import validate_masterclass_editorial as validator

    days, materials = parse_program()
    invalid = dict(materials)
    invalid["broken"] = {
        "step_id": "broken",
        "type": "article",
        "path": None,
    }
    monkeypatch.setattr(validator, "parse_program", lambda: (days, invalid))

    with pytest.raises(SystemExit, match="без Markdown допустим только для messenger"):
        validator.main()


def test_editorial_program_does_not_restore_excluded_cycle_placeholder() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["days"][16]["steps"] = [
        step
        for step in manifest["days"][16]["steps"]
        if step["id"] != "day-17-article-04"
    ]

    compiled, _ = compile_manifest(manifest, next_version=12)

    assert all(
        step["id"] != "day-17-article-04"
        for step in compiled["days"][16]["steps"]
    )


def test_program_order_replaces_stale_runtime_order() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["days"][9]["steps"][0], manifest["days"][9]["steps"][1] = (
        manifest["days"][9]["steps"][1],
        manifest["days"][9]["steps"][0],
    )

    compiled, _ = compile_manifest(manifest, next_version=12)

    assert [step["id"] for step in compiled["days"][9]["steps"][:3]] == [
        "day-10-article-01",
        "day-10-article-02",
        "day-10-article-03",
    ]


def test_day_markdown_supplies_runtime_day_copy_and_checks() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    days, _ = parse_program()
    compiled, _ = compile_manifest(manifest, next_version=12)

    apply_day_copy(compiled, days)

    day = compiled["days"][5]
    assert day["lead"] == ""
    assert day["intro"].startswith("<p>")
    assert day["intro"].count("<p>") >= 2
    assert day["afterText"] == ""
    assert len([item for item in day["checks"] if not item.get("hidden")]) == 2
    assert "<p>" in day["intro"]

    first = compiled["days"][0]
    assert first["intro"].startswith("<p>")
    assert first["afterText"] == ""


def test_first_five_release_preserves_later_days_without_removed_practice() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["days"][5]["intro"] = "Редакция другого потока"
    compiled, _ = compile_manifest(manifest, next_version=12, through_day=5)
    days, _ = parse_program()
    apply_day_copy(compiled, days, through_day=5)
    assert compiled["days"][5:] == manifest["days"][5:]
    assert all(
        step["id"] != "day-03-practice"
        for step in compiled["days"][2]["steps"]
    )


def test_single_day_release_preserves_every_other_day() -> None:
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    original = json.loads(json.dumps(manifest))
    compiled, _ = compile_manifest(
        manifest,
        next_version=12,
        from_day=4,
        through_day=4,
    )
    days, _ = parse_program()
    apply_day_copy(compiled, days, from_day=4, through_day=4)

    assert compiled["days"][:3] == original["days"][:3]
    assert compiled["days"][4:] == original["days"][4:]
    assert compiled["days"][3] != original["days"][3]


def test_partial_publish_writes_only_selected_day_articles(monkeypatch) -> None:
    from scripts import publish_masterclass_editorial as publisher
    manifest = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    writes = []
    published_payloads = []
    class Database:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def commit(self):
            pass
    monkeypatch.setattr(publisher, "SessionLocal", Database)
    monkeypatch.setattr(publisher, "active_course_version", lambda db:
                        SimpleNamespace(payload=manifest, version_no=11))
    monkeypatch.setattr(
        publisher,
        "publish_document",
        lambda *a, **kw: (
            published_payloads.append(kw["payload"])
            or SimpleNamespace(version_no=12)
        ),
    )
    monkeypatch.setattr(publisher, "migrate_step_progress", lambda *a: 0)
    monkeypatch.setattr(publisher, "get_material", lambda *a: {"version": 0})
    monkeypatch.setattr(publisher, "publish_material", lambda *a, **kw:
                        writes.append(kw["step_id"]))
    monkeypatch.setattr(
        "sys.argv",
        ["publisher", "--from-day", "4", "--through-day", "4", "--publish"],
    )
    publisher.main()
    _, materials = parse_program()
    expected = {item["step_id"] for item in materials.values()
                if item["day"] == 4 and item["type"] == "article"}
    assert set(writes) == expected
    assert len(writes) == len(expected)
    dqs_step = published_payloads[0]["days"][3]["steps"][1]
    assert dqs_step["applicationButtons"] == {
        "print": "Скачать печатный вариант",
        "open": "Открыть приложение",
    }
    assert "Ссылка продублируется вам в привязанный мессенджер" in (
        dqs_step["applicationNoteHtml"]
    )


def test_special_material_prelude_uses_markdown_before_embed_only() -> None:
    path = (
        ROOT / "content" / "masterclass" / "editorial" / "materials"
        / "06-04-что-такое-система-рецептов.md"
    )

    html = special_prelude(path, "offer")

    assert "Можно знать правило тарелки" in html
    assert "EMBED" not in html

    empty = (
        ROOT / "content" / "masterclass" / "editorial" / "materials"
        / "01-05-что-еще-вам-может-понадобиться.md"
    )
    assert "мини-курсы и дополнительные программы" in special_prelude(empty, "offer")


def test_dqs_markdown_defines_two_actions_and_messenger_note() -> None:
    path = (
        ROOT
        / "content/masterclass/editorial/materials/04-02-приложение-dqs.md"
    )

    definition = dqs_application_definition(path)

    assert definition["buttons"] == {
        "print": "Скачать печатный вариант",
        "open": "Открыть приложение",
    }
    assert "Ссылка продублируется вам в привязанный мессенджер" in definition["noteHtml"]


def test_step_progress_follows_stable_id_when_program_reorders_steps() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    current = json.loads(
        (ROOT / "content" / "masterclass" / "course" / "course.json").read_text(
            encoding="utf-8"
        )
    )
    current["days"][9]["steps"][0], current["days"][9]["steps"][1] = (
        current["days"][9]["steps"][1],
        current["days"][9]["steps"][0],
    )
    compiled, _ = compile_manifest(current, next_version=12)
    with Session(engine) as db:
        user = User(display_name="Тест", status="active")
        db.add(user)
        db.flush()
        first = MasterclassStepProgress(
            user_id=user.id, day_number=10, step_index=0,
            step_kind="article",
        )
        second = MasterclassStepProgress(
            user_id=user.id, day_number=10, step_index=1,
            step_kind="article",
        )
        db.add_all([first, second])
        db.flush()
        first_id, second_id = first.id, second.id

        assert migrate_step_progress(db, current, compiled) == 2
        rows = list(db.scalars(
            select(MasterclassStepProgress).order_by(MasterclassStepProgress.step_index)
        ))
        assert [row.step_index for row in rows] == [0, 1]
        assert rows[0].id == second_id
        assert rows[1].id == first_id


def test_editorial_body_rewrites_local_article_images_to_public_media_route() -> None:
    path = (
        ROOT
        / "content"
        / "masterclass"
        / "editorial"
        / "materials"
        / "07-02-еда-из-магазина-и-доставок.md"
    )

    body = editorial_body(path)

    assert "](assets/" not in body
    assert "](/course-assets/masterclass/media/55-store-food-without-cooking/" in body
    assert not body.startswith("# ")
    assert "> Тип:" not in body


def test_editorial_body_rewrites_obsidian_visible_article_images_to_public_media_route() -> None:
    path = (
        ROOT
        / "content"
        / "masterclass"
        / "editorial"
        / "materials"
        / "01-02-как-вести-дневник-питания.md"
    )

    body = editorial_body(path)

    assert "](../assets/" not in body
    assert (
        "](/course-assets/masterclass/media/01-food-diary/"
        "telegram-channel-collage-2026-09-20.png)"
    ) in body
    assert (
        "](/course-assets/masterclass/media/01-food-diary/"
        "max-channel-collage-2026-09-20.png)"
    ) in body


def test_tutorial_body_omits_working_status_metadata() -> None:
    body = editorial_body(
        ROOT / "content/masterclass/editorial/materials/01-01-как-устроен-мастер-класс.md"
    )
    assert "draft_for_editing" not in body
    assert "О чём этот Мастер-класс" in body


def test_questionnaire_markdown_defines_existing_questions_and_button() -> None:
    path = ROOT / "content/masterclass/editorial/materials/02-03-какая-у-вас-сейчас-диета.md"
    definition = questionnaire_definition(path)
    assert len(definition["questions"]) == 16
    assert definition["questions"][0]["code"] == "whole_grains"
    assert definition["questions"][0]["prompt"] == ""
    assert definition["button"]
    assert definition["voiceButton"] == "Я оставлю в дневнике голосовое"
    assert "question_codes" not in special_prelude(path, "questionnaire")
    assert "Кнопка отправки:" not in special_prelude(path, "questionnaire")
    assert "Кнопка голосового:" not in special_prelude(path, "questionnaire")


def test_questionnaire_markdown_preserves_help_format_and_rejects_ambiguous_codes(tmp_path) -> None:
    path = tmp_path / "form.md"
    text = "<!-- question_codes: a, b -->\n## Вопросы\n1. Первый\n\n**Подсказка**\n\n2. Второй\n\n> [!NOTE]\n> Помощь\n\n## После анкеты\n\nКнопка отправки: Отправить\nКнопка голосового: Оставлю голосовое\n"
    path.write_text(text, encoding="utf-8")
    definition = questionnaire_definition(path)
    assert "<strong>Подсказка</strong>" in definition["questions"][0]["promptHtml"]
    assert "article-note-accent" in definition["questions"][1]["promptHtml"]
    assert definition["voiceButton"] == "Оставлю голосовое"
    path.write_text(text.replace("a, b", "a, a"), encoding="utf-8")
    with pytest.raises(ValueError, match="неоднозначны"):
        questionnaire_definition(path)


def test_practice_day_has_guide_and_recipe_selection_is_article() -> None:
    current = json.loads((ROOT / "content/masterclass/course/course.json").read_text(encoding="utf-8"))
    compiled, _ = compile_manifest(current, next_version=12)
    assert [
        step["id"]
        for step in compiled["days"][7]["steps"]
        if not step.get("hidden")
    ] == ["day-07-store-food"]
    selection = next(step for step in compiled["days"][6]["steps"] if step["id"] == "day-07-recipes-part-1")
    assert selection["kind"] == "article"
    assert selection["contentKind"] == "text"


def test_cross_day_move_stops_instead_of_corrupting_positional_progress() -> None:
    current = json.loads((ROOT / "content/masterclass/course/course.json").read_text(encoding="utf-8"))
    moved = next(step for step in current["days"][0]["steps"] if step["id"] == "day-01-article-02")
    current["days"][0]["steps"].remove(moved)
    current["days"][1]["steps"].append(moved)
    with pytest.raises(ValueError, match="Перенос материала между днями"):
        compile_manifest(current, next_version=12)


def test_recipe_access_gate_opens_offer_without_repeating_day_six_copy() -> None:
    folder = ROOT / "content/masterclass/editorial/materials"
    assert special_prelude(
        folder / "07-00-приобрести-систему-рецептов.md",
        "offer",
    ) == ""


def test_title_changes_only_in_program_reach_runtime_without_editing_body_h1(monkeypatch) -> None:
    from scripts import publish_masterclass_editorial as publisher
    days, items = parse_program()
    item = items["day-01-article-02"]
    unchanged_body = item["path"].read_text(encoding="utf-8")
    item["title"] = "Новое название дневника"
    days[0]["title"] = "Новое название дня"
    monkeypatch.setattr(publisher, "parse_program", lambda: (days, items))
    current = json.loads((ROOT / "content/masterclass/course/course.json").read_text(encoding="utf-8"))
    compiled, _ = publisher.compile_manifest(current, next_version=12)
    step = next(step for step in compiled["days"][0]["steps"] if step["id"] == item["step_id"])
    assert compiled["days"][0]["title"] == "Новое название дня"
    assert step["title"] == item["title"]
    assert item["path"].read_text(encoding="utf-8") == unchanged_body


def test_published_questions_keep_saved_answers_bound_to_codes_in_api_and_crm(monkeypatch) -> None:
    from app import masterclass_routes as routes
    from app.course_structure_service import active_course_version
    from app.models import QuestionnaireRun, QuestionnaireAnswer
    from app.config import Settings
    from app.crm_service import user_detail
    from copy import deepcopy
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(display_name="Редакционная проверка", status="active")
        db.add(user)
        db.commit()
        current = active_course_version(db)
        manifest = deepcopy(current.payload)
        step = next(step for day in manifest["days"] for step in day["steps"] if step["id"] == "day-01-questionnaire")
        step["title"] = "Название формы из программы"
        step["editorialHtml"] = "<p>Подводка из MD</p>"
        step["questionnaireDefinition"] = {"questions": [
            {"code": "main_request", "title": "Переименованный запрос", "prompt": "Новая подсказка", "promptHtml": "<p>Новая подсказка</p>"},
            {"code": "parameters", "title": "Переименованные параметры", "prompt": "", "promptHtml": ""},
        ], "button": "Новая кнопка", "noteHtml": "<p>После формы</p>"}
        current.payload = manifest
        run = QuestionnaireRun(user_id=user.id, kind="onboarding")
        db.add(run)
        db.flush()
        db.add(QuestionnaireAnswer(run_id=run.id, question_code="parameters", answer_text="Старые параметры"))
        db.commit()
        monkeypatch.setattr(routes, "resolve_masterclass_user", lambda *args: user)
        result = routes.questionnaire("onboarding", "test@example.test", None, db, Settings())
        assert [row["code"] for row in result["questions"]] == ["main_request", "parameters"]
        assert result["questions"][1]["answer"] == "Старые параметры"
        assert result["questions"][1]["title"] == "Переименованные параметры"
        assert result["copy"]["button"] == "Новая кнопка"
        assert result["copy"]["title"] == step["title"]
        detail = user_detail(db, user.id)
        assert detail is not None
        assert any(answer["title"] == "Переименованные параметры" for item in detail["masterclass"]["questionnaires"] for answer in item["answers"])
