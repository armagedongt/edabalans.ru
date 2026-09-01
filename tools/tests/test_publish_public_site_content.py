from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_SCRIPT = REPOSITORY_ROOT / "tools" / "publish_public_site_content.ps1"


class PublishPublicSiteContentTests(unittest.TestCase):
    def test_markdown_is_sent_to_ssh_as_utf8_and_saved_without_bom(self) -> None:
        script = PUBLISH_SCRIPT.read_text(encoding="utf-8")

        encoding_setup = script.index("$OutputEncoding = $utf8WithoutBom")
        ssh_pipe = script.index("ssh $HostAlias")
        self.assertLess(encoding_setup, ssh_pipe)
        self.assertIn("[Console]::OutputEncoding = $utf8WithoutBom", script)
        self.assertIn(
            "[IO.File]::WriteAllText($contentPath, $updatedMarkdown, $utf8WithoutBom)",
            script,
        )


if __name__ == "__main__":
    unittest.main()
