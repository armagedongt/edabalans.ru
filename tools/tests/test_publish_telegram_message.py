from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TelegramMessageCliWrapperTests(unittest.TestCase):
    def test_wrapper_loads_service_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "publish_telegram_message.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"{list,get,check,publish}", result.stdout)


if __name__ == "__main__":
    unittest.main()
