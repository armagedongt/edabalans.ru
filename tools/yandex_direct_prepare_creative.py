#!/usr/bin/env python3
"""Create a moderated Direct ad copy with one new image, without switching traffic."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import urllib.error
import urllib.request


API_ROOT = "https://api.direct.yandex.com/json/v5"


def call(service: str, method: str, params: dict) -> dict:
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
        data=json.dumps({"method": method, "params": params}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{service}.{method}: HTTP {error.code}: {detail}") from error
    if "error" in payload:
        raise RuntimeError(f"{service}.{method}: {json.dumps(payload['error'], ensure_ascii=False)}")
    return payload.get("result", {})


def action_value(result: dict, key: str) -> dict:
    item = result[key][0]
    if item.get("Errors"):
        raise RuntimeError(json.dumps(item["Errors"], ensure_ascii=False))
    return item


def with_creative_alias(href: str, alias: str) -> str:
    parts = urlsplit(href)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["creative"] = alias
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, safe="{}"), parts.fragment))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ad-id", type=int, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--creative", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replace-source", action="store_true")
    args = parser.parse_args()

    source = call(
        "ads",
        "get",
        {
            "SelectionCriteria": {"Ids": [args.source_ad_id]},
            "FieldNames": ["Id", "AdGroupId", "Status", "State"],
            "TextAdFieldNames": [
                "Title", "Title2", "Text", "Href", "Mobile", "DisplayUrlPath",
                "VCardId", "SitelinkSetId", "AdImageHash", "AdExtensions",
            ],
        },
    )["Ads"][0]
    image_bytes = args.image.read_bytes()
    plan = {
        "source_ad_id": source["Id"],
        "source_status": source["Status"],
        "source_state": source["State"],
        "image": str(args.image),
        "image_bytes": len(image_bytes),
        "creative": args.creative,
        "href": with_creative_alias(source["TextAd"]["Href"], args.creative),
    }
    if not args.execute:
        print(json.dumps({"status": "dry_run", **plan}, ensure_ascii=False, indent=2))
        return

    uploaded = action_value(
        call(
            "adimages",
            "add",
            {
                "AdImages": [{
                    "ImageData": base64.b64encode(image_bytes).decode("ascii"),
                    "Name": args.image.name[:255],
                    "Type": "AUTO",
                }]
            },
        ),
        "AddResults",
    )
    image_hash = uploaded["AdImageHash"]
    if args.replace_source:
        action_value(
            call(
                "ads",
                "update",
                {
                    "Ads": [{
                        "Id": source["Id"],
                        "TextAd": {
                            "Href": plan["href"],
                            "AdImageHash": image_hash,
                        },
                    }]
                },
            ),
            "UpdateResults",
        )
        updated = call(
            "ads",
            "get",
            {
                "SelectionCriteria": {"Ids": [source["Id"]]},
                "FieldNames": ["Id", "AdGroupId", "Status", "State", "StatusClarification"],
                "TextAdFieldNames": ["Title", "Text", "Href", "AdImageHash"],
            },
        )["Ads"][0]
        print(json.dumps({"status": "updated", "ad": updated}, ensure_ascii=False, indent=2))
        return
    text = source["TextAd"]
    text_add = {
        "Title": text["Title"],
        "Text": text["Text"],
        "Href": plan["href"],
        "Mobile": text.get("Mobile", "NO"),
        "AdImageHash": image_hash,
    }
    for field in ("Title2", "DisplayUrlPath", "VCardId", "SitelinkSetId"):
        if text.get(field) is not None:
            text_add[field] = text[field]
    extension_ids = [item["AdExtensionId"] for item in text.get("AdExtensions", [])]
    if extension_ids:
        text_add["AdExtensionIds"] = extension_ids
    added = action_value(
        call("ads", "add", {"Ads": [{"AdGroupId": source["AdGroupId"], "TextAd": text_add}]}),
        "AddResults",
    )
    new_id = added["Id"]
    created = call(
        "ads",
        "get",
        {
            "SelectionCriteria": {"Ids": [new_id]},
            "FieldNames": ["Id", "AdGroupId", "Status", "State", "StatusClarification"],
            "TextAdFieldNames": ["Title", "Text", "Href", "AdImageHash"],
        },
    )["Ads"][0]
    print(json.dumps({"status": "created", "source_ad_id": source["Id"], "ad": created}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
