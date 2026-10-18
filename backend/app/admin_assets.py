"""Version administrative code assets without caching pages or personal data."""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse, HTMLResponse


STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSET_LINK = re.compile(
    r'''((?:src|href)=["'])(/(?:admin/static/|crm/)([\w.-]+\.(?:js|css)))(?:\?[^"']*)?(["'])'''
)


@lru_cache(maxsize=128)
def _digest(path: str, modified: int, size: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def asset_version(path: Path) -> str:
    stat = path.stat()
    return _digest(str(path), stat.st_mtime_ns, stat.st_size)


def version_admin_html(source: str) -> str:
    def replace(match: re.Match) -> str:
        path = STATIC_DIR / match[3]
        if not path.is_file():
            return match[0]
        return f'{match[1]}{match[2]}?v={asset_version(path)}{match[4]}'

    return ASSET_LINK.sub(replace, source)


def admin_file(name: str, request: Request | None = None) -> Response:
    path = STATIC_DIR / name
    if path.suffix == ".html":
        return HTMLResponse(
            version_admin_html(path.read_text(encoding="utf-8")),
            headers={"Cache-Control": "no-store"},
        )
    if request is not None and path.suffix in {".js", ".css"}:
        version = asset_version(path)
        headers = {
            "Cache-Control": (
                "private, max-age=31536000, immutable"
                if request.query_params.get("v") == version
                else "private, no-cache"
            ),
            "ETag": f'"{version}"',
        }
        # The caller checks the session before allowing a cached response.
        validators = request.headers.get("if-none-match", "").split(",")
        if any(value.strip().removeprefix("W/") in {headers["ETag"], "*"} for value in validators):
            return Response(status_code=304, headers=headers)
        return FileResponse(path, headers=headers)
    return FileResponse(path, headers={"Cache-Control": "no-store"})
