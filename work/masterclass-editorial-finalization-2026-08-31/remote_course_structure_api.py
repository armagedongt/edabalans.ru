"""Temporary production-side client for the versioned course-structure API."""
from __future__ import annotations

import base64
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


URL = "http://127.0.0.1:8000/admin/api/courses/masterclass-21/structure"


def request(method: str, payload: dict | None = None) -> dict:
    username = os.environ["ADMIN_USERNAME"]
    password = os.environ["ADMIN_PASSWORD"]
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(URL, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API returned {exc.code}: {detail}") from exc


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"get", "put"}:
        raise SystemExit("usage: remote_course_structure_api.py get|put")
    if sys.argv[1] == "get":
        result = request("GET")
    else:
        payload = json.load(sys.stdin)
        current = request("GET")
        expected = int(payload["expected_version"])
        if int(current["active"]["version"]) != expected:
            raise SystemExit(
                f"preflight version conflict: expected {expected}, "
                f"current {current['active']['version']}"
            )
        result = request("PUT", payload)
        if int(result["active"]["version"]) != expected + 1:
            raise SystemExit("post-publish structure verification failed")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
