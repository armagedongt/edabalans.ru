from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "yandex_direct_stats.py"
SPEC = importlib.util.spec_from_file_location("yandex_direct_stats", SCRIPT)
assert SPEC and SPEC.loader
STATS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATS)


class YandexDirectStatsTests(unittest.TestCase):
    def test_request_uses_auto_attribution_for_the_selected_goal(self) -> None:
        captured: dict = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b"CampaignId\n"

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            self.assertEqual(45, timeout)
            return Response()

        with patch.dict(os.environ, {"YANDEX_DIRECT_TOKEN": "secret"}, clear=True):
            with patch.object(STATS.urllib.request, "urlopen", side_effect=fake_urlopen):
                STATS.request_report(714157420, "2026-09-06", "2026-09-08", 608886212)

        params = captured["params"]
        self.assertEqual(["608886212"], params["Goals"])
        self.assertEqual(["AUTO"], params["AttributionModels"])

    def test_summarize_reads_auto_attribution_goal_columns(self) -> None:
        report = (
            "CampaignId\tAdGroupId\tAdId\tImpressions\tClicks\tCost\tCtr\tAvgCpc\t"
            "Conversions_608886212_AUTO\tCostPerConversion_608886212_AUTO\t"
            "ConversionRate_608886212_AUTO\n"
            "714157420\t5795846591\t1920472171246211821\t100\t10\t500.00\t10.00\t"
            "50.00\t2\t250.00\t20.00\n"
        )

        result = STATS.summarize(report)

        self.assertEqual(2.0, result["rows"][0]["bot_start"])
        self.assertEqual(250.0, result["rows"][0]["bot_start_cpa_rub"])
        self.assertEqual(20.0, result["rows"][0]["conversion_rate_percent"])
        self.assertEqual(2.0, result["total"]["bot_start"])

    def test_summarize_keeps_support_for_aggregate_conversion_columns(self) -> None:
        report = (
            "CampaignId\tAdGroupId\tAdId\tImpressions\tClicks\tCost\tCtr\tAvgCpc\t"
            "Conversions\tCostPerConversion\tConversionRate\n"
            "714157420\t5795846591\t1920472171246211821\t100\t10\t500.00\t10.00\t"
            "50.00\t2\t250.00\t20.00\n"
        )

        result = STATS.summarize(report)

        self.assertEqual(2.0, result["rows"][0]["bot_start"])
        self.assertEqual(250.0, result["rows"][0]["bot_start_cpa_rub"])
        self.assertEqual(20.0, result["rows"][0]["conversion_rate_percent"])


if __name__ == "__main__":
    unittest.main()
