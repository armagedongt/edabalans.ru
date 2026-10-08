import unittest
from unittest.mock import Mock

from tools.editorial_vault_desktop import SelectionController, format_results


class DesktopSelectionTests(unittest.TestCase):
    def setUp(self):
        self.vault = Mock()
        self.vault.status.return_value = [
            {"id": "a", "title": "Статья", "status": "changed"},
            {"id": "b", "title": "Программа", "status": "clean"},
            {"id": "c", "title": "Рецепт", "status": "conflict"},
            {"id": "d", "title": "Рассылка", "status": "unsupported"},
            {"id": "e", "title": "Урок", "status": "changed"},
        ]
        self.controller = SelectionController(self.vault)
        self.controller.reload()

    def test_default_view_hides_clean_but_exposes_conflict_and_unsupported(self):
        self.assertEqual([item["id"] for item in self.controller.visible()], ["a", "c", "d", "e"])
        self.assertEqual(len(self.controller.visible(include_clean=True)), 5)

    def test_select_all_includes_only_changed(self):
        self.assertEqual(self.controller.all_changed(), ["a", "e"])
        self.vault.publish.assert_not_called()

    def test_publishes_only_explicit_selection_and_preserves_partial_results(self):
        results = [{"id": "e", "status": "error", "error": "API недоступен"}]
        self.vault.publish.return_value = results
        self.assertEqual(self.controller.publish_selected(["e", "e"]), results)
        self.vault.publish.assert_called_once_with(["e"])

    def test_selecting_unpublishable_item_cannot_publish_other_items_silently(self):
        for blocked in ("b", "c", "d", "unknown"):
            with self.subTest(blocked=blocked), self.assertRaises(ValueError):
                self.controller.publish_selected(["a", blocked])
        self.vault.publish.assert_not_called()

    def test_empty_selection_never_means_publish_all(self):
        with self.assertRaises(ValueError):
            self.controller.publish_selected([])
        self.vault.publish.assert_not_called()

    def test_reloading_status_prevents_publishing_newly_conflicted_item(self):
        self.vault.status.return_value[0]["status"] = "conflict"
        self.controller.reload()
        with self.assertRaises(ValueError):
            self.controller.publish_selected(["a"])
        self.vault.publish.assert_not_called()

    def test_result_text_exposes_both_success_and_failed_material(self):
        output = format_results([
            {"id": "a", "status": "published", "message": "Версия 4"},
            {"id": "e", "status": "error", "error": "Конфликт версии"},
        ])
        self.assertIn("a — published — Версия 4", output)
        self.assertIn("e — error — Конфликт версии", output)


if __name__ == "__main__":
    unittest.main()
