from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import module_inventory as inventory


PYTHON_SOURCE = '''
from fastapi import APIRouter
from sqlalchemy.orm import DeclarativeBase
from alembic import op

router = APIRouter(prefix="/api")

class User(DeclarativeBase):
    __tablename__ = "users"

    def label(self):
        return "user"

@router.get("/users")
def list_users():
    return []

def upgrade():
    op.create_table("events")
'''


class ModuleInventoryTests(unittest.TestCase):
    def test_python_ast_extracts_symbols_routes_and_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.py"
            path.write_text(PYTHON_SOURCE, encoding="utf-8")

            found = inventory.extract_python(path, "sample.py")

        self.assertIn(
            ("class", "User"),
            {(item["kind"], item["qualname"]) for item in found.symbols},
        )
        self.assertIn(
            ("method", "User.label"),
            {(item["kind"], item["qualname"]) for item in found.symbols},
        )
        self.assertEqual(
            [{"method": "GET", "path": "/api/users"}],
            [{"method": item["method"], "path": item["path"]} for item in found.routes],
        )
        self.assertEqual(
            {("events", "migration"), ("users", "orm")},
            {(item["name"], item["source"]) for item in found.tables},
        )

    def test_javascript_extractor_is_conservative(self) -> None:
        source = """
        function declared() {}
        const arrow = () => true;
        let asyncArrow = async value => value;
        document.addEventListener('click', () => null);
        """
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.js"
            path.write_text(source, encoding="utf-8")
            found = inventory.extract_javascript(path, "sample.js")

        self.assertEqual(
            ["declared", "arrow", "asyncArrow"],
            [item["name"] for item in found.symbols],
        )

    def test_owner_uses_more_specific_rule_and_rejects_equal_overlap(self) -> None:
        rules = [("docs/**", "docs"), ("docs/cards/**", "cards")]
        self.assertEqual(
            "cards",
            inventory.resolve_owner("docs/cards/a.md", rules, object_kind="file"),
        )
        with self.assertRaisesRegex(inventory.InventoryError, "overlapping"):
            inventory.resolve_owner(
                "same/a.py",
                [("same/*.py", "one"), ("same/*.py", "two")],
                object_kind="file",
            )
        with self.assertRaisesRegex(inventory.InventoryError, "no owner"):
            inventory.resolve_owner("orphan.py", rules, object_kind="file")

    def test_route_function_inherits_route_module_in_shared_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init")
            (repo / "docs/cards").mkdir(parents=True)
            (repo / "src").mkdir()
            card = (
                "---\ntitle: Module\nsummary: Summary\ndocument_status: current\n"
                "implementation_status: implemented\n---\n# Module\n"
            )
            (repo / "docs/cards/root.md").write_text(card, encoding="utf-8")
            (repo / "docs/cards/api.md").write_text(card, encoding="utf-8")
            (repo / "src/app.py").write_text(PYTHON_SOURCE, encoding="utf-8")
            self._git(repo, "add", ".")
            registry = {
                "modules": [
                    {
                        "id": "root",
                        "card": "docs/cards/root.md",
                        "owns_files": ["src/**"],
                        "owns_tables": ["users", "events"],
                    },
                    {
                        "id": "api",
                        "card": "docs/cards/api.md",
                        "owns_routes": ["*/api/*"],
                    },
                ],
                "derived_outputs": [],
                "derived_output_records": [],
            }

            built, errors = inventory.build_inventory(repo, registry)

        self.assertEqual([], errors)
        route = next(item for item in built["routes"] if item["path"] == "/api/users")
        symbol = next(item for item in built["symbols"] if item["qualname"] == "list_users")
        self.assertEqual("api", route["module_id"])
        self.assertEqual("api", symbol["module_id"])

    def test_plan_provenance_is_required_only_for_active_plans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "PLAN.md"
            path.write_text(
                "---\ndocument_status: planned\nmodule_id: platform\n---\n# Plan\n",
                encoding="utf-8",
            )
            parsed, errors = inventory.parse_plan(path, "docs/plans/PLAN.md")
            self.assertIsNotNone(parsed)
            self.assertEqual(2, len(errors))

            path.write_text(
                "---\ndocument_status: archived\n---\n# Old plan\n", encoding="utf-8"
            )
            parsed, errors = inventory.parse_plan(path, "docs/plans/PLAN.md")
            self.assertIsNone(parsed)
            self.assertEqual([], errors)

    def test_card_exposes_human_boundary_and_sources_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "CARD.md"
            path.write_text(
                "---\ntitle: Card\nsummary: Summary\ndocument_status: current\n"
                "implementation_status: implemented\n---\n# Card\n\n"
                "## Функции\n\n- Делает работу\n\n## Граница\n\nНе меняет оплату.\n\n"
                "## Источники истины\n\n`data.json` и PostgreSQL.\n\n"
                "Технические файлы, routes, таблицы, migrations и программные символы не "
                "перечисляются вручную в карточке: они подставляются из generated inventory.\n",
                encoding="utf-8",
            )

            card = inventory.parse_card(path)

        self.assertEqual("Не меняет оплату.", card["boundary"])
        self.assertEqual(["`data.json` и PostgreSQL."], card["truths"])

    def test_cross_project_plan_is_not_duplicated_in_module_plans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init")
            (repo / "docs/cards").mkdir(parents=True)
            (repo / "docs/plans").mkdir()
            (repo / "docs/cards/root.md").write_text(
                "---\ntitle: Root\nsummary: Summary\ndocument_status: current\n"
                "implementation_status: implemented\n---\n# Root\n",
                encoding="utf-8",
            )
            (repo / "docs/plans/GENERAL.md").write_text(
                "---\ndocument_status: planned\ncross_project: true\n"
                "origin: owner-explicit\ndate: 2026-08-25\n---\n# General plan\n",
                encoding="utf-8",
            )
            self._git(repo, "add", ".")
            registry = {
                "modules": [{
                    "id": "root", "card": "docs/cards/root.md",
                    "owns_files": ["docs/plans/**"],
                }],
                "derived_outputs": [],
                "derived_output_records": [],
            }

            built, errors = inventory.build_inventory(repo, registry)

        self.assertEqual([], errors)
        self.assertEqual([], built["plans"])
        self.assertEqual(["docs/plans/GENERAL.md"], [p["path"] for p in built["cross_project_plans"]])

    def test_current_quick_notes_exposes_only_valid_planned_rows(self) -> None:
        text = """# Notes

Статус: `current`

| ID | Module ID | Статус | Пожелание | Дата | Origin | Источник |
|---|---|---|---|---|---|---|
| Q-001 | platform | `planned` | Сделать каталог | 2026-08-25 | owner-explicit | Решение владельца |
| Q-002 | platform | `idea` | Обсудить идею | 2026-08-25 | owner-explicit | Идея владельца |
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "QUICK_NOTES.md"
            path.write_text(text, encoding="utf-8")
            plans, errors = inventory.parse_quick_notes(path, "docs/plans/QUICK_NOTES.md")

        self.assertEqual([], errors)
        self.assertEqual(["Q-001"], [plan["row_id"] for plan in plans])
        self.assertEqual("platform", plans[0]["module_id"])

    def test_top_document_status_ignores_nested_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "DOC.md"
            path.write_text(
                "# Document\n\nСтатус: `current`\n\n## Runtime\n\nСтатус: disabled\n",
                encoding="utf-8",
            )
            self.assertEqual("current", inventory.top_document_status(path))

            path.write_text(
                "---\ndocument_status: archived\n---\n# Document\n",
                encoding="utf-8",
            )
            self.assertEqual("archived", inventory.top_document_status(path))

    def test_impact_report_lists_registered_consumers(self) -> None:
        registry = {
            "modules": [
                {
                    "id": "owner",
                    "sources": [
                        {
                            "path": "content/course",
                            "role": "runtime",
                            "shared": True,
                            "consumers": ["consumer"],
                        }
                    ],
                }
            ]
        }
        self.assertEqual(
            ["IMPACT content/course (runtime, owner=owner): review consumer"],
            inventory.impact_report(registry, ["content/course/day-1.md"]),
        )

    def test_registry_validation_rejects_status_relation_and_shared_source_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "docs").mkdir()
            (repo / "source.txt").write_text("source", encoding="utf-8")
            (repo / "docs/card.md").write_text(
                "---\ntitle: Module\nsummary: Summary\ndocument_status: unknown\n"
                "implementation_status: enabled\n---\n# Module\n",
                encoding="utf-8",
            )
            registry = {
                "modules": [
                    {
                        "id": "module",
                        "parent": "missing",
                        "card": "docs/card.md",
                        "depends_on": ["also-missing"],
                        "sources": [
                            {
                                "path": "source.txt",
                                "role": "runtime",
                                "shared": True,
                                "consumers": [],
                            }
                        ],
                    }
                ]
            }

            _, errors = inventory.validate_registry(repo, registry)

        joined = "\n".join(errors)
        self.assertIn("unknown parent", joined)
        self.assertIn("targets unknown module", joined)
        self.assertIn("invalid document_status", joined)
        self.assertIn("invalid implementation_status", joined)
        self.assertIn("needs consumers", joined)

    def test_shared_source_consumer_must_read_from_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "docs").mkdir()
            (repo / "source.txt").write_text("source", encoding="utf-8")
            card = (
                "---\ntitle: Module\nsummary: Summary\ndocument_status: current\n"
                "implementation_status: implemented\n---\n# Module\n"
            )
            (repo / "docs/owner.md").write_text(card, encoding="utf-8")
            (repo / "docs/consumer.md").write_text(card, encoding="utf-8")
            registry = {
                "modules": [
                    {
                        "id": "owner",
                        "card": "docs/owner.md",
                        "sources": [
                            {
                                "path": "source.txt",
                                "role": "rule",
                                "shared": True,
                                "consumers": ["consumer"],
                            }
                        ],
                    },
                    {"id": "consumer", "card": "docs/consumer.md"},
                ],
                "derived_output_records": [],
            }

            _, errors = inventory.validate_registry(repo, registry)

        self.assertIn("requires reads_from", "\n".join(errors))

    def test_telegram_projection_uses_explicit_registry_fields(self) -> None:
        payload = {
            "modules": [
                {
                    "id": "telegram.module",
                    "card": "docs/card.md",
                    "telegram": {
                        "code": "runtime_code",
                        "name": "Runtime name",
                        "status": "Runtime status",
                        "order": 20,
                    },
                }
            ]
        }

        projection = json.loads(inventory.render_telegram_modules(payload))

        self.assertEqual(1, projection["schema_version"])
        self.assertEqual(
            {
                "card": "docs/card.md",
                "code": "runtime_code",
                "module_id": "telegram.module",
                "name": "Runtime name",
                "order": 20,
                "status": "Runtime status",
            },
            projection["modules"][0],
        )

    def test_full_fixture_is_deterministic_and_check_detects_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init")
            self._git(repo, "config", "user.email", "test@example.com")
            self._git(repo, "config", "user.name", "Test")
            (repo / "docs/cards").mkdir(parents=True)
            (repo / "docs/generated").mkdir(parents=True)
            (repo / "src").mkdir()
            (repo / "docs/cards/root.md").write_text(
                "---\ntitle: Root\nsummary: Fixture module\ndocument_status: current\n"
                "implementation_status: implemented\n---\n# Root\n\n## Capabilities\n\n- Works\n",
                encoding="utf-8",
            )
            (repo / "src/app.py").write_text(PYTHON_SOURCE, encoding="utf-8")
            (repo / "docs/modules.toml").write_text(
                """schema_version = 1
