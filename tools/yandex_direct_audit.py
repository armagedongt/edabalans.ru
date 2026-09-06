#!/usr/bin/env python3
"""Read-only Yandex Direct campaign audit with secret-safe JSON output."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


API_ROOT = "https://api.direct.yandex.com/json/v5"


def call(service: str, params: dict) -> dict:
    token = os.environ.get("YANDEX_DIRECT_TOKEN")
    if not token:
        raise RuntimeError("YANDEX_DIRECT_TOKEN is not set")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
    }
    client_login = os.environ.get("YANDEX_DIRECT_CLIENT_LOGIN")
    if client_login:
        headers["Client-Login"] = client_login
    request = urllib.request.Request(
        f"{API_ROOT}/{service}",
        data=json.dumps({"method": "get", "params": params}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{service}: HTTP {error.code}: {detail}") from error
    if "error" in payload:
        raise RuntimeError(f"{service}: {json.dumps(payload['error'], ensure_ascii=False)}")
    return payload.get("result", {})


def audit(campaign_ids: list[int]) -> dict:
    criteria = {"CampaignIds": campaign_ids}
    result: dict[str, object] = {}
    result["campaigns"] = call(
        "campaigns",
        {
            "SelectionCriteria": {"Ids": campaign_ids},
            "FieldNames": [
                "Id",
                "Name",
                "StartDate",
                "EndDate",
                "TimeTargeting",
                "TimeZone",
                "NegativeKeywords",
                "BlockedIps",
                "ExcludedSites",
                "DailyBudget",
                "Type",
                "Status",
                "State",
                "StatusPayment",
                "StatusClarification",
            ],
            "TextCampaignFieldNames": [
                "CounterIds",
                "Settings",
                "BiddingStrategy",
                "PriorityGoals",
                "AttributionModel",
                "RelevantKeywords",
            ],
        },
    ).get("Campaigns", [])
    result["ad_groups"] = call(
        "adgroups",
        {
            "SelectionCriteria": criteria,
            "FieldNames": [
                "Id",
                "Name",
                "CampaignId",
                "RegionIds",
                "NegativeKeywords",
                "TrackingParams",
                "Status",
                "ServingStatus",
                "Type",
            ],
        },
    ).get("AdGroups", [])
    result["keywords"] = call(
        "keywords",
        {
            "SelectionCriteria": criteria,
            "FieldNames": [
                "Id",
                "Keyword",
                "AdGroupId",
                "CampaignId",
                "State",
                "Status",
                "ServingStatus",
                "StrategyPriority",
                "AutotargetingCategories",
            ],
            "AutotargetingSettingsCategoriesFieldNames": [
                "Exact",
                "Narrow",
                "Alternative",
                "Accessory",
                "Broader",
            ],
            "AutotargetingSettingsBrandOptionsFieldNames": [
                "WithoutBrands",
                "WithAdvertiserBrand",
                "WithCompetitorsBrand",
            ],
        },
    ).get("Keywords", [])
    result["ads"] = call(
        "ads",
        {
            "SelectionCriteria": criteria,
            "FieldNames": [
                "Id",
                "CampaignId",
                "AdGroupId",
                "Status",
                "State",
                "StatusClarification",
                "Type",
            ],
            "TextAdFieldNames": [
                "Title",
                "Title2",
                "Text",
                "Href",
                "DisplayUrlPath",
                "AdImageHash",
                "SitelinkSetId",
                "AdExtensions",
            ],
        },
    ).get("Ads", [])
    result["bid_modifiers"] = call(
        "bidmodifiers",
        {
            "SelectionCriteria": {
                "CampaignIds": campaign_ids,
                "Levels": ["CAMPAIGN", "AD_GROUP"],
            },
            "FieldNames": ["Id", "CampaignId", "AdGroupId", "Level", "Type"],
            "DemographicsAdjustmentFieldNames": [
                "Gender",
                "Age",
                "BidModifier",
                "Enabled",
            ],
            "MobileAdjustmentFieldNames": ["BidModifier", "OperatingSystemType"],
            "TabletAdjustmentFieldNames": ["BidModifier", "OperatingSystemType"],
            "DesktopAdjustmentFieldNames": ["BidModifier"],
            "DesktopOnlyAdjustmentFieldNames": ["BidModifier"],
        },
    ).get("BidModifiers", [])
    return result


def _items(value: object) -> list:
    return value.get("Items", []) if isinstance(value, dict) else []


def summarize(audit_result: dict) -> dict:
    campaigns = []
    for campaign in audit_result["campaigns"]:
        text = campaign.get("TextCampaign") or {}
        campaigns.append(
            {
                "id": campaign["Id"],
                "name": campaign["Name"],
                "type": campaign["Type"],
                "state": campaign["State"],
                "status": campaign["Status"],
                "status_payment": campaign["StatusPayment"],
                "status_clarification": campaign.get("StatusClarification"),
                "start_date": campaign.get("StartDate"),
                "end_date": campaign.get("EndDate"),
                "time_zone": campaign.get("TimeZone"),
                "time_targeting": campaign.get("TimeTargeting"),
                "negative_keywords": _items(campaign.get("NegativeKeywords")),
                "excluded_sites_count": len(_items(campaign.get("ExcludedSites"))),
                "excluded_sites": _items(campaign.get("ExcludedSites")),
                "counters": _items(text.get("CounterIds")),
                "settings": {
                    item["Option"]: item["Value"] for item in text.get("Settings", [])
                },
                "strategy": text.get("BiddingStrategy"),
                "priority_goals": text.get("PriorityGoals"),
                "attribution_model": text.get("AttributionModel"),
                "relevant_keywords": text.get("RelevantKeywords"),
            }
        )
    groups = []
    for group in audit_result["ad_groups"]:
        groups.append(
            {
                "id": group["Id"],
                "campaign_id": group["CampaignId"],
                "name": group["Name"],
                "status": group["Status"],
                "serving_status": group["ServingStatus"],
                "region_ids": group["RegionIds"],
                "negative_keywords": _items(group.get("NegativeKeywords")),
                "tracking_params": group.get("TrackingParams"),
            }
        )
    ads = []
    for ad in audit_result["ads"]:
        text = ad.get("TextAd") or {}
        ads.append(
            {
                "id": ad["Id"],
                "campaign_id": ad["CampaignId"],
                "ad_group_id": ad["AdGroupId"],
                "state": ad["State"],
                "status": ad["Status"],
                "status_clarification": ad.get("StatusClarification"),
                "title": text.get("Title"),
                "title2": text.get("Title2"),
                "text": text.get("Text"),
                "href": text.get("Href"),
                "image_hash": text.get("AdImageHash"),
                "sitelink_set_id": text.get("SitelinkSetId"),
                "extension_ids": [
                    item.get("AdExtensionId") for item in text.get("AdExtensions", [])
                ],
            }
        )
    return {
        "campaigns": campaigns,
        "ad_groups": groups,
        "ads": ads,
        "keywords": audit_result["keywords"],
        "bid_modifiers": audit_result["bid_modifiers"],
    }


def matrix(audit_result: dict) -> dict:
    """Return a compact readiness matrix suitable for routine acceptance checks."""
    summary = summarize(audit_result)
    keyword_map: dict[int, list[dict]] = {}
    for keyword in summary["keywords"]:
        keyword_map.setdefault(keyword["AdGroupId"], []).append(
            {
                "keyword": keyword["Keyword"],
                "state": keyword["State"],
                "status": keyword["Status"],
                "serving": keyword.get("ServingStatus"),
                "autotargeting": keyword.get("AutotargetingCategories"),
            }
        )
    ad_map: dict[int, list[dict]] = {}
    for ad in summary["ads"]:
        ad_map.setdefault(ad["ad_group_id"], []).append(
            {
                "id": ad["id"],
                "state": ad["state"],
                "status": ad["status"],
                "title": ad["title"],
                "title2": ad["title2"],
                "text": ad["text"],
                "href": ad["href"],
                "image_hash": ad["image_hash"],
                "extensions": len(ad["extension_ids"]),
                "sitelink_set_id": ad["sitelink_set_id"],
            }
        )
    modifier_map: dict[int, list[dict]] = {}
    for modifier in summary["bid_modifiers"]:
        modifier_map.setdefault(modifier["CampaignId"], []).append(modifier)
    group_map: dict[int, list[dict]] = {}
    for group in summary["ad_groups"]:
        group_map.setdefault(group["campaign_id"], []).append(
            {
                "id": group["id"],
                "name": group["name"],
                "status": group["status"],
                "serving": group["serving_status"],
                "region_count": len(group["region_ids"]),
                "negative_count": len(group["negative_keywords"]),
                "tracking_params": group["tracking_params"],
                "keywords": keyword_map.get(group["id"], []),
                "ads": ad_map.get(group["id"], []),
            }
        )
    campaigns = []
    for campaign in summary["campaigns"]:
        strategy = campaign.get("strategy") or {}
        campaigns.append(
            {
                "id": campaign["id"],
                "name": campaign["name"],
                "type": campaign["type"],
                "state": campaign["state"],
                "status": campaign["status"],
                "payment": campaign["status_payment"],
                "start_date": campaign["start_date"],
                "end_date": campaign["end_date"],
                "time_zone": campaign["time_zone"],
                "negative_count": len(campaign["negative_keywords"]),
                "excluded_sites_count": campaign["excluded_sites_count"],
                "counters": campaign["counters"],
                "settings": campaign["settings"],
                "strategy": strategy,
                "priority_goals": campaign["priority_goals"],
                "attribution_model": campaign["attribution_model"],
                "bid_modifiers": modifier_map.get(campaign["id"], []),
                "groups": group_map.get(campaign["id"], []),
            }
        )
    return {"campaigns": campaigns}


def reference_assets(audit_result: dict) -> dict:
    ads = audit_result.get("ads", [])
    if not ads:
        return {"sitelinks": [], "callouts": []}
    text_ad = ads[0].get("TextAd") or {}
    sitelink_id = text_ad.get("SitelinkSetId")
    callout_ids = [
        item["AdExtensionId"] for item in text_ad.get("AdExtensions", [])
    ]
    sitelinks = []
    if sitelink_id:
        sitelinks = call(
            "sitelinks",
            {
                "SelectionCriteria": {"Ids": [sitelink_id]},
                "FieldNames": ["Id", "Sitelinks"],
            },
        ).get("SitelinksSets", [])
    callouts = []
    if callout_ids:
        callouts = call(
            "adextensions",
            {
                "SelectionCriteria": {"Ids": callout_ids},
                "FieldNames": ["Id", "Type", "Status", "State"],
                "CalloutFieldNames": ["CalloutText"],
            },
        ).get("AdExtensions", [])
    return {"sitelinks": sitelinks, "callouts": callouts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--assets", action="store_true")
    parser.add_argument("campaign_ids", nargs="+", type=int)
    args = parser.parse_args()
    try:
        output = audit(args.campaign_ids)
        if args.assets:
            output = reference_assets(output)
        elif args.matrix:
            output = matrix(output)
        elif args.summary:
            output = summarize(output)
    except Exception as error:  # concise CLI boundary
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
