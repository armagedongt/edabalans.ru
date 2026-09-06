#!/usr/bin/env python3
"""Apply the approved, non-launching Direct fixes and verify every response."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


API_ROOT = "https://api.direct.yandex.com/json/v5"
SEARCH_CAMPAIGN = 714152601
RSYA_CAMPAIGN = 714157420
SEARCH_GROUP_NAMES = {
    5795829383: "01 | Как начать худеть",
    5795829384: "02 | Без диет и силы воли",
    5795829385: "03 | Срывы и возврат веса",
}
SEARCH_CREATIVES = {
    1920469239931549227: "search_start",
    1920469239931549228: "search_without_diets",
    1920469239931549229: "search_relapse",
}
RSYA_CREATIVES = {
    1920472171246211821: "control_jeans",
    1920472171246211822: "cat_bagel",
    1920472171246211823: "cat_hudey",
}


def call(service: str, method: str, params: dict, api_version: str = "v5") -> dict:
    token = os.environ.get("YANDEX_DIRECT_TOKEN")
    if not token:
        raise RuntimeError("YANDEX_DIRECT_TOKEN is not set")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
    }
    if os.environ.get("YANDEX_DIRECT_CLIENT_LOGIN"):
        headers["Client-Login"] = os.environ["YANDEX_DIRECT_CLIENT_LOGIN"]
    request = urllib.request.Request(
        f"https://api.direct.yandex.com/json/{api_version}/{service}",
        data=json.dumps({"method": method, "params": params}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{service}.{method}: HTTP {error.code}: {detail}") from error
    if "error" in payload:
        raise RuntimeError(f"{service}.{method}: {json.dumps(payload['error'], ensure_ascii=False)}")
    result = payload.get("result", {})
    for value in result.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("Errors"):
                    raise RuntimeError(
                        f"{service}.{method}: {json.dumps(item['Errors'], ensure_ascii=False)}"
                    )
    return result


def stopped_campaigns() -> dict[int, dict]:
    campaigns = call(
        "campaigns",
        "get",
        {
            "SelectionCriteria": {"Ids": [SEARCH_CAMPAIGN, RSYA_CAMPAIGN]},
            "FieldNames": ["Id", "Name", "State", "Status"],
            "TextCampaignFieldNames": ["Settings"],
        },
    )["Campaigns"]
    indexed = {item["Id"]: item for item in campaigns}
    for campaign_id in (SEARCH_CAMPAIGN, RSYA_CAMPAIGN):
        if indexed[campaign_id]["State"] != "SUSPENDED":
            raise RuntimeError(f"Refusing mutation: campaign {campaign_id} is not SUSPENDED")
    return indexed


def reference_assets() -> tuple[list[dict], list[int]]:
    ads = call(
        "ads",
        "get",
        {
            "SelectionCriteria": {"CampaignIds": [RSYA_CAMPAIGN]},
            "FieldNames": ["Id"],
            "TextAdFieldNames": ["SitelinkSetId", "AdExtensions"],
        },
    )["Ads"]
    text_ad = ads[0]["TextAd"]
    sitelink_id = text_ad["SitelinkSetId"]
    callout_ids = [item["AdExtensionId"] for item in text_ad["AdExtensions"]]
    sitelinks = call(
        "sitelinks",
        "get",
        {
            "SelectionCriteria": {"Ids": [sitelink_id]},
            "FieldNames": ["Id", "Sitelinks"],
        },
    )["SitelinksSets"][0]["Sitelinks"]
    return sitelinks, callout_ids


def create_tracked_sitelinks(campaign_slug: str, term: str) -> int:
    sitelinks, _ = reference_assets()
    tracked = []
    for item in sitelinks:
        copy = dict(item)
        copy["Href"] = (
            "https://похудение-это-есть.рф/podgotovka"
            "?utm_source=yandex&utm_medium=cpc"
            f"&utm_campaign={campaign_slug}_intensive_202609"
            f"&utm_content={{ad_id}}&utm_term={term}&creative=sitelink"
        )
        tracked.append(copy)
    result = call("sitelinks", "add", {"SitelinksSets": [{"Sitelinks": tracked}]})
    sitelink_id = result["AddResults"][0].get("Id")
    if not sitelink_id:
        raise RuntimeError(f"No sitelink ID returned: {json.dumps(result, ensure_ascii=False)}")
    return sitelink_id


def update_ads(sitelink_id: int, creative_map: dict[int, str], term: str) -> None:
    _, callout_ids = reference_assets()
    ads = []
    for ad_id, creative in creative_map.items():
        href = (
            "https://похудение-это-есть.рф/podgotovka"
            f"?utm_source=yandex&utm_medium=cpc"
            f"&utm_campaign={'search' if ad_id in SEARCH_CREATIVES else 'rsya'}_intensive_202609"
            f"&utm_content={{ad_id}}&utm_term={term}&creative={creative}"
        )
        ads.append(
            {
                "Id": ad_id,
                "TextAd": {
                    "Href": href,
                    "SitelinkSetId": sitelink_id,
                    "CalloutSetting": {
                        "AdExtensions": [
                            {"AdExtensionId": extension_id, "Operation": "SET"}
                            for extension_id in callout_ids
                        ]
                    },
                },
            }
        )
    call("ads", "update", {"Ads": ads})


def add_missing_search_demographics() -> None:
    current = call(
        "bidmodifiers",
        "get",
        {
            "SelectionCriteria": {
                "CampaignIds": [SEARCH_CAMPAIGN],
                "Levels": ["CAMPAIGN"],
            },
            "FieldNames": ["Id", "CampaignId", "Type"],
            "DemographicsAdjustmentFieldNames": ["Gender", "Age", "BidModifier"],
        },
    )["BidModifiers"]
    present = {
        (item["DemographicsAdjustment"].get("Gender"), item["DemographicsAdjustment"].get("Age"))
        for item in current
        if item["Type"] == "DEMOGRAPHICS_ADJUSTMENT"
    }
    missing = []
    for age in ("AGE_0_17", "AGE_55"):
        if ("GENDER_FEMALE", age) not in present:
            missing.append(
                {"Gender": "GENDER_FEMALE", "Age": age, "BidModifier": 0}
            )
    if missing:
        call(
            "bidmodifiers",
            "add",
            {
                "BidModifiers": [
                    {"CampaignId": SEARCH_CAMPAIGN, "DemographicsAdjustments": missing}
                ]
            },
        )


def main() -> int:
    stopped_campaigns()
    call(
        "campaigns",
        "update",
        {
            "Campaigns": [
                {
                    "Id": SEARCH_CAMPAIGN,
                    "Name": "Поиск | Бесплатный интенсив | Женщины | 09.2026",
                },
                {
                    "Id": RSYA_CAMPAIGN,
                    "TextCampaign": {
                        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}]
                    },
                },
            ]
        },
    )
    call(
        "adgroups",
        "update",
        {
            "AdGroups": [
                {"Id": group_id, "Name": name}
                for group_id, name in SEARCH_GROUP_NAMES.items()
            ]
        },
    )
    add_missing_search_demographics()
    search_sitelinks = create_tracked_sitelinks("search", "{keyword}")
    rsya_sitelinks = create_tracked_sitelinks("rsya", "{source}")
    update_ads(search_sitelinks, SEARCH_CREATIVES, "{keyword}")
    update_ads(rsya_sitelinks, RSYA_CREATIVES, "{source}")
    final = stopped_campaigns()
    print(
        json.dumps(
            {
                "status": "applied",
                "campaign_states": {
                    str(key): value["State"] for key, value in final.items()
                },
                "search_sitelink_set": search_sitelinks,
                "rsya_sitelink_set": rsya_sitelinks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