derived_outputs = [
  { path = "docs/generated/module-inventory.json", module_id = "root" },
  { path = "docs/generated/module-map.md", module_id = "root" },
  { path = "telegram-bot/service/app/telegram-global-modules.json", module_id = "root" },
]
[[modules]]
id = "root"
card = "docs/cards/root.md"
owns_files = ["docs/modules.toml", "src/**"]
owns_routes = ["*/api/*"]
owns_tables = ["users", "events"]
""",
                encoding="utf-8",
            )
            self._git(repo, "add", ".")

            registry = inventory.load_registry(repo)
            first, errors = inventory.build_inventory(repo, registry)
            self.assertEqual([], errors)
            first_json = inventory.render_json(first)
            second, errors = inventory.build_inventory(repo, registry)
            self.assertEqual([], errors)
            self.assertEqual(first_json, inventory.render_json(second))

            self.assertEqual([], inventory.write_or_check(repo, registry, first, check=False))
            self.assertEqual([], inventory.write_or_check(repo, registry, first, check=True))
            artifact = repo / "docs/generated/module-inventory.json"
            parsed = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(1, parsed["schema_version"])
            self.assertEqual(
                {"docs/cards/root.md", "docs/modules.toml", "src/app.py"},
                {item["path"] for item in parsed["files"]},
            )
            self.assertEqual(
                [{"method": "GET", "module_id": "root", "path": "/api/users"}],
                [
                    {key: route[key] for key in ("method", "module_id", "path")}
                    for route in parsed["routes"]
                ],
            )
            self.assertEqual(
                {("events", "root"), ("users", "root")},
                {(item["name"], item["module_id"]) for item in parsed["tables"]},
            )
            self.assertTrue(parsed["symbols"])
            self.assertEqual({"root"}, {item["module_id"] for item in parsed["symbols"]})

            (repo / "scratch.py").write_text("x = 1\n", encoding="utf-8")
            _, untracked_errors = inventory.build_inventory(repo, registry)
            self.assertIn("file has no owner: scratch.py", untracked_errors)
            tracked_only, errors = inventory.build_inventory(
                repo, registry, include_untracked=False
            )
            self.assertEqual([], errors)
            self.assertNotIn("scratch.py", {item["path"] for item in tracked_only["files"]})
            self.assertEqual(0, inventory.main(["--repo", str(repo), "--tracked-only"]))

            (repo / "orphan.py").write_text("x = 1\n", encoding="utf-8")
            self._git(repo, "add", "orphan.py")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = inventory.main(["--repo", str(repo), "--tracked-only"])
            self.assertEqual(1, exit_code)
            self.assertIn("file has no owner: orphan.py", stderr.getvalue())

            artifact.write_text("{}\n", encoding="utf-8")
            self.assertIn("stale", inventory.write_or_check(repo, registry, first, check=True)[0])

    def test_cli_check_fails_for_orphan_overlap_and_invalid_relation(self) -> None:
        cases = {
            "orphan": (
                '[[modules]]\nid = "root"\ncard = "docs/cards/root.md"\n'
                'owns_files = ["src/owned.py"]\n',
                {"src/owned.py": "x = 1\n", "src/orphan.py": "x = 2\n"},
            ),
            "overlap": (
                '[[modules]]\nid = "one"\ncard = "docs/cards/one.md"\n'
                'owns_files = ["src/*.py"]\n'
                '[[modules]]\nid = "two"\ncard = "docs/cards/two.md"\n'
                'owns_files = ["src/*.py"]\n',
                {"src/app.py": "x = 1\n"},
            ),
            "relation": (
                '[[modules]]\nid = "root"\ncard = "docs/cards/root.md"\n'
                'depends_on = ["missing"]\nowns_files = ["src/**"]\n',
                {"src/app.py": "x = 1\n"},
            ),
        }
        for name, (registry_text, sources) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary)
                (repo / "docs/cards").mkdir(parents=True)
                (repo / "src").mkdir()
                module_ids = {"root"} if name != "overlap" else {"one", "two"}
                card = (
                    "---\ntitle: Module\nsummary: Summary\ndocument_status: current\n"
                    "implementation_status: implemented\n---\n# Module\n"
                )
                for module_id in module_ids:
                    (repo / f"docs/cards/{module_id}.md").write_text(card, encoding="utf-8")
                for relative_path, content in sources.items():
                    path = repo / relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                (repo / "docs/modules.toml").write_text(registry_text, encoding="utf-8")

                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    exit_code = inventory.main(["--repo", str(repo), "--check"])

                self.assertEqual(1, exit_code)
                self.assertIn("ERROR", stderr.getvalue())

    @staticmethod
    def _git(repo: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
