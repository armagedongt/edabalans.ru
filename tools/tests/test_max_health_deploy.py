from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "Bash is required for the real deployment gate")
class MaxHealthDeploymentGateTests(unittest.TestCase):
    def run_gate(self, *, configured: str = "yes", discovery_failure: bool = False, failures: int = 0):
        source = (ROOT / "infra/deploy/edabalans-deploy").read_text(encoding="utf-8")
        start = source.index('max_configured="$(')
        end = source.index("https://edabalans.ru/apps/masterclass-course.html", start)
        gate = source[start:source.rfind("curl --fail", start, end)]
        # Shell functions replace external commands; the actual gate is unchanged.
        harness = "set -Eeuo pipefail\n" + f"""
docker() {{
    {'return 7' if discovery_failure else f'printf %s {configured}'}
}}
checks=0
curl() {{
    checks=$((checks + 1))
    if [[ "$checks" -le {failures} ]]; then return 22; fi
}}
sleep() {{ :; }}
""" + gate + '\nprintf "checks=%s\\n" "$checks"\n'
        return subprocess.run([BASH, "-s"], input=harness, text=True, capture_output=True)

    def test_unconfigured_max_does_not_call_health(self):
        result = self.run_gate(configured="no")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checks=0", result.stdout)

    def test_ready_configured_max_passes(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checks=1", result.stdout)

    def test_transient_failure_retries_then_passes(self):
        result = self.run_gate(failures=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checks=3", result.stdout)

    def test_unavailable_max_fails_release(self):
        result = self.run_gate(failures=8)
        self.assertEqual(result.returncode, 1)
        self.assertIn("MAX readiness did not become healthy", result.stderr)

    def test_discovery_error_does_not_skip_gate(self):
        result = self.run_gate(discovery_failure=True)
        self.assertEqual(result.returncode, 7)


if __name__ == "__main__":
    unittest.main()
