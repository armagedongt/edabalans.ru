from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1]
import sys
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import author_workflow
import prepare_author_post
import record_author_correction
import report_author_corpus_health
import install_edabalans_writer_skill
import validate_author_draft


def empty_voice_index(path: Path) -> None:
    with sqlite3.connect(path) as db:
        for table, key in (
            ("rules", "rule_id"), ("exemplars", "exemplar_id"),
            ("fragments", "fragment_id"), ("rhetoric", "entry_id"),
            ("corrections", "correction_id"), ("corpus", "corpus_id"),
        ):
            db.execute(f"CREATE TABLE {table} ({key} TEXT PRIMARY KEY, payload_json TEXT)")
        db.execute("CREATE VIRTUAL TABLE voice_fts USING fts5(kind UNINDEXED, item_id UNINDEXED, catalog_id UNINDEXED, headline, text, tags)")


class AuthorWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.folder.name)
        self.index = self.root / "voice.sqlite"
        empty_voice_index(self.index)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def pack(self, payload: dict) -> tuple[Path, dict]:
        payload = dict(payload)
        payload.setdefault(
            "source_basis",
            "sparse_basis" if payload.get("work_profile") == "new_material" else "full_source",
        )
        if payload.get("work_profile") == "transcript_to_article":
            payload.setdefault("transcript_role", "article_source")
        if payload.get("surface_context") in {
            "course_material", "masterclass_material", "intensive_article"
        }:
            payload.setdefault("course_context", {
                "day_context": "Учебный день: прочитаны вводная, список материалов, задание и соседние материалы.",
                "material_role": "Раскрыть текущую тему без повтора оболочки.",
                "continuity": "Продолжить введённую идею, добавить новый прикладной слой и передать следующий шаг.",
            })
        if payload.get("format_profile") == "course":
            payload.setdefault("course_continuity", [{
                "idea": "Главный принцип курса",
                "route": "Вводится в первом этапе, развивается во втором и применяется в финале.",
            }])
        task = self.root / f"task-{len(list(self.root.glob('task-*')))}.json"
        output = self.root / f"pack-{len(list(self.root.glob('pack-*')))}.json"
        task.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = author_workflow.prepare(task, self.index, output)
        self.assertEqual(result["status"], "prepared")
        return output, json.loads(output.read_text(encoding="utf-8"))

    def test_four_profiles_prepare_and_validate(self) -> None:
        source = " ".join(["Исходная авторская мысль с примером и подробным объяснением."] * 12)
        cases = [
            ({"note": "структура материала", "work_profile": "structure", "edit_mode": "structure_only", "source_text": source, "structural_labels": ["Раздел"]}, "## Раздел\n\n" + source, "pass"),
            ({"note": "транскрипт питание", "work_profile": "transcript_to_article", "edit_mode": "rewrite", "source_text": source, "rewrite_goal": "Собрать статью", "preservation_anchors": ["авторская мысль"]}, source, "manual_review_required"),
            ({"note": "новый материал питание", "work_profile": "new_material", "edit_mode": "draft"}, "Совершенно новый готовый материал.", "manual_review_required"),
            ({"note": "развитие статьи", "work_profile": "develop_existing", "edit_mode": "proofread", "source_text": source, "preservation_anchors": ["авторская мысль"]}, source, "manual_review_required"),
        ]
        for task, draft_text, expected in cases:
            pack_path, pack = self.pack(task)
            self.assertEqual(pack["content_contract"]["work_profile_source"], "explicit")
            draft = self.root / f"draft-{task['work_profile']}.md"
            draft.write_text(draft_text, encoding="utf-8")
            self.assertEqual(validate_author_draft.validate(pack_path, draft)["status"], expected)

    def test_full_source_and_sparse_basis_route_different_owner_outputs(self) -> None:
        source = "Полный авторский исходник с примером, ходом мысли и выводом."
        _, full_pack = self.pack({
            "note": "Преемственно развить статью",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_basis": "full_source",
            "source_text": source,
            "rewrite_goal": "Уточнить один блок",
            "preservation_anchors": ["Полный авторский исходник"],
        })
        self.assertIn(
            "without an automatic suggestion appendix",
            " ".join(full_pack["instructions"]),
        )

        sparse_pack_path, sparse_pack = self.pack({
            "note": "Написать новый материал из короткой заметки",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "source_basis": "sparse_basis",
        })
        self.assertIn("clearly non-publishable owner-review note", " ".join(sparse_pack["instructions"]))
        sparse_draft = self.root / "sparse-draft.md"
        sparse_draft.write_text("Полноценный новый материал.", encoding="utf-8")
        pending = validate_author_draft.validate(
            sparse_pack_path, sparse_draft
        )["pending_manual_reviews"]
        self.assertIn("sparse_basis_owner_review", {item["id"] for item in pending})

    def test_three_transcript_roles_are_explicit_and_separated(self) -> None:
        source = "Автор подробно объясняет мысль и приводит живой пример. " * 8
        for role in ("article_source", "video_script"):
            pack_path, pack = self.pack({
                "note": f"Транскрипт как {role}",
                "work_profile": "transcript_to_article",
                "edit_mode": "rewrite",
                "source_basis": "full_source",
                "transcript_role": role,
                "source_text": source,
                "rewrite_goal": "Собрать готовый материал",
                "preservation_anchors": ["живой пример"],
            })
            self.assertEqual(pack["content_contract"]["transcript_role"], role)
            draft = self.root / f"{role}.md"
            draft.write_text(source, encoding="utf-8")
            pending = {
                item["id"] for item in validate_author_draft.validate(pack_path, draft)["pending_manual_reviews"]
            }
            self.assertIn("rewrite_continuity", pending)
            self.assertEqual("transcript_output_role" in pending, role == "video_script")

        context_pack_path, context_pack = self.pack({
            "note": "Написать дополняющий гайд рядом с видео",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "source_basis": "sparse_basis",
            "transcript_role": "context_only",
            "transcript_context": source,
        })
        self.assertEqual(context_pack["content_contract"]["transcript_role"], "context_only")
        context_draft = self.root / "context-only.md"
        context_draft.write_text("Самостоятельный дополняющий гайд.", encoding="utf-8")
        pending = {
            item["id"] for item in validate_author_draft.validate(context_pack_path, context_draft)["pending_manual_reviews"]
        }
        self.assertEqual(
            pending,
            {"transcript_context_separation", "sparse_basis_owner_review", "semantic_facts"},
        )
        semantic_check = next(
            item
            for item in validate_author_draft.validate(
                context_pack_path, context_draft
            )["pending_manual_reviews"]
            if item["id"] == "semantic_facts"
        )
        self.assertEqual(semantic_check["items"], [])
        self.assertIn("entire assembled draft", semantic_check["instruction"])

    def test_course_material_requires_whole_day_context_and_continuity(self) -> None:
        task = self.root / "missing-course-context.json"
        task.write_text(json.dumps({
            "note": "Материал дня",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "source_basis": "sparse_basis",
            "surface_context": "course_material",
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "course_context is required"):
            prepare_author_post.build_pack(task, self.index)

        pack_path, pack = self.pack({
            "note": "Материал дня",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "source_basis": "sparse_basis",
            "surface_context": "course_material",
        })
        self.assertIn("новый прикладной слой", pack["content_contract"]["course_context"]["continuity"])
        draft = self.root / "course-material.md"
        draft.write_text("Готовый материал дня.", encoding="utf-8")
        pending = validate_author_draft.validate(pack_path, draft)["pending_manual_reviews"]
        self.assertIn("course_context_continuity", {item["id"] for item in pending})

        course_path, _ = self.pack({
            "note": "Полный живой курс",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "source_basis": "sparse_basis",
            "format_profile": "course",
            "product": "calorie_course",
            "course_outline": [
                {"day": 1, "materials": ["Один материал"]},
                {"day": 2, "materials": ["Первый", "Второй", "Третий"]},
            ],
            "course_structure_source": "course-structure.md",
        })
        course_draft = self.root / "course.md"
        course_draft.write_text("Полный пакет курса.", encoding="utf-8")
        pending = validate_author_draft.validate(course_path, course_draft)["pending_manual_reviews"]
        self.assertIn("course_architecture", {item["id"] for item in pending})
        architecture = next(item for item in pending if item["id"] == "course_architecture")
        self.assertEqual(architecture["course_continuity"][0]["idea"], "Главный принцип курса")

        missing_continuity = self.root / "missing-course-continuity.json"
        missing_continuity.write_text(json.dumps({
            "note": "Полный курс без карты преемственности",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "source_basis": "sparse_basis",
            "format_profile": "course",
            "product": "calorie_course",
            "course_outline": [{"day": 1, "materials": ["Введение"]}],
            "course_structure_source": "course-structure.md",
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "course_continuity is required"):
            prepare_author_post.build_pack(missing_continuity, self.index)

    def test_new_workflow_requires_explicit_basis_and_transcript_role(self) -> None:
        task = self.root / "missing-basis.json"
        output = self.root / "missing-basis-pack.json"
        task.write_text(json.dumps({
            "note": "Новый материал",
            "work_profile": "new_material",
            "edit_mode": "draft",
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "explicit source_basis"):
            author_workflow.prepare(task, self.index, output)

        task.write_text(json.dumps({
            "note": "Транскрипт",
            "work_profile": "transcript_to_article",
            "edit_mode": "rewrite",
            "source_basis": "full_source",
            "source_text": "Полный транскрипт",
            "rewrite_goal": "Собрать статью",
            "preservation_anchors": ["транскрипт"],
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "explicit transcript_role"):
            author_workflow.prepare(task, self.index, output)

        task.write_text(json.dumps({
            "note": "Творчески пересобрать полные статьи",
            "work_profile": "new_material",
            "edit_mode": "creative_rebuild",
            "source_basis": "full_source",
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "requires task.source_text"):
            author_workflow.prepare(task, self.index, output)

        task.write_text(json.dumps({
            "note": "Творчески пересобрать полные статьи",
            "work_profile": "new_material",
            "edit_mode": "creative_rebuild",
            "source_basis": "full_source",
            "source_text": "Полный авторский исходник с важным примером.",
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "requires preservation_anchors"):
            author_workflow.prepare(task, self.index, output)

    def test_legacy_inference_and_profile_floors(self) -> None:
        task = self.root / "legacy.json"
        task.write_text(json.dumps({"note": "новый текст", "edit_mode": "draft"}), encoding="utf-8")
        pack = prepare_author_post.build_pack(task, self.index)
        self.assertEqual(pack["content_contract"]["work_profile"], "new_material")
        self.assertEqual(pack["content_contract"]["work_profile_source"], "inferred")

        task.write_text(json.dumps({
            "note": "транскрипт", "work_profile": "transcript_to_article",
            "edit_mode": "rewrite", "source_text": "достаточный исходник",
            "rewrite_goal": "статья", "preservation_anchors": ["исходник"],
            "allowed_removals": ["достаточный"], "min_token_coverage": 0.39,
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "floor"):
            prepare_author_post.build_pack(task, self.index)

        task.write_text(json.dumps({
            "note": "развитие", "work_profile": "develop_existing",
            "edit_mode": "proofread", "source_text": "достаточный исходник",
            "preservation_anchors": ["исходник"], "min_length_ratio": 0.24,
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "floor"):
            prepare_author_post.build_pack(task, self.index)

    def test_preservation_thresholds_are_inclusive_and_activate_at_exact_limits(self) -> None:
        source = " ".join(f"слово{number:03d}" for number in range(100))
        draft_text = " ".join(f"слово{number:03d}" for number in range(60))
        pack_path, pack = self.pack({
            "note": "транскрипт", "work_profile": "transcript_to_article",
            "edit_mode": "rewrite", "source_text": source, "rewrite_goal": "статья",
            "preservation_anchors": ["слово000"],
        })
        draft = self.root / "boundary.md"
        draft.write_text(draft_text, encoding="utf-8")
        metrics = validate_author_draft.preservation_metrics(source, draft_text)
        pack["content_contract"]["min_token_coverage"] = metrics["token_coverage"]
        pack["content_contract"]["min_length_ratio"] = metrics["visible_length_ratio"]
        pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        exact = validate_author_draft.validate(pack_path, draft)
        self.assertFalse(exact["protected_layer_errors"], exact)
        pack["content_contract"]["min_token_coverage"] += 0.000001
        pack["content_contract"]["min_length_ratio"] += 0.000001
        pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        below = validate_author_draft.validate(pack_path, draft)
        self.assertTrue(any("token coverage" in item for item in below["protected_layer_errors"]))
        self.assertTrue(any("visible-length" in item for item in below["protected_layer_errors"]))

        for token_count, should_activate in ((19, False), (20, True)):
            source_at_limit = " ".join(f"токен{number:02d}" for number in range(token_count))
            pack["content_contract"].update({
                "source_text": source_at_limit,
                "preservation_anchors": ["токен00"],
                "min_token_coverage": 0.60,
                "min_length_ratio": 0.0,
            })
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft.write_text("токен00", encoding="utf-8")
            errors = validate_author_draft.validate(pack_path, draft)["protected_layer_errors"]
            self.assertEqual(any("token coverage" in item for item in errors), should_activate)

        for character_count, should_activate in ((199, False), (200, True)):
            source_at_limit = "я" * character_count
            pack["content_contract"].update({
                "source_text": source_at_limit,
                "preservation_anchors": ["яя"],
                "min_token_coverage": 0.0,
                "min_length_ratio": 0.55,
            })
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft.write_text("яя", encoding="utf-8")
            errors = validate_author_draft.validate(pack_path, draft)["protected_layer_errors"]
            self.assertEqual(any("visible-length" in item for item in errors), should_activate)

    def test_structure_profile_accepts_only_allowlisted_heading_text(self) -> None:
        source = "Первый абзац.\n\nВторой абзац."
        pack_path, _ = self.pack({
            "note": "структура", "work_profile": "structure",
            "edit_mode": "structure_only", "source_text": source,
            "structural_labels": ["Раздел"],
        })
        draft = self.root / "structured.md"
        draft.write_text("## Раздел\n\n" + source, encoding="utf-8")
        self.assertEqual(validate_author_draft.validate(pack_path, draft)["status"], "pass")
        draft.write_text("## Новый смысл\n\n" + source, encoding="utf-8")
        self.assertEqual(validate_author_draft.validate(pack_path, draft)["status"], "needs_fix")

    def test_structure_profile_cannot_delete_move_or_duplicate_authored_heading(self) -> None:
        source = "Вступление.\n\n## Раздел\n\nАвторский текст."
        pack_path, _ = self.pack({
            "note": "структура", "work_profile": "structure",
            "edit_mode": "structure_only", "source_text": source,
            "structural_labels": ["Раздел", "Новый заголовок"],
        })
        draft = self.root / "authored-heading.md"

        draft.write_text(
            "Вступление.\n\n### Раздел\n\nАвторский текст.", encoding="utf-8"
        )
        self.assertEqual(
            validate_author_draft.validate(pack_path, draft)["status"], "pass"
        )

        for invalid in (
            "Вступление.\n\nАвторский текст.",
            "## Раздел\n\nВступление.\n\nАвторский текст.",
            "Вступление.\n\n### раздел\n\nАвторский текст.",
            "Вступление.\n\n## Раздел\n\n## Раздел\n\nАвторский текст.",
            "## Новый заголовок\n\n## Новый заголовок\n\n" + source,
        ):
            draft.write_text(invalid, encoding="utf-8")
            self.assertEqual(
                validate_author_draft.validate(pack_path, draft)["status"],
                "needs_fix",
            )

    def test_exact_removal_ledger_is_removed_from_coverage_baseline(self) -> None:
        removable = "Разговорное отступление " * 30
        kept = "Основная авторская мысль с примером и объяснением. " * 20
        pack_path, _ = self.pack({
            "note": "транскрипт", "work_profile": "transcript_to_article",
            "edit_mode": "rewrite", "source_text": removable + kept,
            "rewrite_goal": "убрать отступление", "preservation_anchors": ["Основная авторская мысль"],
            "allowed_removals": [removable],
        })
        draft = self.root / "without-removal.md"
        draft.write_text(kept, encoding="utf-8")
        self.assertEqual(validate_author_draft.validate(pack_path, draft)["status"], "manual_review_required")

    def test_missing_anchor_and_coverage_need_fix(self) -> None:
        source = " ".join(f"Уникальная мысль номер {number} объясняет питание подробно." for number in range(40))
        pack_path, _ = self.pack({
            "note": "транскрипт питание", "work_profile": "transcript_to_article",
            "edit_mode": "rewrite", "source_text": source, "rewrite_goal": "статья",
            "preservation_anchors": ["Уникальная мысль номер 12"],
        })
        draft = self.root / "short.md"
        draft.write_text("Очень короткий пересказ.", encoding="utf-8")
        result = validate_author_draft.validate(pack_path, draft)
        self.assertEqual(result["status"], "needs_fix")
        self.assertTrue(any("anchor" in item for item in result["protected_layer_errors"]))
        self.assertTrue(any("coverage" in item for item in result["protected_layer_errors"]))

    def test_validator_cli_exit_codes(self) -> None:
        new_pack, _ = self.pack({
            "note": "новый материал", "work_profile": "new_material", "edit_mode": "draft"
        })
        new_draft = self.root / "new.md"
        new_draft.write_text("Готовый текст.", encoding="utf-8")
        with patch.object(sys, "argv", ["validate_author_draft.py", "--pack", str(new_pack), "--draft", str(new_draft)]), redirect_stdout(StringIO()):
            self.assertEqual(validate_author_draft.main(), 2)

        source = " ".join(["Авторская мысль остаётся в подробном объяснении."] * 10)
        review_pack, _ = self.pack({
            "note": "транскрипт", "work_profile": "transcript_to_article",
            "edit_mode": "rewrite", "source_text": source, "rewrite_goal": "статья",
            "preservation_anchors": ["Авторская мысль"],
        })
        review_draft = self.root / "review.md"
        review_draft.write_text(source, encoding="utf-8")
        with patch.object(sys, "argv", ["validate_author_draft.py", "--pack", str(review_pack), "--draft", str(review_draft)]), redirect_stdout(StringIO()):
            self.assertEqual(validate_author_draft.main(), 2)
        review_draft.write_text("Слишком коротко.", encoding="utf-8")
        with patch.object(sys, "argv", ["validate_author_draft.py", "--pack", str(review_pack), "--draft", str(review_draft)]), redirect_stdout(StringIO()):
            self.assertEqual(validate_author_draft.main(), 1)

    def test_exact_review_set_hashes_and_fact_expiry(self) -> None:
        source = " ".join(["Авторская мысль и проверяемый факт остаются в материале."] * 10)
        pack_path, _ = self.pack({
            "note": "развить статью", "work_profile": "develop_existing",
            "edit_mode": "rewrite", "source_text": source, "rewrite_goal": "усилить",
            "preservation_anchors": ["Авторская мысль"],
            "required_facts": [{"text": "проверяемый факт", "mode": "semantic"}],
            "fact_sources": [{"name": "owner", "fingerprint": "sha256:abc"}],
        })
        draft = self.root / "reviewed.md"
        draft.write_text(source, encoding="utf-8")
        initial = validate_author_draft.validate(pack_path, draft)
        self.assertEqual({item["id"] for item in initial["pending_manual_reviews"]}, {"rewrite_continuity", "semantic_facts"})
        fact_check = next(item for item in initial["pending_manual_reviews"] if item["id"] == "semantic_facts")
        self.assertEqual(fact_check["fact_check_profile"], "editorial_materiality")
        self.assertIn("entire assembled draft", fact_check["instruction"])
        self.assertIn("do not edit the draft", fact_check["instruction"])
        review_path = self.root / "review.json"
        author_workflow.create_review(
            pack_path, draft, review_path, reviewer="Сергей",
            check_values=["rewrite_continuity=Преемственность подтверждена", "semantic_facts=Факт сверен с источником"],
        )
        self.assertEqual(validate_author_draft.validate(pack_path, draft, review_path)["status"], "pass")
        valid = json.loads(review_path.read_text(encoding="utf-8"))
        malformed = []
        missing_check = json.loads(json.dumps(valid)); missing_check["checks"] = missing_check["checks"][:-1]; malformed.append(missing_check)
        extra_check = json.loads(json.dumps(valid)); extra_check["checks"].append({"id": "extra", "result": "pass", "notes": "ok"}); malformed.append(extra_check)
        failed_check = json.loads(json.dumps(valid)); failed_check["checks"][0]["result"] = "fail"; malformed.append(failed_check)
        blank_notes = json.loads(json.dumps(valid)); blank_notes["checks"][0]["notes"] = " "; malformed.append(blank_notes)
        blank_reviewer = json.loads(json.dumps(valid)); blank_reviewer["reviewer"] = " "; malformed.append(blank_reviewer)
        stale_pack = json.loads(json.dumps(valid)); stale_pack["pack_sha256"] = "sha256:other"; malformed.append(stale_pack)
        wrong_facts = json.loads(json.dumps(valid)); wrong_facts["fact_sources"] = []; malformed.append(wrong_facts)
        future = json.loads(json.dumps(valid)); future["reviewed_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(); malformed.append(future)
        for payload in malformed:
            review_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                validate_author_draft.validate(pack_path, draft, review_path)["status"],
                "manual_review_required",
                payload,
            )

        review_path.write_text(json.dumps(valid, ensure_ascii=False), encoding="utf-8")
        stale = json.loads(review_path.read_text(encoding="utf-8"))
        stale["reviewed_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        review_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(validate_author_draft.validate(pack_path, draft, review_path)["status"], "manual_review_required")
        draft.write_text(source + " Изменение.", encoding="utf-8")
        self.assertEqual(validate_author_draft.validate(pack_path, draft, review_path)["status"], "manual_review_required")

    def test_fact_check_profile_follows_surface_and_can_be_overridden(self) -> None:
        cases = [
            ("masterclass_material", None, "instructional_strict"),
            ("course_material", None, "instructional_strict"),
            ("intensive_article", None, "instructional_strict"),
            ("telegram", None, "editorial_materiality"),
            ("pikabu", None, "editorial_materiality"),
            ("masterclass_material", "editorial_materiality", "editorial_materiality"),
        ]
        for surface, requested, expected in cases:
            task = {
                "note": "проверить факт",
                "work_profile": "new_material",
                "edit_mode": "draft",
                "surface_context": surface,
                "required_facts": [{"text": "проверяемый факт", "mode": "semantic"}],
                "fact_sources": [{"name": "source", "fingerprint": "sha256:abc"}],
            }
            if requested:
                task["fact_check_profile"] = requested
            pack_path, pack = self.pack(task)
            self.assertEqual(pack["content_contract"]["fact_check_profile"], expected)
            self.assertEqual(pack["review_policy"]["fact_check_profile"], expected)
            draft = self.root / f"fact-{surface}-{requested or 'default'}.md"
            draft.write_text("проверяемый факт", encoding="utf-8")
            pending = validate_author_draft.validate(pack_path, draft)["pending_manual_reviews"]
            fact_check = next(item for item in pending if item["id"] == "semantic_facts")
            self.assertEqual(fact_check["fact_check_profile"], expected)
            if expected == "instructional_strict":
                self.assertIn("against strong sources", fact_check["instruction"])
            else:
                self.assertIn("materially false or invented facts", fact_check["instruction"])

        course_task = {
            "note": "полный учебный курс",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "format_profile": "course",
            "product": "masterclass",
            "course_outline": [{"day": 1, "materials": ["Урок"]}],
            "course_structure_source": "course-structure.md",
        }
        _, course_pack = self.pack(course_task)
        self.assertEqual(
            course_pack["content_contract"]["fact_check_profile"],
            "instructional_strict",
        )

    def test_approved_factual_targeted_edit_still_requires_semantic_review(self) -> None:
        source = "В этом месте стоит старая цифра 10. Остальной текст защищён."
        pack_path, _ = self.pack({
            "note": "Исправить одобренную фактическую цифру",
            "work_profile": "develop_existing",
            "edit_mode": "targeted_edit",
            "source_text": source,
            "editable_scope": ["старая цифра 10"],
            "preservation_anchors": ["Остальной текст защищён"],
            "required_facts": [{"text": "новая цифра 12", "mode": "semantic"}],
            "fact_sources": [{"name": "source", "fingerprint": "sha256:fact"}],
        })
        draft = self.root / "factual-targeted-edit.md"
        draft.write_text(
            source.replace("старая цифра 10", "новая цифра 12"), encoding="utf-8"
        )
        pending = validate_author_draft.validate(pack_path, draft)[
            "pending_manual_reviews"
        ]
        self.assertIn("semantic_facts", {item["id"] for item in pending})

    def test_proofread_preserves_intentional_spoken_tokens(self) -> None:
        source = "Ну вооот, кааак это объяснить? Пу-пу-пу — сейчас соберусь."
        pack_path, _ = self.pack({
            "note": "Исправить обычные ошибки, сохранив разговорную запись",
            "work_profile": "develop_existing",
            "edit_mode": "proofread",
            "source_text": source,
            "preservation_anchors": ["сейчас соберусь"],
        })
        cases = {
            "elongated": "Ну вот, как это объяснить? Пу-пу-пу — сейчас соберусь.",
            "repeated": "Ну вооот, кааак это объяснить? Пу-пу — сейчас соберусь.",
        }
        for name, changed_text in cases.items():
            with self.subTest(name=name):
                changed = self.root / f"normalized-spoken-{name}.md"
                changed.write_text(changed_text, encoding="utf-8")
                result = validate_author_draft.validate(pack_path, changed)
                self.assertEqual(result["status"], "needs_fix")
                self.assertIn(
                    "proofread changed intentional elongated or repeated spoken tokens",
                    result["protected_layer_errors"],
                )

    def test_rewrite_and_creative_rebuild_factcheck_whole_draft_without_fact_list(self) -> None:
        source = "Полный авторский исходник с важным примером и основной мыслью."
        cases = (
            {
                "note": "Пересобрать авторский материал",
                "work_profile": "develop_existing",
                "edit_mode": "rewrite",
                "source_text": source,
                "rewrite_goal": "Собрать новую версию",
                "preservation_anchors": ["важным примером"],
            },
            {
                "note": "Творчески пересобрать полные статьи",
                "work_profile": "new_material",
                "edit_mode": "creative_rebuild",
                "source_basis": "full_source",
                "source_text": source,
                "preservation_anchors": ["важным примером"],
            },
        )
        for task in cases:
            with self.subTest(edit_mode=task["edit_mode"]):
                pack_path, _ = self.pack(task)
                draft = self.root / f"whole-{task['edit_mode']}.md"
                draft.write_text(source, encoding="utf-8")
                pending = validate_author_draft.validate(pack_path, draft)[
                    "pending_manual_reviews"
                ]
                semantic = [item for item in pending if item["id"] == "semantic_facts"]
                self.assertEqual(len(semantic), 1)
                self.assertEqual(semantic[0]["items"], [])

    def test_whole_draft_fact_review_without_sources_does_not_expire(self) -> None:
        pack_path, _ = self.pack({
            "note": "Новый короткий материал",
            "work_profile": "new_material",
            "edit_mode": "draft",
        })
        draft = self.root / "whole-draft-review.md"
        draft.write_text("Самостоятельный готовый текст.", encoding="utf-8")
        initial = validate_author_draft.validate(pack_path, draft)
        checks = [
            f"{item['id']}=Проверка выполнена"
            for item in initial["pending_manual_reviews"]
        ]
        review_path = self.root / "whole-draft-review.json"
        author_workflow.create_review(
            pack_path,
            draft,
            review_path,
            reviewer="Сергей",
            check_values=checks,
        )
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["reviewed_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat()
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        result = validate_author_draft.validate(pack_path, draft, review_path)
        self.assertEqual(result["status"], "pass")
        self.assertIsNone(result["fact_review_expires_at"])

        invalid = {
            "note": "проверить факт",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "fact_check_profile": "pedantic",
        }
        task_path = self.root / "invalid-fact-profile.json"
        task_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown fact_check_profile"):
            prepare_author_post.build_pack(task_path, self.index)

        invalid_surface = {
            "note": "учебный материал",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "surface_context": "masterclass",
        }
        task_path.write_text(json.dumps(invalid_surface, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown surface_context"):
            prepare_author_post.build_pack(task_path, self.index)

    def test_required_facts_require_sources_and_editorial_wording_is_not_literal(self) -> None:
        missing_sources = {
            "note": "проверить факт",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "required_facts": [{"text": "около 500 граммов", "mode": "semantic"}],
        }
        task_path = self.root / "missing-fact-sources.json"
        task_path.write_text(json.dumps(missing_sources, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fact_sources is required"):
            prepare_author_post.build_pack(task_path, self.index)

        malformed_facts = {
            **missing_sources,
            "required_facts": {"text": "около 500 граммов"},
            "fact_sources": [{"name": "source", "fingerprint": "sha256:abc"}],
        }
        task_path.write_text(json.dumps(malformed_facts, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "required_facts must be a list"):
            prepare_author_post.build_pack(task_path, self.index)

        pack_path, _ = self.pack({
            **missing_sources,
            "surface_context": "telegram",
            "fact_sources": [{"name": "source", "fingerprint": "sha256:abc"}],
        })
        draft = self.root / "editorial-approximation.md"
        draft.write_text(
            "Не надо превращать полкило в магическую границу: это примерно пятьсот граммов.",
            encoding="utf-8",
        )
        initial = validate_author_draft.validate(pack_path, draft)
        self.assertEqual(initial["status"], "manual_review_required")
        self.assertFalse(initial["missing_verbatim"])
        review_path = self.root / "editorial-approximation-review.json"
        author_workflow.create_review(
            pack_path,
            draft,
            review_path,
            reviewer="Редактор",
            check_values=[
                "semantic_facts=Разговорная формулировка сохраняет смысл источника",
                "sparse_basis_owner_review=Отдельное непубликуемое примечание подготовлено полностью",
            ],
        )
        self.assertEqual(
            validate_author_draft.validate(pack_path, draft, review_path)["status"],
            "pass",
        )

    def test_mixed_block_instructions_are_carried_and_verbatim_is_protected(self) -> None:
        source = (
            "Эту фразу оставить дословно.\n\n"
            "Этот тезис нужно раскрыть.\n\n"
            "Этот блок можно дополнить исследованием."
        )
        pack_path, pack = self.pack({
            "note": "Доработать разные части готового текста по комментариям",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_text": source,
            "rewrite_goal": "Применить комментарии внутри черновика",
            "preservation_anchors": ["Эту фразу оставить дословно"],
            "block_instructions": [
                {"source": "Эту фразу оставить дословно.", "action": "verbatim"},
                {
                    "source": "Этот тезис нужно раскрыть.",
                    "action": "expand_thesis",
                    "instruction": "Добавить практический пример",
                },
                {
                    "source": "Этот блок можно дополнить исследованием.",
                    "action": "research_and_write",
                },
            ],
        })
        self.assertEqual(
            pack["content_contract"]["block_instructions"][1]["action"],
            "expand_thesis",
        )
        draft = self.root / "mixed-blocks.md"
        draft.write_text(
            source.replace(
                "Этот тезис нужно раскрыть.",
                "Этот тезис нужно раскрыть. Вот практический пример.",
            ),
            encoding="utf-8",
        )
        result = validate_author_draft.validate(pack_path, draft)
        self.assertFalse(
            any("verbatim block instruction" in item for item in result["protected_layer_errors"])
        )
        self.assertIn(
            "block_instructions",
            {item["id"] for item in result["pending_manual_reviews"]},
        )

        draft.write_text(
            draft.read_text(encoding="utf-8").replace("дословно", "почти дословно"),
            encoding="utf-8",
        )
        self.assertTrue(
            any(
                "verbatim block instruction" in item
                for item in validate_author_draft.validate(pack_path, draft)[
                    "protected_layer_errors"
                ]
            )
        )

    def test_block_instruction_source_must_be_unique_in_source(self) -> None:
        task = self.root / "duplicate-block-task.json"
        task.write_text(json.dumps({
            "note": "Развить повторяющийся блок",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_basis": "full_source",
            "source_text": "Повтор. Повтор.",
            "rewrite_goal": "Раскрыть один блок",
            "preservation_anchors": ["Повтор"],
            "block_instructions": [{"source": "Повтор.", "action": "expand_thesis"}],
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must occur exactly once"):
            prepare_author_post.build_pack(task, self.index)

    def test_same_block_cannot_receive_conflicting_actions(self) -> None:
        source = "Этот блок имеет один адрес."
        task = self.root / "conflicting-block-actions.json"
        task.write_text(json.dumps({
            "note": "Не назначать блоку две операции",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_basis": "full_source",
            "source_text": source,
            "rewrite_goal": "Сохранить однозначные разрешения",
            "preservation_anchors": ["один адрес"],
            "block_instructions": [
                {"source": source, "action": "verbatim"},
                {"source": source, "action": "remove"},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "only one block_instructions action"):
            prepare_author_post.build_pack(task, self.index)

    def test_block_instructions_require_an_addressable_target_or_assignment(self) -> None:
        base = {
            "note": "Разобрать комментарии внутри текста",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_basis": "full_source",
            "source_text": "Первый блок. Второй блок.",
            "rewrite_goal": "Применить комментарии",
            "preservation_anchors": ["Первый блок"],
        }
        invalid = (
            {"action": "remove"},
            {"action": "expand_thesis"},
            {"action": "write_new"},
        )
        for number, instruction in enumerate(invalid):
            task = self.root / f"unaddressed-block-{number}.json"
            task.write_text(
                json.dumps(
                    {**base, "block_instructions": [instruction]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid block action"):
                prepare_author_post.build_pack(task, self.index)

    def test_find_author_material_and_write_new_are_valid_block_routes(self) -> None:
        source = "Здесь нужно найти мой старый пример."
        _, pack = self.pack({
            "note": "Собрать два назначенных блока",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_text": source,
            "rewrite_goal": "Применить комментарии по блокам",
            "preservation_anchors": ["старый пример"],
            "block_instructions": [
                {"source": source, "action": "find_author_material"},
                {
                    "action": "write_new",
                    "instruction": "Добавить короткий переход к следующему разделу",
                    "placement": "После найденного авторского примера",
                },
            ],
        })
        self.assertEqual(
            [item["action"] for item in pack["content_contract"]["block_instructions"]],
            ["find_author_material", "write_new"],
        )

    def test_remove_block_instruction_updates_preservation_baseline(self) -> None:
        removable = "Удаляемое длинное вступление. " * 40
        kept = "Сохраняемый основной авторский блок. " * 20
        pack_path, pack = self.pack({
            "note": "Удалить прямо отмеченное вступление",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_text": removable + kept,
            "rewrite_goal": "Убрать вступление",
            "preservation_anchors": ["Сохраняемый основной авторский блок"],
            "block_instructions": [
                {"source": removable, "action": "remove"},
            ],
        })
        self.assertIn(removable, pack["content_contract"]["allowed_removals"])
        draft = self.root / "removed-block.md"
        draft.write_text(kept, encoding="utf-8")
        result = validate_author_draft.validate(pack_path, draft)
        self.assertFalse(
            any("coverage" in item or "length" in item for item in result["protected_layer_errors"])
        )

    def test_verbatim_only_block_instruction_needs_no_duplicate_manual_review(self) -> None:
        source = "Эта цитата остаётся дословно."
        pack_path, _ = self.pack({
            "note": "Сохранить цитату",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_text": source,
            "rewrite_goal": "Сохранить материал",
            "preservation_anchors": ["остаётся дословно"],
            "block_instructions": [{"source": source, "action": "verbatim"}],
        })
        draft = self.root / "verbatim-only.md"
        draft.write_text(source, encoding="utf-8")
        pending = validate_author_draft.validate(pack_path, draft)[
            "pending_manual_reviews"
        ]
        self.assertNotIn("block_instructions", {item["id"] for item in pending})

    def test_verbatim_is_accepted_in_narrow_structure_route(self) -> None:
        source = "Эта цитата остаётся дословно."
        for profile, mode in (
            ("develop_existing", "proofread"),
            ("structure", "structure_only"),
        ):
            pack_path, pack = self.pack({
                "note": "Защитить цитату",
                "work_profile": profile,
                "edit_mode": mode,
                "source_text": source,
                "preservation_anchors": ["остаётся дословно"],
                "block_instructions": [{"source": source, "action": "verbatim"}],
            })
            self.assertEqual(
                pack["content_contract"]["block_instructions"][0]["action"],
                "verbatim",
            )
            draft = self.root / f"verbatim-{mode}.md"
            draft.write_text(source, encoding="utf-8")
            result = validate_author_draft.validate(pack_path, draft)
            self.assertFalse(result["protected_layer_errors"])
            self.assertNotIn(
                "block_instructions",
                {item["id"] for item in result["pending_manual_reviews"]},
            )

    def test_light_edit_requires_addressable_manual_review(self) -> None:
        source = "Эту фразу можно слегка поправить."
        pack_path, _ = self.pack({
            "note": "Слегка поправить фразу",
            "work_profile": "develop_existing",
            "edit_mode": "rewrite",
            "source_text": source,
            "rewrite_goal": "Исправить только назначенный фрагмент",
            "preservation_anchors": ["слегка поправить"],
            "block_instructions": [{"source": source, "action": "light_edit"}],
        })
        draft = self.root / "light-edit.md"
        draft.write_text("Эту фразу нужно слегка поправить.", encoding="utf-8")
        pending = validate_author_draft.validate(pack_path, draft)[
            "pending_manual_reviews"
        ]
        self.assertIn("block_instructions", {item["id"] for item in pending})

    def test_marketing_brief_is_preserved_in_content_contract(self) -> None:
        brief = {
            "audience_segment": "Люди, которые устали начинать заново",
            "promise": "Показать выполнимый следующий шаг",
            "offer": "Мастер-класс",
            "disclosure_boundary": "Не публиковать весь платный алгоритм",
            "cta": "Перейти к программе",
            "success_metric": "Переход на страницу продукта",
        }
        _, pack = self.pack({
            "note": "Написать продуктовый пост",
            "work_profile": "new_material",
            "edit_mode": "draft",
            "marketing_brief": brief,
        })
        self.assertEqual(pack["content_contract"]["marketing_brief"], brief)

    def test_known_marketing_brief_fields_must_be_non_empty_strings(self) -> None:
        for number, brief in enumerate(({"cta": ""}, {"success_metric": 7})):
            task = self.root / f"invalid-marketing-brief-{number}.json"
            task.write_text(json.dumps({
                "note": "Написать продуктовый пост",
                "work_profile": "new_material",
                "edit_mode": "draft",
                "marketing_brief": brief,
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be non-empty strings"):
                prepare_author_post.build_pack(task, self.index)

    def test_substantive_block_action_cannot_run_inside_proofread(self) -> None:
        task = self.root / "substantive-proofread.json"
        task.write_text(json.dumps({
            "note": "Структурировать и раскрыть тезис",
            "work_profile": "develop_existing",
            "edit_mode": "proofread",
            "source_basis": "full_source",
            "source_text": "Этот тезис нужно раскрыть.",
            "preservation_anchors": ["Этот тезис"],
            "block_instructions": [{
                "source": "Этот тезис нужно раскрыть.",
                "action": "expand_thesis",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "require rewrite before proofread"):
            prepare_author_post.build_pack(task, self.index)

    def test_light_edit_cannot_run_inside_structure_only(self) -> None:
        task = self.root / "light-edit-structure-only.json"
        task.write_text(json.dumps({
            "note": "Структурировать и слегка поправить фразу",
            "work_profile": "structure",
            "edit_mode": "structure_only",
            "source_basis": "full_source",
            "source_text": "Эту фразу можно слегка поправить.",
            "preservation_anchors": ["слегка поправить"],
            "block_instructions": [{
                "source": "Эту фразу можно слегка поправить.",
                "action": "light_edit",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "require rewrite before structure_only"):
            prepare_author_post.build_pack(task, self.index)

    def test_recording_correction_refreshes_semantic_counters(self) -> None:
        memory = self.root / "correction-memory.jsonl"
        (self.root / "semantic-report.json").write_text(
            json.dumps({"correction_chains": 0}), encoding="utf-8"
        )
        (self.root / "analysis-state.json").write_text(
            json.dumps({"correction_chains": 0}), encoding="utf-8"
        )
        result = record_author_correction.record_payload({
            "request": "Сделать материал",
            "assistant_draft": "Черновик",
            "owner_feedback": "Сохранить исходные слова",
            "owner_revision": "Финальный авторский текст",
        }, memory, self.index)
        self.assertEqual(result["status"], "recorded")
        semantic = json.loads((self.root / "semantic-report.json").read_text(encoding="utf-8"))
        state = json.loads((self.root / "analysis-state.json").read_text(encoding="utf-8"))
        self.assertEqual(semantic["correction_chains"], 1)
        self.assertEqual(state["correction_chains"], 1)
        self.assertIn("corrections_updated_at", semantic)

    def test_health_reports_one_fresh_voice_state(self) -> None:
        health_index = self.root / "voice-index.sqlite"
        empty_voice_index(health_index)
        memory = self.root / "correction-memory.jsonl"
        memory.write_text(json.dumps({"correction_id": "one"}) + "\n", encoding="utf-8")
        (self.root / "semantic-report.json").write_text(json.dumps({"correction_chains": 1}), encoding="utf-8")
        (self.root / "analysis-state.json").write_text(json.dumps({"correction_chains": 1}), encoding="utf-8")
        with sqlite3.connect(health_index) as db:
            db.execute("INSERT INTO corrections VALUES (?, ?)", ("one", "{}"))
        # The production installer uses a managed copy so a task worktree cannot
        # mutate the runtime skill before its change is accepted.
        with tempfile.TemporaryDirectory() as skill_folder:
            destination = Path(skill_folder) / "skills/edabalans-writer/SKILL.md"
            install_edabalans_writer_skill.install(
                install_edabalans_writer_skill.SOURCE, destination
            )
            with patch.object(
                install_edabalans_writer_skill,
                "default_destination",
                return_value=destination,
            ):
                result = report_author_corpus_health.voice_freshness(self.root)
            self.assertEqual(result["status"], "current", result)
            (self.root / "semantic-report.json").write_text(
                json.dumps({"correction_chains": 0}), encoding="utf-8"
            )
            with patch.object(
                install_edabalans_writer_skill,
                "default_destination",
                return_value=destination,
            ):
                stale = report_author_corpus_health.voice_freshness(self.root)
            self.assertEqual(stale["status"], "stale")
            self.assertIn("semantic-report correction_chains is stale", stale["errors"])

    def test_skill_manifest_digest_ignores_text_line_endings(self) -> None:
        lf = self.root / "lf.md"
        crlf = self.root / "crlf.md"
        lf.write_bytes(b"one\ntwo\n")
        crlf.write_bytes(b"one\r\ntwo\r\n")
        self.assertEqual(
            install_edabalans_writer_skill.digest(lf),
            install_edabalans_writer_skill.digest(crlf),
        )


if __name__ == "__main__":
    unittest.main()
