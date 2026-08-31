"""Production-side helper: render Markdown exactly as the course API and hash HTML."""
from __future__ import annotations

import hashlib
import json
import sys

sys.path.insert(0, "/app/backend")

from app.course_material_service import render_material


def main() -> int:
    payload = json.load(sys.stdin)
    rendered = {}
    for key, markdown in payload["materials"].items():
        html = render_material(str(markdown), "markdown")
        rendered[key] = {
            "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest()[:16],
            "html": html,
        }
    print(json.dumps({"ok": True, "materials": rendered}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
