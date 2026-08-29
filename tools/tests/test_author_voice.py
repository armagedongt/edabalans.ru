from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_author_catalog as catalog
import build_author_voice as voice
import build_rhetorical_library as rhetoric
import install_edabalans_writer_skill as writer_skill_installer
import materialize_author_voice as materialize
import prepare_author_post as prepare
import record_author_correction as correction
import validate_author_draft as draft_validator


def whole_day_context() -> dict:
    return {
        "day_context": "Учебный день: прочитаны вводная, список материалов, задание и соседние материалы.",
        "material_role": "Раскрыть текущую тему без повтора оболочки.",
        "continuity": "Продолжить введённую идею, добавить новый прикладной слой и передать следующий шаг.",
    }


class ProjectVoiceManifestTests(unittest.TestCase):
    def test_retrieval_full_text_has_a_hard_character_ceiling(self) -> None:
        rows = [{"item_id": "long", "full_text": "а" * 1000}]

        selected = prepare.bounded_full_text(rows, ("full_text",), 200)

        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0]["context_truncated"])
        self.assertLessEqual(len(selected[0]["full_text"]), 200)

    def test_project_writer_skill_installer_keeps_runtime_copy_in_sync(self) -> None:
        # The installer intentionally uses hard links so the project-owned skill and
        # its Codex runtime copy cannot drift. Keep the fixture on the source volume:
        # hosted CI may mount the checkout and /tmp on different filesystems.
        with tempfile.TemporaryDirectory(dir=TOOLS.parent) as folder:
            destination = Path(folder) / "skills" / "edabalans-writer" / "SKILL.md"
            destination.parent.mkdir(parents=True)
            destination.write_text("stale runtime copy", encoding="utf-8")

            before = writer_skill_installer.sync_status(
                writer_skill_installer.SOURCE, destination
            )
            self.assertEqual(before["status"], "outdated")
            self.assertFalse(before["hard_linked"])

            installed = writer_skill_installer.install(writer_skill_installer.SOURCE, destination)

            self.assertEqual(installed["status"], "current")
            self.assertTrue(installed["hard_linked"])
            self.assertTrue(destination.samefile(writer_skill_installer.SOURCE))
            self.assertEqual(destination.read_bytes(), writer_skill_installer.SOURCE.read_bytes())

    def test_writer_skill_manifest_hash_ignores_checkout_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            windows = root / "windows.md"
            unix = root / "unix.md"
            windows.write_bytes(b"first\r\nsecond\r\n")
            unix.write_bytes(b"first\nsecond\n")

            self.assertEqual(
                writer_skill_installer.canonical_text_digest(windows),
                writer_skill_installer.canonical_text_digest(unix),
            )

    def test_writer_skill_package_status_uses_canonical_text_hash(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            canonical = root / "canonical.md"
            canonical.write_bytes(b"first\r\nsecond\r\n")
            expected_source = root / "expected.md"
            expected_source.write_bytes(b"first\nsecond\n")

            manifest = root / "skill-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "package_version": "test",
                        "files": [
                            {
                                "path": "canonical.md",
                                "sha256": writer_skill_installer.canonical_text_digest(
                                    expected_source
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            destination = root / "skills/edabalans-writer/SKILL.md"
            installed_manifest = destination.parent / "assets" / manifest.name
            installed_manifest.parent.mkdir(parents=True)
            installed_manifest.hardlink_to(manifest)

            with (
                patch.object(writer_skill_installer, "PROJECT_ROOT", root),
                patch.object(writer_skill_installer, "MANIFEST", manifest),
            ):
                result = writer_skill_installer.package_status(destination)

            self.assertEqual(result["package_status"], "current", result)

    def test_retrieval_depth_applies_item_and_full_text_ceilings(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            exemplars = [
                {
                    "exemplar_id": f"ex:{number}",
                    "catalog_id": f"telegram:{number}",
                    "source": "telegram_channel",
                    "source_url": None,
                    "headline": f"Похудение {number}",
                    "text": ("похудение питание пример " * 220) + str(number),
                    "dominant_job": "education",
                    "composition_recipe": "reframe",
                    "surface_context": "telegram_channel",
                    "media_dependency": "none_recorded",
                    "related_versions": [],
                    "exact_cluster_ids": [],
                }
                for number in range(8)
            ]
            rules = [
                {
                    "rule_id": f"rule:{number}",
                    "statement": f"Похудение и питание: правило {number}",
                    "mechanism": "Показывает критерий.",
                    "counter_boundary": "Не превращать в запрет.",
                    "section": "reasoning",
                    "scope": ["all"],
                }
                for number in range(10)
            ]
            rhetoric_rows = [
                {
                    "entry_id": f"rhet:{number}",
                    "catalog_id": f"telegram:rhet:{number}",
                    "text": f"Похудение и питание: риторический ход {number}",
                    "family": "hook",
                    "subtype": "question",
                    "function": "Открыть мысль.",
                    "dominant_job": "education",
                    "surface_context": "telegram_channel",
                }
                for number in range(15)
            ]
            corrections = [
                {
                    "correction_id": f"correction:{number}",
                    "title": f"Похудение и питание: правка {number}",
                    "full_case": ("похудение питание коррекция " * 20) + str(number),
                    "candidate_rules": ["rule"],
                }
                for number in range(3)
            ]
            corpus = [
                {
                    "corpus_id": f"corpus:{number}",
                    "catalog_id": f"telegram:history:{number}",
                    "source": "telegram_channel",
                    "source_url": None,
                    "headline": f"История похудения {number}",
                    "text": f"Похудение питание тематическая история {number}",
                    "dominant_job": "education",
                    "surface_context": "telegram_channel",
                    "related_versions": [],
                    "exact_cluster_ids": [],
                }
                for number in range(15)
            ]
            materialize.build_index(
                index, rules, exemplars, [], corrections, rhetoric_rows, corpus
            )

            for depth in ("light", "standard", "deep"):
                with self.subTest(depth=depth):
                    task_path.write_text(json.dumps({
                        "note": "Пост про похудение и питание",
                        "retrieval_depth": depth,
                    }, ensure_ascii=False), encoding="utf-8")
                    pack = prepare.build_pack(task_path, index)
                    profile = prepare.RETRIEVAL_PROFILES[depth]
                    rows = pack["retrieval"]["exemplars"]
                    self.assertEqual(len(rows), profile["exemplars"])
                    self.assertEqual(
                        len(pack["retrieval"]["rhetoric"]), profile["rhetoric"]
                    )
                    self.assertEqual(
                        len(pack["retrieval"]["corrections"]), profile["corrections"]
                    )
                    self.assertEqual(len(pack["retrieval"]["rules"]), profile["rules"])
                    self.assertEqual(
                        len(pack["retrieval"]["topic_history"]), profile["history"]
                    )
                    self.assertLessEqual(
                        sum(len(row.get("full_text") or "") for row in rows),
                        profile["full_text_characters"],
                    )

    def test_all_authoring_canon_files_have_one_platform_content_owner(self) -> None:
        project_root = TOOLS.parent
        registry = tomllib.loads(
            (project_root / "docs" / "modules.toml").read_text(encoding="utf-8")
        )
        modules = registry["modules"]
        owners: dict[str, list[str]] = {}
        for module in modules:
            for path in module.get("owns_files", []):
                owners.setdefault(path, []).append(module["id"])

        canon_files = {
            path.relative_to(project_root).as_posix()
            for path in (project_root / "content" / "author-voice").rglob("*")
            if path.is_file()
        }
        self.assertTrue(canon_files)
        self.assertEqual(
            {path: owners.get(path) for path in sorted(canon_files)},
            {path: ["platform.content"] for path in sorted(canon_files)},
        )
        required_owned_files = {
            "docs/knowledge-base/ARTICLE_STANDARD.md",
            "tools/build_rhetorical_library.py",
            "tools/prepare_author_post.py",
            "tools/record_author_correction_from_codex.py",
            "tools/validate_author_draft.py",
        }
        self.assertEqual(
            {path: owners.get(path) for path in sorted(required_owned_files)},
            {path: ["platform.content"] for path in sorted(required_owned_files)},
        )

    def test_project_routes_every_writing_task_through_writer_skill(self) -> None:
        project_root = TOOLS.parent
        agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("выполнять только через skill `edabalans-writer`", agents)
        self.assertIn("Единый писательский канон принадлежит только модулю `platform.content`", agents)

    def test_expanded_exemplar_core_is_unique_and_keeps_owner_named_posts(self) -> None:
        project_root = TOOLS.parent
        payload = json.loads(
            (project_root / "content" / "author-voice" / "semantic-exemplars-v1.json")
            .read_text(encoding="utf-8")
        )
        exemplars = payload["exemplars"]
        ids = [row["catalog_id"] for row in exemplars]

        self.assertEqual(payload["status"], "reviewed_expanded_core")
        self.assertEqual(len(ids), 82)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            sum(bool(row.get("eligibility_override")) for row in exemplars),
            8,
        )
        self.assertNotIn("telegram:1878297271:837", ids)
        self.assertTrue({
            "pikabu:10877887",
            "pikabu:11269472",
            "pikabu:11989790",
            "pikabu:13277231",
            "telegram:1878297271:262",
            "telegram:1878297271:263",
            "telegram:1878297271:698",
            "telegram:1878297271:795",
        }.issubset(ids))

        jobs: dict[str, int] = {}
        for row in exemplars:
            jobs[row["job"]] = jobs.get(row["job"], 0) + 1
        self.assertEqual(jobs, {
            "education": 53,
            "personal": 11,
            "engagement": 8,
            "sales": 10,
        })

        rules = json.loads(
            (project_root / "content" / "author-voice" / "voice-rules-v1.json")
            .read_text(encoding="utf-8")
        )
        evidence_ids = {
            evidence_id
            for rule in rules["rules"]
            for evidence_id in rule.get("evidence_ids", [])
        }
        self.assertNotIn("telegram:1878297271:837", evidence_ids)

    def test_expanded_core_matches_private_catalog_when_available(self) -> None:
        private_root = Path(r"C:\private\edabalans-content-authoring")
        cards_path = private_root / "working" / "author-content-cards.jsonl"
        assessments_path = private_root / "voice" / "v1" / "source-assessments.jsonl"
        try:
            available = cards_path.exists() and assessments_path.exists()
        except PermissionError:
            self.skipTest("Private author corpus is protected from this process.")
        if not available:
            self.skipTest("Private author corpus is not available in this environment.")
        try:
            cards_text = cards_path.read_text(encoding="utf-8")
            assessments_text = assessments_path.read_text(encoding="utf-8")
        except PermissionError:
            self.skipTest("Private author corpus is protected from this process.")

        project_root = TOOLS.parent
        exemplars = json.loads(
            (project_root / "content" / "author-voice" / "semantic-exemplars-v1.json")
            .read_text(encoding="utf-8")
        )["exemplars"]
        ids = {row["catalog_id"] for row in exemplars}
        cards = {
            row["catalog_id"]: row
            for row in (
                json.loads(line)
                for line in cards_text.splitlines()
                if line.strip()
            )
        }
        assessments = {
            row["catalog_id"]: row
            for row in (
                json.loads(line)
                for line in assessments_text.splitlines()
                if line.strip()
            )
        }

        self.assertEqual(ids - cards.keys(), set())
        sources: dict[str, int] = {}
        hashes: dict[str, list[str]] = {}
        for catalog_id in ids:
            source = cards[catalog_id]["source"]
            sources[source] = sources.get(source, 0) + 1
            normalized_hash = assessments[catalog_id]["normalized_text_hash"]
            hashes.setdefault(normalized_hash, []).append(catalog_id)

        self.assertEqual(sources, {
            "pikabu": 39,
            "telegram_channel": 34,
            "tilda_site": 6,
            "bot_constructor": 3,
        })
        self.assertEqual(
            {value: group for value, group in hashes.items() if len(group) > 1},
            {},
        )


class CatalogAuthorshipTests(unittest.TestCase):
    def test_telegram_preserves_embedded_link_targets(self) -> None:
        item = {
            "external_id": "telegram:1",
            "text_content": "Читайте продолжение",
            "blocks": [{"entities": [{"href": "https://pikabu.ru/story/42"}]}],
        }

        card = catalog.card_from_telegram(item)

        self.assertEqual(card["links"], ["https://pikabu.ru/story/42"])

    def test_reply_page_separates_parent_context_from_owner_text(self) -> None:
        page = {
            "external_id": "story-1",
            "canonical_url": "https://pikabu.ru/story/1",
            "author_name": "another_user",
            "title": "Исходный вопрос",
            "text": "Текст исходного поста, который не является текстом Сергея. " * 5,
            "comments": [
                {"external_id": "c1", "author_name": "armagedongt", "text": "Мой развёрнутый ответ. " * 10},
                {
                    "external_id": "c2",
                    "author_name": "another_user",
                    "is_owner_comment": True,
                    "text": "Ответ автора исходного поста.",
                },
            ],
        }

        parent = catalog.card_from_pikabu(page, "armagedongt")
        replies = catalog.cards_from_pikabu_replies(page, "armagedongt")

        self.assertEqual(parent["context"]["authorship_auto"], "reply_parent_context")
        self.assertEqual(parent["voice_reference_eligibility"], "not_default_reply_parent_context")
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["catalog_id"], "pikabu-reply:c1")
        self.assertEqual(replies[0]["context"]["authorship_auto"], "own_reply")
        self.assertNotIn("Ответ автора исходного поста", replies[0]["text_plain"])


class VoiceDecisionTests(unittest.TestCase):
    @staticmethod
    def card(**overrides: object) -> dict:
        base = {
            "catalog_id": "x",
            "source": "telegram_channel",
            "text_plain": "Полноценный авторский текст. " * 20,
            "reuse_catalog": "included",
            "context": {},
            "links": [],
        }
        base.update(overrides)
        return base

    def test_link_only_variants_share_normalized_hash(self) -> None:
        first = "Одинаковая подводка https://example.com/old"
        second = "Одинаковая подводка https://another.example/new?utm=1"

        self.assertEqual(voice.normalized_hash(first), voice.normalized_hash(second))
        self.assertEqual(
            voice.normalized_hash("Одинаковая подводка"),
            voice.normalized_hash("Одинаковая подводка https://example.com/only-added-link"),
        )

    def test_parent_context_never_teaches_voice(self) -> None:
        card = self.card(context={"authorship_auto": "reply_parent_context"})

        decision, _ = voice.voice_decision(card, voice.authorship(card), "education", False)

        self.assertEqual(decision, "excluded_reply_parent_context")

    def test_owner_reply_is_eligible_when_long_enough(self) -> None:
        card = self.card(context={"authorship_auto": "own_reply"})

        decision, _ = voice.voice_decision(card, voice.authorship(card), "education", False)

        self.assertEqual(decision, "eligible")

    def test_linkout_with_original_value_is_fragment_not_full_exemplar(self) -> None:
        card = self.card(
            links=["https://pikabu.ru/story/1"],
            context={"linkout_status_reviewed": "linkout_with_original_value"},
        )

        decision, _ = voice.voice_decision(card, "own_published", "education", False)

        self.assertEqual(decision, "fragment_only")


class VoiceSearchIntegrationTests(unittest.TestCase):
    def test_direct_owner_decision_reaches_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cards = root / "cards.jsonl"
            assessments = root / "assessments.jsonl"
            rules = root / "rules.json"
            exemplars = root / "exemplars.json"
            contract = root / "contract.md"
            editorial_linking = root / "editorial-linking.md"
            case_study = root / "case.md"
            output = root / "voice"
            cards.write_text(json.dumps({
                "catalog_id": "telegram:1",
                "source": "telegram_channel",
                "source_url": "https://t.me/example/1",
                "headline": "Пример",
                "text_plain": "Полноценный пример авторского абзаца для проверки пересборки индекса.",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            assessments.write_text(json.dumps({
                "catalog_id": "telegram:1",
                "voice_use": "eligible",
                "dominant_job": "education",
                "surface_context": "telegram_channel",
                "normalized_text_hash": "test-hash",
                "exact_cluster_ids": ["telegram:1"],
                "related_versions": [],
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            rules.write_text(json.dumps({"rules": [{
                "rule_id": "language.telegram_post_formatting",
                "section": "language",
                "statement": "В Telegram у поста есть отдельный жирный заголовок.",
                "mechanism": "Применить прямое правило владельца.",
                "scope": ["telegram"],
                "counter_boundary": "К чатовой заметке не применяется.",
                "confidence": "high",
                "evidence_ids": ["owner:2026-08-26:editorial-linking"],
            }]}, ensure_ascii=False), encoding="utf-8")
            exemplars.write_text(json.dumps({"exemplars": [{
                "catalog_id": "telegram:1",
                "job": "education",
                "recipe": "explanation",
                "strength": "supporting",
            }]}, ensure_ascii=False), encoding="utf-8")
            contract.write_text("# Контракт", encoding="utf-8")
            editorial_linking.write_text(
                "# Ссылки\n\nСтандартный вход: https://telegram.me/example_bot?start=approved",
                encoding="utf-8",
            )
            case_study.write_text("# Кейс", encoding="utf-8")

            command = [
                sys.executable,
                str(TOOLS / "materialize_author_voice.py"),
                "--cards", str(cards),
                "--assessments", str(assessments),
                "--rules", str(rules),
                "--exemplars", str(exemplars),
                "--writer-contract", str(contract),
                "--editorial-linking", str(editorial_linking),
                "--case-study", str(case_study),
                "--output", str(output),
            ]
            completed = subprocess.run(
                command, check=True, capture_output=True, text=True, encoding="utf-8"
            )

            self.assertEqual(json.loads(completed.stdout)["status"], "materialized")
            evidence = json.loads((output / "voice-evidence.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(evidence["evidence"][0]["source"], "owner_decision")
            self.assertIn(
                "https://telegram.me/example_bot?start=approved",
                (output / "voice-passport-v1.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (output / "editorial-linking-v1.md").read_text(encoding="utf-8").strip(),
                editorial_linking.read_text(encoding="utf-8").strip(),
            )
            with closing(sqlite3.connect(output / "voice-index.sqlite")) as db:
                payload = json.loads(db.execute(
                    "SELECT payload_json FROM rules WHERE rule_id = ?",
                    ("language.telegram_post_formatting",),
                ).fetchone()[0])
                corpus_count = db.execute("SELECT COUNT(*) FROM corpus").fetchone()[0]
            self.assertEqual(payload["evidence"][0]["catalog_id"], "owner:2026-08-26:editorial-linking")
            self.assertEqual(corpus_count, 1)

            cached = subprocess.run(
                command, check=True, capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(json.loads(cached.stdout)["status"], "cache_hit")

            reviewed_text = "Новый проверенный разворот мысли."
            (output / "rhetorical-library-reviewed.jsonl").write_text(
                json.dumps({
                    "entry_id": "rhet:new", "catalog_id": "telegram:1",
                    "text": reviewed_text, "family": "reframe_and_turn",
                    "subtype": "criterion_shift", "function": "Сменить критерий.",
                    "mechanism": "Показать второй критерий.",
                    "works_when": [], "avoid_when": [],
                    "reuse_instruction": "Повторять механику.",
                    "review_status": "semantic_reviewed",
                    "review_provenance": {
                        "review_prompt_version": rhetoric.REVIEW_PROMPT_VERSION,
                        "reviewed_at": "2026-08-26T00:00:00+00:00",
                        "text_hash": rhetoric.text_hash(reviewed_text),
                    },
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            rebuilt_for_rhetoric = subprocess.run(
                command, check=True, capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(json.loads(rebuilt_for_rhetoric.stdout)["status"], "materialized")
            with closing(sqlite3.connect(output / "voice-index.sqlite")) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM rhetoric").fetchone()[0], 1)

            editorial_linking.write_text(
                "# Ссылки\n\nСтандартный вход: https://telegram.me/example_bot?start=changed",
                encoding="utf-8",
            )
            rebuilt = subprocess.run(
                command, check=True, capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(json.loads(rebuilt.stdout)["status"], "materialized")
            self.assertIn(
                "https://telegram.me/example_bot?start=changed",
                (output / "voice-passport-v1.md").read_text(encoding="utf-8"),
            )

    def test_old_materialization_version_is_not_current(self) -> None:
        state = {
            "materialization_sha256": "same-inputs",
            "materialization_version": "voice-semantic-v1-20260826-r2",
            "checkpoint": "semantic_materialization_complete",
        }

        self.assertFalse(materialize.materialization_state_is_current(state, "same-inputs"))
        state["materialization_version"] = materialize.MATERIALIZATION_VERSION
        self.assertTrue(materialize.materialization_state_is_current(state, "same-inputs"))

    def test_materialization_rebuild_preserves_owner_corrections(self) -> None:
        owner = {"correction_id": "correction:same", "owner_revision": "Мой текст"}
        seed = {"correction_id": "correction:same", "owner_revision": "Seed"}

        merged = materialize.merge_corrections([owner], [seed])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["owner_revision"], "Мой текст")

    def test_cache_requires_all_derived_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "one.jsonl").write_text("{}\n", encoding="utf-8")
            materialize.build_index(output / "voice.sqlite", [], [], [], [])
            self.assertTrue(voice.artifacts_ready(output, ("one.jsonl",), "voice.sqlite"))
            (output / "one.jsonl").unlink()
            self.assertFalse(voice.artifacts_ready(output, ("one.jsonl",), "voice.sqlite"))

    def test_natural_query_adds_shared_russian_prefix(self) -> None:
        query = __import__("search_author_voice").natural_fts_query("похудение")
        self.assertIn('"похуд"*', query)

    def test_reviewed_index_returns_source_linked_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "voice.sqlite"
            exemplar = {
                "exemplar_id": "ex:1",
                "catalog_id": "telegram:1",
                "source": "telegram_channel",
                "source_url": "https://t.me/example/1",
                "headline": "Про котлеты",
                "text": "Котлета с клетчаткой может быть удобнее для похудения.",
                "dominant_job": "education",
                "composition_recipe": "product_comparison",
                "surface_context": "telegram_channel",
                "media_dependency": "possible",
                "media_note": "Часть смысла могла быть в изображении.",
                "performance_signals": {"views": 1000, "rating": 42},
            }
            fragment = {
                "fragment_id": "frag:1",
                "catalog_id": "telegram:1",
                "source": "telegram_channel",
                "source_url": "https://t.me/example/1",
                "fragment_kind": "reframe_or_transition",
                "text": "Только вот короткий состав не говорит самого главного.",
                "dominant_job": "education",
                "composition_recipe": "product_comparison",
            }
            materialize.build_index(index, [], [exemplar], [fragment], [])

            completed = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS / "search_author_voice.py"),
                    "идеи про котлеты",
                    "--index",
                    str(index),
                    "--kind",
                    "exemplar",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(payload["results"][0]["catalog_id"], "telegram:1")
            self.assertEqual(payload["results"][0]["source_url"], "https://t.me/example/1")
            self.assertEqual(payload["results"][0]["media_dependency"], "possible")
            self.assertEqual(payload["results"][0]["performance_signals"]["views"], 1000)

    def test_writer_retrieval_returns_full_examples_and_rhetorical_context(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "voice.sqlite"
            exemplar = {
                "exemplar_id": "ex:1", "catalog_id": "telegram:1",
                "source": "telegram_channel", "source_url": "https://t.me/example/1",
                "headline": "Кортизол и похудение",
                "text": "Полный авторский текст про кортизол. " * 80,
                "dominant_job": "education", "composition_recipe": "reframe",
                "surface_context": "telegram_channel", "strength": "owner_named_core",
                "related_versions": [], "exact_cluster_ids": ["telegram:1"],
            }
            correction_row = {
                "correction_id": "correction:1", "title": "Кортизол: работа над ошибками",
                "full_case": "Полная цепочка авторских правок про кортизол. " * 40,
                "candidate_rules": ["hook_before_fact"],
            }
            rhetoric_row = {
                "entry_id": "rhet:1", "catalog_id": "telegram:1",
                "source": "telegram_channel", "source_url": "https://t.me/example/1",
                "text": "Так, стоп — а что если кортизол вообще не главный вопрос?",
                "context_before": "Сначала показана популярная схема.",
                "context_after": "Затем меняется критерий выбора.",
                "mechanism": "Перенести внимание с гормона на поведение.",
                "cluster_id": "cluster:1", "family": "reframe_and_turn",
                "subtype": "criterion_shift", "function": "Развернуть аргумент.",
                "dominant_job": "education", "surface_context": "telegram_channel",
                "works_when": [], "avoid_when": [], "reuse_instruction": "Повторять механику.",
            }
            materialize.build_index(
                index, [], [exemplar], [], [correction_row], [rhetoric_row]
            )

            found_exemplar = prepare.search_index(
                index, "кортизол", kind_filter="exemplar", include_full_text=True
            )["results"][0]
            found_correction = prepare.search_index(
                index, "кортизол", kind_filter="correction", include_full_text=True
            )["results"][0]
            found_rhetoric = prepare.search_index(
                index, "кортизол", kind_filter="rhetoric"
            )["results"][0]

            self.assertGreater(len(found_exemplar["full_text"]), 1000)
            self.assertGreater(len(found_correction["full_case"]), 1000)
            self.assertEqual(found_rhetoric["context_before"], "Сначала показана популярная схема.")
            self.assertEqual(found_rhetoric["mechanism"], "Перенести внимание с гормона на поведение.")
            self.assertEqual(found_rhetoric["cluster_id"], "cluster:1")

    def test_search_softly_prioritizes_strength_and_surface(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "voice.sqlite"
            base = {
                "source": "pikabu", "source_url": None,
                "headline": "Скорость похудения", "text": "скорость похудения и сроки",
                "dominant_job": "education", "composition_recipe": "calculation",
                "related_versions": [], "exact_cluster_ids": [],
            }
            owner = {
                **base, "exemplar_id": "ex:owner", "catalog_id": "pikabu:owner",
                "surface_context": "pikabu_article", "strength": "owner_named_core",
            }
            supporting = {
                **base, "exemplar_id": "ex:support", "catalog_id": "pikabu:support",
                "surface_context": "pikabu_article", "strength": "supporting",
            }
            telegram_a = {
                **base, "exemplar_id": "ex:tg", "catalog_id": "telegram:tg",
                "source": "telegram_channel", "surface_context": "telegram_channel",
                "strength": "supporting",
            }
            materialize.build_index(index, [], [supporting, owner, telegram_a], [], [])

            ranked = prepare.search_index(
                index, "скорость похудения", kind_filter="exemplar", limit=3
            )["results"]
            surface_ranked = prepare.search_index(
                index, "скорость похудения", kind_filter="exemplar",
                preferred_surface="telegram_channel", limit=3,
            )["results"]

            self.assertEqual(ranked[0]["catalog_id"], "pikabu:owner")
            self.assertLess(
                [row["catalog_id"] for row in surface_ranked].index("telegram:tg"),
                [row["catalog_id"] for row in surface_ranked].index("pikabu:support"),
            )

    def test_strength_bonus_cannot_overrule_large_relevance_gap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "voice.sqlite"
            detailed = {
                "exemplar_id": "ex:detailed", "catalog_id": "pikabu:detailed",
                "source": "pikabu", "source_url": None,
                "headline": "Разбор клетчатки в котлетах",
                "text": ("клетчатка котлета белок жир насыщение " * 80),
                "dominant_job": "education", "composition_recipe": "deep_explanation",
                "surface_context": "pikabu_article", "strength": "supporting",
                "related_versions": [], "exact_cluster_ids": [],
            }
            weak_owner = {
                "exemplar_id": "ex:weak", "catalog_id": "telegram:weak",
                "source": "telegram_channel", "source_url": None,
                "headline": "Личная заметка", "text": "Однажды я упомянул клетчатку и пошёл дальше.",
                "dominant_job": "education", "composition_recipe": "personal_note",
                "surface_context": "telegram_channel", "strength": "owner_named_core",
                "related_versions": [], "exact_cluster_ids": [],
            }
            fillers = [
                {
                    **weak_owner,
                    "exemplar_id": f"ex:filler:{number}",
                    "catalog_id": f"telegram:filler:{number}",
                    "strength": "supporting",
                    "text": f"Клетчатка мельком номер {number}.",
                }
                for number in range(6)
            ]
            materialize.build_index(index, [], [detailed, *fillers, weak_owner], [], [])

            ranked = prepare.search_index(
                index, "клетчатка котлета белок жир насыщение",
                kind_filter="exemplar", limit=3,
            )["results"]

            self.assertEqual(ranked[0]["catalog_id"], "pikabu:detailed")

    def test_russian_word_forms_and_late_filtered_result_are_found(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "voice.sqlite"
            exemplars = []
            for number in range(50):
                exemplars.append({
                    "exemplar_id": f"ex:wrong:{number}",
                    "catalog_id": f"wrong:{number}",
                    "source": "pikabu",
                    "source_url": None,
                    "headline": "Как похудеть спокойно",
                    "text": "Можно похудеть без героизма.",
                    "dominant_job": "education",
                    "composition_recipe": "explanation",
                    "surface_context": "pikabu_article",
                    "media_dependency": "none_recorded",
                })
            exemplars.append({
                "exemplar_id": "ex:target",
                "catalog_id": "telegram:target",
                "source": "telegram_channel",
                "source_url": "https://t.me/example/target",
                "headline": "Как похудеть спокойно",
                "text": "Можно похудеть без героизма.",
                "dominant_job": "education",
                "composition_recipe": "explanation",
                "surface_context": "telegram_channel",
                "media_dependency": "none_recorded",
            })
            materialize.build_index(index, [], exemplars, [], [])

            completed = subprocess.run(
                [sys.executable, str(TOOLS / "search_author_voice.py"), "похудение", "--index", str(index), "--surface", "telegram_channel", "--limit", "1"],
                check=True, capture_output=True, text=True, encoding="utf-8",
            )
            result = json.loads(completed.stdout)["results"]

            self.assertEqual(result[0]["catalog_id"], "telegram:target")

    def test_private_guard_rejects_git_tree(self) -> None:
        import search_author_voice as search

        guards = (voice.private, catalog.private, search.private, correction.private)
        for guard in guards:
            with self.subTest(guard=guard.__module__), self.assertRaises(ValueError):
                guard(TOOLS / "private-output")

    def test_owner_correction_is_persisted_and_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            memory = root / "corrections.jsonl"
            payload = root / "input.json"
            materialize.build_index(index, [], [], [], [])
            payload.write_text(json.dumps({
                "title": "Правило про предлог",
                "request": "Напиши подводку.",
                "assistant_draft": "На Мастер-классе разберём.",
                "owner_feedback": "Я всегда пишу В Мастер-классе.",
                "owner_revision": "В Мастер-классе разберём.",
                "candidate_rules": ["product_preposition_in_masterclass"],
            }, ensure_ascii=False), encoding="utf-8")

            result = correction.record(payload, memory, index)

            self.assertEqual(result["status"], "recorded")
            saved = json.loads(memory.read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("В Мастер-классе", saved["owner_revision"])
            with closing(sqlite3.connect(index)) as db:
                count = db.execute(
                    "SELECT count(*) FROM voice_fts WHERE voice_fts MATCH ? AND kind = 'correction'",
                    ('"мастер"*',),
                ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_post_pack_preserves_contract_and_draft_validator_checks_literals(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            pack_path = root / "pack.json"
            draft_path = root / "draft.txt"
            exemplar = {
                "exemplar_id": "ex:1", "catalog_id": "telegram:1", "source": "telegram_channel",
                "source_url": None, "headline": "Похудение без героизма", "text": "Можно похудеть спокойно.",
                "dominant_job": "education", "composition_recipe": "reframe", "surface_context": "telegram_channel",
                "media_dependency": "none_recorded",
            }
            materialize.build_index(index, [], [exemplar], [], [])
            task_path.write_text(json.dumps({
                "note": "Почему похудение не должно быть героизмом",
                "job": "education",
                "required_facts": [{"text": "7 граммов жира", "mode": "verbatim"}, {"text": "клетчатка удерживает влагу", "mode": "semantic"}],
                "fact_sources": [{"name": "owner source", "fingerprint": "sha256:abc"}],
                "cta": {"required_phrase": "В Мастер-классе"},
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft_path.write_text("Здесь есть 7 граммов жира. В Мастер-классе разберём подробнее.", encoding="utf-8")
            result = draft_validator.validate(pack_path, draft_path)

            self.assertEqual(pack["content_contract"]["required_facts"][0]["text"], "7 граммов жира")
            self.assertEqual(result["status"], "manual_review_required")
            self.assertEqual(result["semantic_fact_review_required_once"], ["7 граммов жира", "клетчатка удерживает влагу"])
            fact_check = next(item for item in result["pending_manual_reviews"] if item["id"] == "semantic_facts")
            self.assertEqual(fact_check["items"], ["7 граммов жира", "клетчатка удерживает влагу"])
            draft_path.write_text(
                "Здесь есть жир. В Мастер-классе разберём подробнее.",
                encoding="utf-8",
            )
            missing_verbatim = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(missing_verbatim["status"], "needs_fix")
            self.assertEqual(missing_verbatim["missing_verbatim"], ["7 граммов жира"])

    def test_rhetorical_candidates_are_never_promoted_by_extraction(self) -> None:
        card = {
            "catalog_id": "telegram:1",
            "source": "telegram_channel",
            "source_url": "https://t.me/example/1",
            "text_plain": (
                "ЖОПА ГОРИТ!!! У моих коллег.\n"
                "У вас повышен кортизол → вы не худеете → купите БАД. И так, блять, по кругу.\n"
                "Так, стоп… Я же сам нутрициолог! Есть нюанс."
            ),
            "media": {},
            "context": {},
        }
        assessment = {
            "catalog_id": "telegram:1",
            "voice_use": "eligible",
            "authorship": "own_published",
            "quality_score": 14,
            "era": "current_2025_plus",
            "dominant_job": "education",
            "surface_context": "telegram_channel",
            "composition_map": ["hook", "reframe"],
            "exact_cluster_ids": ["telegram:1"],
            "tone_dials": {},
        }

        rows = rhetoric.build_candidates([card], [assessment])

        self.assertTrue(rows)
        self.assertTrue(all(row["review_status"] == "candidate_unreviewed" for row in rows))
        self.assertIn("causal_chain", {hint for row in rows for hint in row["family_hints_auto"]})
        self.assertIn("reframe_and_turn", {hint for row in rows for hint in row["family_hints_auto"]})

    def test_reviewed_rhetoric_requires_semantic_provenance_and_matching_hash(self) -> None:
        text = "Так, стоп… Я же сам нутрициолог!"
        entry = {
            "entry_id": "rhet:1",
            "text": text,
            "catalog_id": "case:nutritionists-law",
            "family": "reframe_and_turn",
            "subtype": "self_reveal",
            "function": "Сменить роль автора.",
            "mechanism": "Применить критику к себе.",
            "works_when": ["Автор относится к критикуемой категории."],
            "avoid_when": ["Поворот не меняет аргумент."],
            "reuse_instruction": "Повторять механику, не фразу.",
            "review_status": "semantic_reviewed",
            "review_provenance": {
                "review_prompt_version": rhetoric.REVIEW_PROMPT_VERSION,
                "reviewed_at": "2026-08-26T00:00:00+00:00",
                "text_hash": rhetoric.text_hash(text),
            },
        }

        merged = rhetoric.merge_review_batch([entry], [])

        self.assertEqual(merged[0]["entry_id"], "rhet:1")
        broken = {**entry, "review_provenance": {**entry["review_provenance"], "text_hash": "wrong"}}
        with self.assertRaisesRegex(ValueError, "text hash mismatch"):
            rhetoric.merge_review_batch([broken], [])

    def test_review_batch_is_unique_stratified_and_skips_already_reviewed(self) -> None:
        candidates = []
        for number, source in enumerate(("telegram_channel", "pikabu", "telegram_channel", "pikabu")):
            candidates.append({
                "candidate_id": f"cand:{number}",
                "candidate_priority": 20 - number,
                "source": source,
                "dominant_job": "education" if number % 2 == 0 else "personal",
                "family_hints_auto": ["hook"],
                "is_exact_fragment_duplicate": number == 3,
            })
        reviewed = [{"review_provenance": {"candidate_id": "cand:0"}}]

        batch = rhetoric.select_review_batch(
            candidates, reviewed, family="hook", limit=4,
            sources={"telegram_channel", "pikabu"},
        )

        self.assertEqual({row["candidate_id"] for row in batch}, {"cand:1", "cand:2"})

    def test_review_decision_promotes_text_from_private_candidate_not_safe_config(self) -> None:
        text = "Так, стоп… Я же сам нутрициолог!"
        candidate = {
            "candidate_id": "cand:1", "text": text, "text_hash": rhetoric.text_hash(text),
            "context_before": "", "context_after": "Есть нюанс.",
            "catalog_id": "telegram:1", "source": "telegram_channel", "source_url": None,
            "cluster_id": "telegram:1", "related_versions": [], "dominant_job": "education",
            "composition_map": ["reframe"], "surface_context": "telegram_channel",
            "era": "current_2025_plus", "tone_dials": {}, "authorship": "own_published",
            "media_dependency": "none_recorded", "media_note": None, "media_hypothesis": None,
            "performance_signals": {},
        }
        decision = {
            "candidate_id": "cand:1", "decision": "accept", "family": "reframe_and_turn",
            "subtype": "self_reveal", "function": "Сменить роль автора.",
            "mechanism": "Применить критику к себе.", "works_when": [], "avoid_when": [],
            "reuse_instruction": "Повторять механику.",
        }

        library, ledger = rhetoric.promote_review_decisions(
            [candidate], [decision], [], [], reviewed_at="2026-08-26T00:00:00+00:00"
        )

        self.assertEqual(library[0]["text"], text)
        self.assertEqual(library[0]["review_provenance"]["candidate_id"], "cand:1")
        self.assertEqual(ledger[0]["decision"], "accept")

    def test_default_search_excludes_candidates_but_can_request_them(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "voice.sqlite"
            candidate = {
                "fragment_id": "frag:1",
                "catalog_id": "telegram:1",
                "source": "telegram_channel",
                "source_url": None,
                "fragment_kind": "hook_or_opening",
                "text": "Кортизол снова во всём виноват.",
                "dominant_job": "education",
                "composition_recipe": "provocation",
            }
            reviewed = {
                "entry_id": "rhet:1",
                "catalog_id": "telegram:2",
                "source": "telegram_channel",
                "source_url": None,
                "text": "Кортизол снова во всём виноват.",
                "family": "hook",
                "subtype": "provocation",
                "function": "Открыть конфликт.",
                "dominant_job": "education",
                "surface_context": "telegram_channel",
                "works_when": [],
                "avoid_when": [],
                "reuse_instruction": "Не копировать.",
            }
            materialize.build_index(index, [], [], [candidate], [], [reviewed])

            default = prepare.search_index(index, "кортизол", kind_filter="all")["results"]
            candidates = prepare.search_index(index, "кортизол", kind_filter="candidate")["results"]

            self.assertEqual([row["kind"] for row in default], ["rhetoric"])
            self.assertEqual([row["kind"] for row in candidates], ["candidate"])

    def test_post_pack_carries_argument_route_and_edit_mode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            materialize.build_index(index, [], [], [], [])
            source_text = (
                "Вступление остаётся.\n\n"
                "Абзац о законе, который можно менять.\n\n"
                "Финал тоже остаётся."
            )
            task_path.write_text(json.dumps({
                "note": "Точечно исправить пост про нутрициологов",
                "edit_mode": "targeted_edit",
                "source_text": source_text,
                "target_emotion": "возмущение, затем доверие",
                "central_conflict": "псевдомедицина против честной границы",
                "argument_route": ["показать схему", "дать закон", "повернуть на себя"],
                "editable_scope": ["Абзац о законе, который можно менять."],
                "protected_text": "Остальные принятые абзацы",
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)

            contract = pack["content_contract"]
            self.assertEqual(contract["edit_mode"], "targeted_edit")
            self.assertEqual(contract["argument_route"][1], "дать закон")
            self.assertEqual(contract["protected_text"], "Остальные принятые абзацы")

            pack_path = root / "pack.json"
            draft_path = root / "draft.md"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft_path.write_text(
                "Вступление остаётся.\n\nНовый абзац о законе.\n\nФинал тоже остаётся.",
                encoding="utf-8",
            )
            valid_result = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(valid_result["status"], "pass")
            self.assertIsNone(valid_result["inline_binding_review_required_once"])
            draft_path.write_text(
                "Изменённое вступление.\n\nНовый абзац о законе.\n\nФинал тоже остаётся.",
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

    def test_structure_only_pack_skips_voice_retrieval_and_routes_article_format(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            exemplar = {
                "exemplar_id": "ex:1", "catalog_id": "telegram:1",
                "source": "telegram_channel", "source_url": None,
                "headline": "Эталон", "text": "Этот текст не должен попасть в пакет.",
                "dominant_job": "education", "composition_recipe": "reframe",
                "surface_context": "telegram_channel", "media_dependency": "none_recorded",
            }
            materialize.build_index(index, [], [exemplar], [], [])
            task_path.write_text(json.dumps({
                "note": "Только структурировать статью, не меняя ни буквы",
                "source_text": (
                    "Первый абзац со [ссылкой](https://example.com).\n\n"
                    "Второй абзац!\n\n![Фото](https://example.com/photo.jpg)"
                ),
                "edit_mode": "structure_only",
                "surface_context": "masterclass_material",
                "course_context": whole_day_context(),
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)

            self.assertEqual(pack["content_contract"]["edit_mode"], "structure_only")
            self.assertEqual(pack["content_contract"]["format_profile"], "article")
            self.assertTrue(all(not rows for rows in pack["retrieval"].values()))
            self.assertNotIn("article_standard", pack["runtime_sources"])
            self.assertNotIn("course_structure", pack["runtime_sources"])
            self.assertNotIn("course_visual", pack["runtime_sources"])

            task_path.write_text(json.dumps({
                "note": "Перенести legacy HTML со слайдером",
                "surface_context": "course_material",
                "legacy_article_migration": True,
                "article_components": ["slider"],
                "course_context": whole_day_context(),
            }, ensure_ascii=False), encoding="utf-8")
            migration = prepare.build_pack(task_path, index)
            self.assertIn("article_standard", migration["runtime_sources"])
            self.assertIn("component_router", migration["runtime_sources"])
            self.assertNotIn("writer_contract", pack["runtime_sources"])
            self.assertIn("editing_modes", pack["runtime_sources"])
            self.assertEqual(pack["review_policy"]["policy_id"], "protected-edit-v1")

            pack_path = root / "pack.json"
            draft_path = root / "draft.md"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft_path.write_text(
                "## Первый абзац со [ссылкой](https://example.com).\n\n"
                "**Второй абзац!**\n\n![Фото](https://example.com/photo.jpg)",
                encoding="utf-8",
            )
            valid_result = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(valid_result["status"], "pass")
            self.assertIsNone(valid_result["inline_binding_review_required_once"])
            draft_path.write_text(
                "## первый абзац со [ссылкой](https://example.com).\n\n"
                "**Второй абзац!**\n\n![Фото](https://example.com/photo.jpg)",
                encoding="utf-8",
            )
            failed = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(failed["status"], "needs_fix")
            self.assertTrue(failed["protected_layer_errors"])
            draft_path.write_text(
                "## Первый абзац со [ссылкой](https://changed.example.com).\n\n"
                "**Второй абзац!**\n\n![Фото](https://example.com/photo.jpg)",
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")
            draft_path.write_text(
                "## Первый абзац со [ссылкой](https://example.com).\n\n"
                "**Второйабзац!**\n\n![Фото](https://example.com/photo.jpg)",
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

    def test_text_only_mode_preserves_structure_contract(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            materialize.build_index(index, [], [], [], [])
            task_path.write_text(json.dumps({
                "note": "Отредактировать только формулировки",
                "source_text": (
                    "## Старый заголовок\n\n"
                    "Абзац с **важной мыслью**, _нюансом_ и [ссылкой](https://example.com).\n\n"
                    "- Первый пункт\n- Второй пункт"
                ),
                "edit_mode": "text_only",
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)

            self.assertEqual(pack["content_contract"]["edit_mode"], "text_only")
            self.assertIn("editing_modes", pack["runtime_sources"])
            self.assertNotIn("writer_contract", pack["runtime_sources"])
            self.assertNotIn("article_standard", pack["runtime_sources"])
            self.assertTrue(all(not rows for rows in pack["retrieval"].values()))

            pack_path = root / "pack.json"
            draft_path = root / "draft.md"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft_path.write_text(
                "## Новый заголовок\n\n"
                "Другой абзац с **точной формулировкой**, _другим нюансом_ и [ссылкой](https://example.com).\n\n"
                "- Новый первый пункт\n- Новый второй пункт",
                encoding="utf-8",
            )
            valid_result = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(valid_result["status"], "manual_review_required")
            self.assertIsNotNone(valid_result["inline_binding_review_required_once"])
            draft_path.write_text(
                "## Новый заголовок\n\n"
                "Другой абзац без выделения, курсива и ссылки.\n\n"
                "- Новый первый пункт\n- Новый второй пункт",
                encoding="utf-8",
            )
            failed = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(failed["status"], "needs_fix")
            self.assertTrue(failed["protected_layer_errors"])
            draft_path.write_text(
                "## Новый заголовок\n\n"
                "**Другой абзац** с точной формулировкой, _другим нюансом_ и [ссылкой](https://example.com).\n\n"
                "- Новый первый пункт\n- Новый второй пункт",
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")
            draft_path.write_text(
                "## Новый заголовок\n\n"
                "Другой очень длинный абзац с полностью новой подводкой и точной **формулировкой**, _другим нюансом_ и [ссылкой](https://example.com).\n\n"
                "- Новый первый пункт\n- Новый второй пункт",
                encoding="utf-8",
            )
            moved_result = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(moved_result["status"], "manual_review_required")
            self.assertIsNotNone(moved_result["inline_binding_review_required_once"])

    def test_general_course_article_uses_article_rules_without_full_shell(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            materialize.build_index(index, [], [], [], [])
            task_path.write_text(json.dumps({
                "note": "Новый материал другого курса",
                "surface_context": "course_material",
                "course_context": whole_day_context(),
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)

            self.assertEqual(pack["content_contract"]["format_profile"], "article")
            self.assertNotIn("article_standard", pack["runtime_sources"])
            self.assertNotIn("course_structure", pack["runtime_sources"])
            self.assertNotIn("course_visual", pack["runtime_sources"])

    def test_full_masterclass_course_requires_outline_and_routes_course_structure(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            materialize.build_index(index, [], [], [], [])
            task_path.write_text(json.dumps({
                "note": "Написать курс по заданной программе",
                "surface_context": "masterclass_course",
                "course_outline": [
                    {"day": 1, "materials": ["Введение", "Задание"]},
                    {"day": 2, "materials": ["Разбор питания"]},
                ],
                "course_continuity": [{
                    "idea": "Осознанный выбор",
                    "route": "Вводится во введении и применяется в разборе питания.",
                }],
                "retrieval_depth": "deep",
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)

            self.assertEqual(pack["content_contract"]["format_profile"], "course")
            self.assertEqual(pack["content_contract"]["retrieval_depth"], "deep")
            self.assertNotIn("article_standard", pack["runtime_sources"])
            self.assertIn("course_structure", pack["runtime_sources"])
            self.assertNotIn("course_visual", pack["runtime_sources"])
            self.assertIn("complete course package", pack["instructions"][0])

            task_path.write_text(json.dumps({
                "note": "Написать курс без программы",
                "surface_context": "masterclass_course",
                "course_continuity": [{
                    "idea": "Осознанный выбор",
                    "route": "Вводится во введении и применяется в разборе питания.",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "course_outline is required"):
                prepare.build_pack(task_path, index)

            task_path.write_text(json.dumps({
                "note": "Написать полный новый курс",
                "surface_context": "course",
                "product": "new_course",
                "course_outline": [{"day": 1, "materials": ["Введение"]}],
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "course_structure_source is required"):
                prepare.build_pack(task_path, index)
            task_path.write_text(json.dumps({
                "note": "Написать курс с поломанной программой",
                "surface_context": "course",
                "product": "new_course",
                "course_outline": "День 1: Введение",
                "course_structure_source": "docs/example-course-structure.md",
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must contain days"):
                prepare.build_pack(task_path, index)
            malformed_outlines = [
                ["не объект"],
                [{"materials": ["Введение"]}],
                [{"day": 1}],
                [{"day": 1, "materials": []}],
                [{"day": 1, "materials": [42]}],
                [{"day": 1, "materials": ["   "]}],
            ]
            for malformed_outline in malformed_outlines:
                with self.subTest(malformed_outline=malformed_outline):
                    task_path.write_text(json.dumps({
                        "note": "Написать курс с неполной программой",
                        "surface_context": "course",
                        "product": "new_course",
                        "course_outline": malformed_outline,
                        "course_structure_source": "docs/example-course-structure.md",
                    }, ensure_ascii=False), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "must contain days"):
                        prepare.build_pack(task_path, index)

    def test_rewrite_requires_goal_preserves_links_and_declares_review_layers(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            pack_path = root / "pack.json"
            draft_path = root / "draft.md"
            materialize.build_index(index, [], [], [], [])
            source = "## Старый заголовок\n\nПолный исходный текст со [ссылкой](https://example.com)."

            task_path.write_text(json.dumps({
                "note": "Сократить без переписывания с нуля",
                "source_text": source,
                "edit_mode": "rewrite",
                "rewrite_goal": "Сократить повторяющиеся объяснения",
                "comparison_texts": ["В другом материале этот факт уже раскрыт."],
                "product": "masterclass",
            }, ensure_ascii=False), encoding="utf-8")
            pack = prepare.build_pack(task_path, index)
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(pack["content_contract"]["rewrite_goal"], "Сократить повторяющиеся объяснения")
            self.assertEqual(pack["review_policy"]["policy_id"], "writer-three-layer-v1")
            self.assertEqual(
                pack["runtime_sources"]["product_fact_router"],
                "content/author-voice/product-fact-router.md",
            )
            self.assertEqual(
                pack["runtime_sources"]["authoring_skill"],
                "content/author-voice/skill/edabalans-writer/SKILL.md",
            )

            draft_path.write_text(
                "## Новый заголовок\n\nСокращённый текст со [ссылкой](https://example.com).",
                encoding="utf-8",
            )
            result = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(result["status"], "manual_review_required")
            self.assertEqual(
                result["rewrite_continuity_review_required_once"]["goal"],
                "Сократить повторяющиеся объяснения",
            )

            draft_path.write_text(
                "## Новый заголовок\n\nСокращённый текст со [ссылкой](https://other.example).",
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

    def test_rewrite_requires_source_text_and_goal(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            materialize.build_index(index, [], [], [], [])

            task_path.write_text(json.dumps({
                "note": "Рерайт",
                "edit_mode": "rewrite",
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source_text is required"):
                prepare.build_pack(task_path, index)

            task_path.write_text(json.dumps({
                "note": "Рерайт",
                "edit_mode": "rewrite",
                "source_text": "Исходник",
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rewrite_goal is required"):
                prepare.build_pack(task_path, index)

    def test_rewrite_protects_unquoted_html_link_and_media_targets(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            pack_path = root / "pack.json"
            draft_path = root / "draft.html"
            materialize.build_index(index, [], [], [], [])
            source = (
                '<p><a href=https://one.example>Текст</a></p>'
                '<img src=/one.jpg>'
            )
            task_path.write_text(json.dumps({
                "note": "Сократить HTML, сохранив ссылки",
                "edit_mode": "rewrite",
                "source_text": source,
                "rewrite_goal": "Сократить текст",
            }, ensure_ascii=False), encoding="utf-8")
            pack = prepare.build_pack(task_path, index)
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

            draft_path.write_text(
                '<p><a href=https://two.example>Короче</a></p><img src=/two.jpg>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

    def test_protected_edit_modes_cover_html_links_media_and_structure(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            pack_path = root / "pack.json"
            draft_path = root / "draft.html"
            materialize.build_index(index, [], [], [], [])
            source = (
                '<h2>Заголовок</h2><p class="callout">Это <strong>важная мысль</strong> со '
                '<a href="https://example.com">ссылкой</a>.</p>'
                '<figure><img src="https://example.com/image.jpg"></figure>'
                '<p>Финал.</p>'
            )

            task_path.write_text(json.dumps({
                "note": "Только оформить HTML",
                "source_text": source,
                "edit_mode": "structure_only",
            }, ensure_ascii=False), encoding="utf-8")
            pack = prepare.build_pack(task_path, index)
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft_path.write_text(
                '<h2><strong>Заголовок</strong></h2><p>Это важная мысль со '
                '<a href="https://example.com">ссылкой</a>.</p>'
                '<figure><img src="https://example.com/image.jpg"></figure>'
                '<p>Финал.</p>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "pass")
            draft_path.write_text(source.replace("image.jpg", "other.jpg"), encoding="utf-8")
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")
            draft_path.write_text(
                '<h2>Заголовок</h2><p class="callout">Это '
                '<a href="https://example.com">важная</a> мысль со ссылкой.</p>'
                '<figure><img src="https://example.com/image.jpg"></figure>'
                '<p>Финал.</p>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")
            draft_path.write_text(
                '<h2>Заголовок</h2><p class="callout">Это <strong>важная мысль</strong> со '
                '<a href="https://example.com">ссылкой</a>.</p>'
                '<p>Финал.</p><figure><img src="https://example.com/image.jpg"></figure>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

            task_path.write_text(json.dumps({
                "note": "Изменить только слова HTML",
                "source_text": source,
                "edit_mode": "text_only",
            }, ensure_ascii=False), encoding="utf-8")
            pack = prepare.build_pack(task_path, index)
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            draft_path.write_text(
                '<h2>Новый заголовок</h2><p class="callout">Здесь <strong>другая формулировка</strong> и '
                '<a href="https://example.com">переход</a>.</p>'
                '<figure><img src="https://example.com/image.jpg"></figure>'
                '<p>Другой финал.</p>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "manual_review_required")
            draft_path.write_text(
                '<h2>Новый заголовок</h2><p class="callout"><strong>Здесь другая</strong> формулировка и '
                '<a href="https://example.com">переход</a>.</p>'
                '<figure><img src="https://example.com/image.jpg"></figure>'
                '<p>Другой финал.</p>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")
            draft_path.write_text(
                '<h2>Новый заголовок</h2><p class="plain">Здесь <strong>другая формулировка</strong> и '
                '<a href="https://example.com">переход</a>.</p>'
                '<figure><img src="https://example.com/image.jpg"></figure>'
                '<p>Другой финал.</p>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

    def test_structure_only_protects_embedded_video_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            pack_path = root / "pack.json"
            draft_path = root / "draft.html"
            materialize.build_index(index, [], [], [], [])
            source = (
                '<p>До.</p><iframe src="https://video.example/x"></iframe>'
                '<audio src="https://audio.example/x.mp3"></audio><p>После.</p>'
            )
            task_path.write_text(json.dumps({
                "note": "Только оформить материал с медиа",
                "source_text": source,
                "edit_mode": "structure_only",
            }, ensure_ascii=False), encoding="utf-8")
            pack = prepare.build_pack(task_path, index)
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

            draft_path.write_text(source.replace("<p>До.</p>", "<p><strong>До.</strong></p>"), encoding="utf-8")
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "pass")
            draft_path.write_text(source.replace('<iframe src="https://video.example/x"></iframe>', ""), encoding="utf-8")
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")
            draft_path.write_text(
                '<p>До.</p><audio src="https://audio.example/x.mp3"></audio>'
                '<iframe src="https://video.example/x"></iframe><p>После.</p>',
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

    def test_sales_cta_pack_routes_editorial_linking(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            materialize.build_index(index, [], [], [], [])
            task_path.write_text(json.dumps({
                "note": "Продажный пост с переходом в Мастер-класс",
                "surface_context": "telegram_channel",
                "job": "sales",
                "product": "masterclass",
                "cta": {"required_phrase": "Худеть"},
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)

            self.assertEqual(
                pack["runtime_sources"]["editorial_linking"],
                "content/author-voice/editorial-linking-v1.md",
            )

    def test_edit_only_modes_require_source_text(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            materialize.build_index(index, [], [], [], [])
            for edit_mode in ("targeted_edit", "proofread", "structure_only", "text_only"):
                with self.subTest(edit_mode=edit_mode):
                    task_path.write_text(json.dumps({
                        "note": "Редактура",
                        "edit_mode": edit_mode,
                    }, ensure_ascii=False), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "source_text is required"):
                        prepare.build_pack(task_path, index)
            task_path.write_text(json.dumps({
                "note": "Точечная редактура без границы",
                "edit_mode": "targeted_edit",
                "source_text": "Исходный текст.",
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "editable_scope is required"):
                prepare.build_pack(task_path, index)

    def test_proofread_preserves_structure_and_requires_change_review(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            pack_path = root / "pack.json"
            draft_path = root / "draft.md"
            materialize.build_index(index, [], [], [], [])
            source = (
                "## Заголовок\n\n"
                "Я тоже прозодил эти курсы, но толку там было немного.\n\n"
                "**Вывод остаётся на месте.**"
            )
            task_path.write_text(json.dumps({
                "note": "Исправить только ошибки",
                "edit_mode": "proofread",
                "source_text": source,
            }, ensure_ascii=False), encoding="utf-8")
            pack = prepare.build_pack(task_path, index)
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

            draft_path.write_text(
                source.replace("прозодил", "проходил"),
                encoding="utf-8",
            )
            result = draft_validator.validate(pack_path, draft_path)
            self.assertEqual(result["status"], "manual_review_required")
            proofread_review = result["proofread_change_review_required_once"]
            self.assertIn("spelling, punctuation", proofread_review["instruction"])
            self.assertGreater(proofread_review["similarity"], 0.9)

            draft_path.write_text(
                "## Другой заголовок\n\nЯ полностью переписал весь смысл этого материала.\n\nФинал исчез.",
                encoding="utf-8",
            )
            self.assertEqual(draft_validator.validate(pack_path, draft_path)["status"], "needs_fix")

    def test_post_pack_deduplicates_platform_variants_and_adds_topic_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            task_path = root / "task.json"
            common = {
                "source_url": None, "headline": "Сколько времени нужно на похудение",
                "text": "Скорость похудения и адекватные сроки. " * 20,
                "dominant_job": "education", "composition_recipe": "calculation",
                "strength": "owner_named_core", "exact_cluster_ids": [],
            }
            pikabu = {
                **common, "exemplar_id": "ex:pika", "catalog_id": "pikabu:1",
                "source": "pikabu", "surface_context": "pikabu_article",
                "related_versions": ["telegram:1"],
            }
            telegram = {
                **common, "exemplar_id": "ex:tg", "catalog_id": "telegram:1",
                "source": "telegram_channel", "surface_context": "telegram_channel",
                "related_versions": ["pikabu:1"],
            }
            corpus_row = {
                "corpus_id": "corpus:telegram:other", "catalog_id": "telegram:other",
                "source": "telegram_channel", "source_url": None,
                "headline": "Похудеть быстро", "text": "Скорость похудения в другом старом посте.",
                "dominant_job": "education", "surface_context": "telegram_channel",
                "related_versions": [], "exact_cluster_ids": ["telegram:other"],
                "corpus_usability": "author_text",
            }
            technical_row = {
                **corpus_row,
                "corpus_id": "corpus:leadteh:technical",
                "catalog_id": "leadteh:technical",
                "source": "bot_constructor",
                "headline": "Скорость похудения {{round($speed)}}",
                "text": "Скорость похудения {{round($speed)}} " * 20,
                "exact_cluster_ids": ["leadteh:technical"],
                "corpus_usability": "technical_template",
            }
            correction_row = {
                "correction_id": "correction:speed", "title": "Скорость похудения",
                "full_case": "Полная цепочка исправлений про скорость похудения. " * 30,
                "candidate_rules": ["expectation_reframe"],
            }
            materialize.build_index(
                index, [], [pikabu, telegram], [], [correction_row], [],
                [technical_row, corpus_row],
            )
            task_path.write_text(json.dumps({
                "note": "Скорость похудения",
                "job": "education",
                "surface_context": "telegram_channel",
            }, ensure_ascii=False), encoding="utf-8")

            pack = prepare.build_pack(task_path, index)

            self.assertEqual(len(pack["retrieval"]["exemplars"]), 1)
            self.assertEqual(pack["retrieval"]["exemplars"][0]["catalog_id"], "telegram:1")
            self.assertIn("full_text", pack["retrieval"]["exemplars"][0])
            self.assertGreater(
                len(pack["retrieval"]["corrections"][0]["full_case"]),
                1000,
            )
            self.assertEqual(
                [row["catalog_id"] for row in pack["retrieval"]["topic_history"]],
                ["telegram:other"],
            )

    def test_corpus_usability_marks_bot_placeholders_as_technical(self) -> None:
        self.assertEqual(
            materialize.corpus_usability("170 — {{round($170_EE_60)}}"),
            "technical_template",
        )
        self.assertEqual(
            materialize.corpus_usability("Обычный авторский текст про скорость похудения."),
            "author_text",
        )
        self.assertEqual(
            materialize.corpus_usability("На эксперимент он потратил $400 млн."),
            "author_text",
        )
        self.assertEqual(
            materialize.corpus_usability("Техническое значение $speed_value"),
            "technical_template",
        )

    def test_correction_preserves_owner_final_and_review_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "voice.sqlite"
            memory = root / "corrections.jsonl"
            payload = root / "input.json"
            materialize.build_index(index, [], [], [], [])
            payload.write_text(json.dumps({
                "request": "Написать пост.",
                "assistant_draft": "Сухой первый текст.",
                "assistant_versions": ["Вторая версия."],
                "owner_feedback": "Нет хука.",
                "owner_feedback_rounds": ["Сначала накинуть, потом закон."],
                "owner_revision": "Авторский черновик.",
                "owner_final": "Финальная версия.",
                "source_artifacts": [{"path": "D:/source.txt", "sha256": "abc123"}],
                "before_after_examples": [{"before": "По мнению Сергея", "after": "Я считаю"}],
                "positive_examples": ["Я считаю этот критерий рабочим."],
                "negative_examples": ["Автор предлагает использовать критерий."],
                "application_examples": ["Сначала резкий тезис, потом границы и действие."],
            }, ensure_ascii=False), encoding="utf-8")

            correction.record(payload, memory, index)

            saved = json.loads(memory.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(saved["owner_final"], "Финальная версия.")
            self.assertIn("Вторая версия.", saved["full_case"])
            self.assertIn("Сначала накинуть", saved["full_case"])
            self.assertEqual(saved["schema_version"], "1.3")
            self.assertEqual(saved["assistant_versions"], ["Сухой первый текст.", "Вторая версия."])
            self.assertEqual(saved["owner_feedback_rounds"], ["Нет хука.", "Сначала накинуть, потом закон."])
            self.assertEqual(saved["owner_revision_rounds"], ["Авторский черновик."])
            self.assertEqual(saved["owner_final_versions"], ["Финальная версия."])
            self.assertEqual(saved["source_artifacts"][0]["sha256"], "abc123")
            self.assertIn("По мнению Сергея", saved["full_case"])
            self.assertIn("Я считаю этот критерий", saved["full_case"])
            self.assertIn("Автор предлагает", saved["full_case"])
            self.assertIn("резкий тезис", saved["full_case"])
            with closing(sqlite3.connect(index)) as db:
                searchable = db.execute(
                    "SELECT count(*) FROM voice_fts "
                    "WHERE voice_fts MATCH ? AND kind = 'correction'",
                    ("предлагает",),
                ).fetchone()[0]
            self.assertEqual(searchable, 1)

            saved["legacy_note"] = "Не потерять старое наследие 8472."
            saved["schema_version"] = "1.1"
            saved["owner_final_versions"] = [None, *saved["owner_final_versions"]]
            saved["full_case"] += "\n\nУникальный фрагмент прежней полной цепочки 9631."
            memory.write_text(
                json.dumps(saved, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with closing(sqlite3.connect(index)) as db:
                db.execute(
                    "INSERT INTO corrections VALUES (?, ?)",
                    ("correction:orphan", json.dumps({"correction_id": "correction:orphan"})),
                )
                db.execute(
                    "INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)",
                    ("correction", "correction:orphan", "", "Сирота", "Осиротевшая запись 7419", ""),
                )
                db.execute(
                    "INSERT INTO voice_fts VALUES (?, ?, ?, ?, ?, ?)",
                    ("correction", "correction:fts-only", "", "Сирота FTS", "Осиротевшая FTS-запись 8520", ""),
                )
                db.commit()
            payload.write_text(json.dumps({
                "correction_id": saved["correction_id"],
                "request": "Усилить тот же пост.",
                "assistant_draft": "Новый, но всё ещё сухой текст.",
                "owner_feedback": "Теперь потерялись границы.",
                "owner_revision": "Вторая авторская редакция.",
                "owner_final": "Второй подтверждённый финал.",
                "application_examples": ["Новый пример применения."],
            }, ensure_ascii=False), encoding="utf-8")

            correction.record(payload, memory, index)

            enriched = json.loads(memory.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(enriched["request"], "Усилить тот же пост.")
            self.assertEqual(enriched["request_versions"], ["Написать пост.", "Усилить тот же пост."])
            self.assertEqual(enriched["assistant_draft"], "Новый, но всё ещё сухой текст.")
            self.assertEqual(enriched["owner_feedback"], "Теперь потерялись границы.")
            self.assertEqual(enriched["owner_revision"], "Вторая авторская редакция.")
            self.assertEqual(enriched["legacy_note"], "Не потерять старое наследие 8472.")
            self.assertEqual(enriched["source_artifacts"][0]["sha256"], "abc123")
            self.assertEqual(
                enriched["before_after_examples"],
                [{"before": "По мнению Сергея", "after": "Я считаю"}],
            )
            self.assertIn("Я считаю этот критерий рабочим.", enriched["positive_examples"])
            self.assertIn("Автор предлагает использовать критерий.", enriched["negative_examples"])
            self.assertIn(
                "Сначала резкий тезис, потом границы и действие.",
                enriched["application_examples"],
            )
            self.assertIn("Новый пример применения.", enriched["application_examples"])
            self.assertIn("Сухой первый текст.", enriched["assistant_versions"])
            self.assertIn("Написать пост.", enriched["request_versions"])
            self.assertIn("Нет хука.", enriched["owner_feedback_rounds"])
            self.assertIn("Авторский черновик.", enriched["owner_revision_rounds"])
            self.assertIn("Финальная версия.", enriched["owner_final_versions"])
            self.assertEqual(enriched["owner_final"], "Второй подтверждённый финал.")
            self.assertEqual(
                enriched["assistant_versions"],
                ["Сухой первый текст.", "Вторая версия.", "Новый, но всё ещё сухой текст."],
            )
            self.assertEqual(
                enriched["owner_feedback_rounds"],
                ["Нет хука.", "Сначала накинуть, потом закон.", "Теперь потерялись границы."],
            )
            self.assertEqual(
                enriched["owner_revision_rounds"],
                ["Авторский черновик.", "Вторая авторская редакция."],
            )
            self.assertEqual(
                enriched["owner_final_versions"],
                ["Финальная версия.", "Второй подтверждённый финал."],
            )
            self.assertNotIn(None, enriched["owner_final_versions"])
            self.assertIn("Не потерять старое наследие 8472", enriched["full_case"])
            self.assertIn("Уникальный фрагмент прежней полной цепочки 9631", enriched["full_case"])
            self.assertIn("Усилить тот же пост.", enriched["full_case"])
            self.assertIn("Сухой первый текст.", enriched["full_case"])
            self.assertIn("Новый, но всё ещё сухой текст.", enriched["full_case"])
            self.assertIn("Теперь потерялись границы.", enriched["full_case"])
            self.assertIn("Вторая авторская редакция.", enriched["full_case"])
            self.assertIn("Второй подтверждённый финал.", enriched["full_case"])
            with closing(sqlite3.connect(index)) as db:
                legacy_searchable = db.execute(
                    "SELECT count(*) FROM voice_fts "
                    "WHERE voice_fts MATCH ? AND kind = 'correction'",
                    ("8472",),
                ).fetchone()[0]
            self.assertEqual(legacy_searchable, 1)
            with closing(sqlite3.connect(index)) as db:
                history_searchable = db.execute(
                    "SELECT count(*) FROM voice_fts "
                    "WHERE voice_fts MATCH ? AND kind = 'correction'",
                    ("9631",),
                ).fetchone()[0]
                orphan_rows = db.execute(
                    "SELECT count(*) FROM corrections WHERE correction_id = ?",
                    ("correction:orphan",),
                ).fetchone()[0]
                orphan_fts = db.execute(
                    "SELECT count(*) FROM voice_fts WHERE kind = 'correction' AND item_id = ?",
                    ("correction:orphan",),
                ).fetchone()[0]
                fts_only_orphan = db.execute(
                    "SELECT count(*) FROM voice_fts WHERE kind = 'correction' AND item_id = ?",
                    ("correction:fts-only",),
                ).fetchone()[0]
                current_round_searchable = db.execute(
                    "SELECT count(*) FROM voice_fts "
                    "WHERE voice_fts MATCH ? AND kind = 'correction'",
                    ("потерялись",),
                ).fetchone()[0]
                current_request_searchable = db.execute(
                    "SELECT count(*) FROM voice_fts "
                    "WHERE voice_fts MATCH ? AND kind = 'correction'",
                    ("усилить",),
                ).fetchone()[0]
            self.assertEqual(history_searchable, 1)
            self.assertEqual(orphan_rows, 0)
            self.assertEqual(orphan_fts, 0)
            self.assertEqual(fts_only_orphan, 0)
            self.assertEqual(current_round_searchable, 1)
            self.assertEqual(current_request_searchable, 1)

            wrong_memory = root / "wrong-memory.jsonl"
            with self.assertRaisesRegex(ValueError, "missing or empty correction memory"):
                correction.record(payload, wrong_memory, index)
            self.assertFalse(wrong_memory.exists())
            with closing(sqlite3.connect(index)) as db:
                self.assertGreater(db.execute("SELECT COUNT(*) FROM corrections").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
