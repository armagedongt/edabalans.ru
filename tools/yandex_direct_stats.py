#!/usr/bin/env python3
"""Fetch a compact Direct performance report without exposing credentials."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request


REPORT_URL = "https://api.direct.yandex.com/json/v5/reports"


def request_report(campaign_id: int, date_from: str, date_to: str, goal_id: int) -> str:
    token = os.environ.get("YANDEX_DIRECT_TOKEN")
    if not token:
        raise RuntimeError("YANDEX_DIRECT_TOKEN is not set")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
        "processingMode": "auto",
        "skipReportHeader": "true",
        "skipReportSummary": "true",
        "skipColumnHeader": "false",
        "returnMoneyInMicros": "false",
    }
    if os.environ.get("YANDEX_DIRECT_CLIENT_LOGIN"):
        headers["Client-Login"] = os.environ["YANDEX_DIRECT_CLIENT_LOGIN"]
    body = {
        "params": {
            "SelectionCriteria": {
                "Filter": [
                    {
                        "Field": "CampaignId",
                        "Operator": "EQUALS",
                        "Values": [str(campaign_id)],
                    }
                ],
                "DateFrom": date_from,
                "DateTo": date_to,
            },
            "FieldNames": [
                "CampaignId",
                "AdGroupId",
                "AdId",
                "Impressions",
                "Clicks",
                "Cost",
                "Ctr",
                "AvgCpc",
                "Conversions",
                "CostPerConversion",
                "ConversionRate",
            ],
            "Goals": [str(goal_id)],
            "AttributionModels": ["AUTO"],
            "ReportName": f"codex-rsya-{campaign_id}-{date_from}-{date_to}",
            "ReportType": "CUSTOM_REPORT",
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "YES",
            "IncludeDiscount": "YES",
        }
    }
    data = json.dumps(body).encode("utf-8")
    for _ in range(6):
        request = urllib.request.Request(REPORT_URL, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            if error.code in (201, 202):
                time.sleep(min(int(error.headers.get("retryIn", "2")), 10))
                continue
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"reports: HTTP {error.code}: {detail}") from error
    raise RuntimeError("reports: generation did not finish in retry window")


def number(value: str) -> float:
    if not value or value == "--":
        return 0.0
    return float(value.replace(",", "."))


def metric(row: dict[str, str], name: str) -> str:
    """Read either the aggregate metric or its goal/attribution-specific column."""
    if name in row:
        return row[name]
    prefix = f"{name}_"
    return next((value for key, value in row.items() if key.startswith(prefix)), "")


def summarize(tsv: str) -> dict:
    rows = list(csv.DictReader(io.StringIO(tsv), delimiter="\t"))
    result = {
        "rows": [],
        "total": {"impressions": 0, "clicks": 0, "cost_rub": 0.0, "bot_start": 0.0},
    }
    for row in rows:
        item = {
            "ad_group_id": int(row["AdGroupId"]),
            "ad_id": int(row["AdId"]),
            "impressions": int(row["Impressions"]),
            "clicks": int(row["Clicks"]),
            "cost_rub": number(row["Cost"]),
            "ctr_percent": number(row["Ctr"]),
            "avg_cpc_rub": number(row["AvgCpc"]),
            "bot_start": number(metric(row, "Conversions")),
            "bot_start_cpa_rub": number(metric(row, "CostPerConversion")),
            "conversion_rate_percent": number(metric(row, "ConversionRate")),
        }
        result["rows"].append(item)
        for key in ("impressions", "clicks", "cost_rub", "bot_start"):
            result["total"][key] += item[key]
    total = result["total"]
    total["ctr_percent"] = round(total["clicks"] / total["impressions"] * 100, 2) if total["impressions"] else 0
    total["avg_cpc_rub"] = round(total["cost_rub"] / total["clicks"], 2) if total["clicks"] else 0
    total["bot_start_cpa_rub"] = round(total["cost_rub"] / total["bot_start"], 2) if total["bot_start"] else 0
    total["conversion_rate_percent"] = round(total["bot_start"] / total["clicks"] * 100, 2) if total["clicks"] else 0
    total["cost_rub"] = round(total["cost_rub"], 2)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign_id", type=int)
    parser.add_argument("date_from")
    parser.add_argument("date_to")
    parser.add_argument("--goal-id", type=int, required=True)
    args = parser.parse_args()
    try:
        output = summarize(
            request_report(args.campaign_id, args.date_from, args.date_to, args.goal_id)
        )
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
