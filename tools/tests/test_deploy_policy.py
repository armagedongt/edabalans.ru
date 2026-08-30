from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = REPOSITORY_ROOT / "infra" / "deploy" / "classify-deploy-impact"


class DeployPolicyTests(unittest.TestCase):
    def test_deploy_bootstraps_target_policy_and_refreshes_installed_scripts(self) -> None:
        source = (REPOSITORY_ROOT / "infra/deploy/edabalans-deploy").read_text(encoding="utf-8")

        self.assertIn(
            'git show "${TARGET_SHA}:infra/deploy/classify-deploy-impact"',
            source,
        )
        self.assertIn("| bash -s --", source)
        self.assertIn("python3 tools/module_inventory.py --tracked-only", source)
        self.assertIn("if ! python3 tools/module_inventory.py --tracked-only; then", source)
        self.assertGreaterEqual(
            source.count('git checkout --quiet --force "${PREVIOUS_SHA}"'), 2
        )
        self.assertIn("/usr/local/sbin/edabalans-deploy\n", source)
        self.assertIn("/usr/local/sbin/edabalans-deploy-poll\n", source)

    def test_routine_deploy_reuses_cached_base_images(self) -> None:
        source = (REPOSITORY_ROOT / "infra/deploy/edabalans-deploy").read_text(encoding="utf-8")
        pull_pattern = r"docker compose build(?:[ \t]|\\\r?\n)*--pull"

        self.assertIn('docker compose build "${build_services[@]}"', source)
        self.assertIn('docker compose up -d --no-deps --wait --wait-timeout 180 "${runtime_services[@]}"', source)
        self.assertIn('if [[ "${compose_changed}" == "true" ]]', source)
        self.assertNotIn("docker compose build\n", source)
        self.assertIsNone(
            re.search(pull_pattern, source),
            "routine deploy must not force a Docker base-image pull",
        )
        self.assertIsNotNone(re.search(pull_pattern, "docker compose build \\\n  --pull"))

    def test_ci_builds_and_tests_only_changed_application_services(self) -> None:
        source = (REPOSITORY_ROOT / ".github/workflows/production.yml").read_text(encoding="utf-8")

        self.assertIn("id: impact", source)
        self.assertIn("bash infra/deploy/classify-deploy-impact", source)
        self.assertEqual(source.count("if: steps.impact.outputs.backend == 'true'"), 2)
        self.assertEqual(source.count("if: steps.impact.outputs.telegram == 'true'"), 2)
        self.assertIn("if: steps.impact.outputs.migration == 'true'", source)

    @unittest.skipUnless(shutil.which("bash"), "deploy classifier requires bash")
    def test_backup_impact_classification_uses_real_git_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.git(repo, "init")
            self.git(repo, "config", "user.email", "test@example.com")
            self.git(repo, "config", "user.name", "Test")
            main = repo / "telegram-bot" / "service" / "app" / "main.py"
            seed = repo / "telegram-bot" / "service" / "app" / "seed.py"
            backend = repo / "backend" / "app" / "main.py"
            migration = repo / "backend" / "migrations" / "versions" / "001.py"
            docs = repo / "docs" / "OPERATIONS.md"
            caddy = repo / "infra" / "caddy" / "Caddyfile"
            main.parent.mkdir(parents=True)
            backend.parent.mkdir(parents=True)
            migration.parent.mkdir(parents=True)
            docs.parent.mkdir(parents=True)
            caddy.parent.mkdir(parents=True)
            main.write_text(
                "def start():\n"
                "        seed_defaults(\n"
                "            session,\n"
                "        )\n",
                encoding="utf-8",
            )
            seed.write_text("DEFAULT = 1\n", encoding="utf-8")
            backend.write_text("VALUE = 1\n", encoding="utf-8")
            docs.write_text("operations\n", encoding="utf-8")
            caddy.write_text("example.com\n", encoding="utf-8")
            (repo / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            (repo / "README.md").write_text("base\n", encoding="utf-8")
            base = self.commit(repo, "base")

            (repo / "README.md").write_text("code only\n", encoding="utf-8")
            code_only = self.commit(repo, "code only")
            self.assertEqual((False, False, False, False, False, False), self.classify(repo, base, code_only))

            backend.write_text("VALUE = 2\n", encoding="utf-8")
            backend_sha = self.commit(repo, "backend")
            self.assertEqual((False, False, True, False, False, False), self.classify(repo, code_only, backend_sha))

            docs.write_text("updated operations\n", encoding="utf-8")
            docs_sha = self.commit(repo, "docs")
            self.assertEqual((False, False, True, False, False, False), self.classify(repo, backend_sha, docs_sha))

            migration.write_text("migration\n", encoding="utf-8")
            migration_sha = self.commit(repo, "migration")
            self.assertEqual((True, False, True, False, False, False), self.classify(repo, docs_sha, migration_sha))

            seed.write_text("DEFAULT = 2\n", encoding="utf-8")
            seed_sha = self.commit(repo, "seed")
            self.assertEqual((False, True, False, True, False, False), self.classify(repo, migration_sha, seed_sha))

            main.write_text(main.read_text(encoding="utf-8") + "VALUE = 1\n", encoding="utf-8")
            unrelated_main = self.commit(repo, "unrelated main")
            self.assertEqual((False, False, False, True, False, False), self.classify(repo, seed_sha, unrelated_main))

            main.write_text(
                main.read_text(encoding="utf-8").replace("            session,", "            session,\n            new_default=True,"),
                encoding="utf-8",
            )
            changed_call = self.commit(repo, "startup call")
            self.assertEqual((False, True, False, True, False, False), self.classify(repo, unrelated_main, changed_call))

            caddy.write_text("updated.example.com\n", encoding="utf-8")
            caddy_sha = self.commit(repo, "caddy")
            self.assertEqual((False, False, False, False, True, False), self.classify(repo, changed_call, caddy_sha))

            (repo / "compose.yaml").write_text("services:\n  backend: {}\n", encoding="utf-8")
            compose_sha = self.commit(repo, "compose")
            self.assertEqual((False, False, True, True, True, True), self.classify(repo, caddy_sha, compose_sha))

    def classify(self, repo: Path, previous: str, target: str) -> tuple[bool, bool, bool, bool, bool, bool]:
        result = subprocess.run(
            ["bash", str(CLASSIFIER), str(repo), previous, target],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip().split()
        self.assertEqual(6, len(result))
        return tuple(value == "true" for value in result)  # type: ignore[return-value]

    def commit(self, repo: Path, message: str) -> str:
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", message)
        return self.git(repo, "rev-parse", "HEAD").strip()

    @staticmethod
    def git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout


if __name__ == "__main__":
    unittest.main()
