from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = load_script(
    "audit_days_1_5_markdown",
    "work/content-authoring-system/audit_days_1_5_markdown.py",
)
prepare = load_script(
    "prepare_days_1_5_structure_validation",
    "work/content-authoring-system/prepare_days_1_5_structure_validation.py",
)


class DaysOneToFiveAuditTests(unittest.TestCase):
    def test_link_binding_is_part_of_comparison(self) -> None:
        first = '<p><a href="https://example.com">Alpha</a> Beta</p>'
        second = '<p>Alpha <a href="https://example.com">Beta</a></p>'

        self.assertNotEqual(audit.links(first), audit.links(second))

    def test_dqs_slider_reference_comes_from_original_html(self) -> None:
        original = """
        <div class="dqs-gallery dqs-gallery-home">
          <div class="feed-slider-track">
            <img src="./Article_files/Borshch.png">
            <img src="./Article_files/Omlet.png">
          </div>
        </div>
        <div class="dqs-gallery dqs-gallery-takeout">
          <div class="feed-slider-track">
            <img src="./Article_files/Burger.png">
            <img src="./Article_files/Ramen.png">
          </div>
        </div>
        """
        markdown = """slider(
https://storage.example/at_home/Borshch.png
https://storage.example/at_home/Omlet.png
)
slider(
https://storage.example/take_out/Burger.png
https://storage.example/take_out/Ramen.png
)
"""

        expected = audit.legacy_dqs_slider_image_names(original)
        self.assertEqual(audit.slider_image_names(markdown), expected)

        changed = markdown.replace("Borshch.png", "replaced.png")
        self.assertNotEqual(audit.slider_image_names(changed), expected)

        production = "<p>[[GALLERY:dqs-home]]</p><p>[[GALLERY:dqs-takeout]]</p>"
        expanded = audit.expand_legacy_dqs_galleries(production, expected)
        self.assertNotIn("[[GALLERY:", expanded)
        self.assertNotIn("storage.example", expanded)

    def test_dqs_audit_rejects_candidate_image_change_against_original_source(self) -> None:
        original = """
        <div class="dqs-gallery dqs-gallery-home"><div class="feed-slider-track">
          <img src="./Article_files/A.png"><img src="./Article_files/B.png">
        </div></div>
        <div class="dqs-gallery dqs-gallery-takeout"><div class="feed-slider-track">
          <img src="./Article_files/C.png"><img src="./Article_files/D.png">
        </div></div>
        """
        markdown = """Text

slider(
https://storage.example/A.png
https://storage.example/B.png
)

slider(
https://storage.example/C.png
https://storage.example/D.png
)
"""
        production = "<p>Text</p><p>[[GALLERY:dqs-home]]</p><p>[[GALLERY:dqs-takeout]]</p>"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            markdown_path = directory / "candidate.md"
            source_path = directory / "source.html"
            snapshot_path = directory / "snapshot.json"
            markdown_path.write_text(markdown.replace("A.png", "X.png"), encoding="utf-8")
            source_path.write_text(original, encoding="utf-8")
            snapshot_path.write_text(
                json.dumps({"html": production, "version": 1, "title": "DQS"}),
                encoding="utf-8",
            )
            row = audit.audit(
                {
                    "day": 4,
                    "step_id": "day-04-article-01",
                    "title": "DQS",
                    "markdown": str(markdown_path),
                    "sources": [str(source_path)],
                    "snapshot": str(snapshot_path),
                }
            )

        comparison = row["production_comparison"]
        self.assertFalse(comparison["images_exact"])
        self.assertEqual(comparison["reference_slider_image_names"][0], ["A.png", "B.png"])
        self.assertEqual(comparison["local_slider_image_names"][0], ["X.png", "B.png"])

    def test_private_output_guard_runs_before_writes(self) -> None:
        forbidden = ROOT / "work" / f"private-artifacts-{uuid.uuid4().hex}"
        argv = [
            "prepare_days_1_5_structure_validation.py",
            "--output-root",
            str(forbidden),
            "--index",
            str(ROOT / "unused-index.sqlite"),
        ]
        with patch.object(sys, "argv", argv):
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                prepare.main()
        self.assertFalse(forbidden.exists())

    def test_integrity_status_fails_on_text_media_or_link_difference(self) -> None:
        exact = {
            "production_comparison": {
                "tokens_exact": True,
                "images_exact": True,
                "links_exact": True,
            }
        }
        self.assertTrue(audit.critical_integrity_exact(exact))
        self.assertTrue(
            audit.critical_integrity_exact(
                {"tokens_exact": True, "images_exact": True, "links_exact": True}
            )
        )
        for key in ("tokens_exact", "images_exact", "links_exact"):
            changed = json.loads(json.dumps(exact))
            changed["production_comparison"][key] = False
            self.assertFalse(audit.critical_integrity_exact(changed), key)


if __name__ == "__main__":
    unittest.main()
