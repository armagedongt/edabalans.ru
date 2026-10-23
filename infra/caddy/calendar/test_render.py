import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("calendar_render", Path(__file__).with_name("render.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CalendarTests(unittest.TestCase):
    def fixture(self):
        return {"title": "Calendar", "start": "2020-01-22", "end": "2020-02-29",
                "cycle_start": "2020-01-21", "cycle_length": 28, "period_days": 7}

    def test_partial_month_leap_day_and_cycle_rollover(self):
        html = module.render(self.fixture())
        self.assertNotIn('data-date="2020-01-21"', html)
        self.assertIn('data-date="2020-02-29"', html)
        self.assertEqual(html.count('class="day"'), 39)
        start = html.split('data-date="2020-02-18"', 1)[1].split('class="day"', 1)[0]
        self.assertIn('phase period', start)
        self.assertIn('<span>1</span>', start)
        for day, expected in (("01", "plain"), ("02", "ovulation"), ("08", "ovulation"), ("09", "plain")):
            cell = html.split(f'data-date="2020-02-{day}"', 1)[1].split('class="day"', 1)[0]
            self.assertIn(f'phase {expected}', cell)

    def test_untrusted_text_is_escaped_and_plaque_order_is_preserved(self):
        data = self.fixture()
        data["title"] = '<script>alert("title")</script>'
        data["days"] = {"2020-01-29": {"status": "partial", "note": '<img src=x onerror="alert(1)"> & note'}}
        html = module.render(data)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)
        cell = html.split('data-date="2020-01-29"', 1)[1].split('class="day"', 1)[0]
        self.assertLess(cell.index('status partial'), cell.index('phase plain'))
        self.assertLess(cell.index('phase plain'), cell.index('class="comment"'))

    def test_missing_schedule_is_unknown_instead_of_free(self):
        html = module.render(self.fixture())
        self.assertNotIn('status free', html)
        self.assertEqual(html.count('status unknown'), 39)


if __name__ == "__main__":
    unittest.main()
