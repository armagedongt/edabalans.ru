from __future__ import annotations

import argparse
import json
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


MODULE_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_DATABASE = MODULE_ROOT / "runtime" / "catalog.sqlite"


class PrototypeHandler(SimpleHTTPRequestHandler):
    database_path = DEFAULT_DATABASE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/summary":
            return self._summary()
        if parsed.path == "/api/archive":
            return self._archive(parse_qs(parsed.query))
        if parsed.path == "/api/sequence":
            return self._sequence()
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "archive"] and parts[3] == "copy":
            return self._copy_archive(parts[2])
        self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _summary(self) -> None:
        with self._connection() as connection:
            payload = {
                "archive_items": connection.execute("SELECT count(*) FROM archive_content_items").fetchone()[0],
                "media_assets": connection.execute("SELECT count(*) FROM archive_media_assets").fetchone()[0],
                "working_copies": connection.execute("SELECT count(*) FROM content_items").fetchone()[0],
                "sequences": connection.execute("SELECT count(*) FROM sequences").fetchone()[0],
            }
        self._json(payload)

    def _archive(self, query: dict[str, list[str]]) -> None:
        search = query.get("q", [""])[0].strip()
        media = query.get("media", [""])[0].strip()
        sql = """
            SELECT a.*,
                   (SELECT count(*) FROM content_items c WHERE c.origin_archive_item_id = a.id) AS copy_count,
                   (SELECT count(*) FROM archive_links l WHERE l.archive_content_item_id = a.id) AS link_count
            FROM archive_content_items a
            WHERE 1 = 1
        """
        values: list[object] = []
        if search:
            sql += " AND (a.title LIKE ? OR a.plain_text LIKE ? OR a.scenario_name LIKE ?)"
            wildcard = f"%{search}%"
            values.extend([wildcard, wildcard, wildcard])
        if media == "with":
            sql += " AND a.media_kind IS NOT NULL"
        elif media == "without":
            sql += " AND a.media_kind IS NULL"
        sql += " ORDER BY a.scenario_name, a.source_scenario_id, a.source_block_id LIMIT 250"
        with self._connection() as connection:
            rows = [dict(row) for row in connection.execute(sql, values)]
        self._json(rows)

    def _sequence(self) -> None:
        sql = """
            SELECT s.id AS sequence_id, s.name AS sequence_name, s.version_no, s.status,
                   st.id, st.position, st.kind, st.delay_seconds, st.label, st.configuration,
                   c.id AS content_id, c.title AS content_title, c.body_source,
                   c.source_format, c.media_kind
            FROM sequences s
            JOIN sequence_steps st ON st.sequence_id = s.id
            LEFT JOIN content_items c ON c.id = st.content_item_id
            ORDER BY s.id, st.position
        """
        with self._connection() as connection:
            rows = [dict(row) for row in connection.execute(sql)]
        self._json(rows)

    def _copy_archive(self, archive_id: str) -> None:
        with self._connection() as connection:
            item = connection.execute("SELECT * FROM archive_content_items WHERE id = ?", (archive_id,)).fetchone()
            if item is None:
                return self._json({"error": "Archive item not found"}, HTTPStatus.NOT_FOUND)
            cursor = connection.execute(
                """
                INSERT INTO content_items (
                    origin_archive_item_id, title, body_source, source_format, media_kind
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (item["id"], item["title"], item["source_text"], item["source_format"], item["media_kind"]),
            )
            connection.commit()
        self._json({"id": cursor.lastrowid, "origin_archive_item_id": archive_id}, HTTPStatus.CREATED)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[prototype] {self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Telegram admin prototype")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    if not args.database.exists():
        raise SystemExit("Local catalog is missing. Run prototype/import_legacy.py first.")
    PrototypeHandler.database_path = args.database.resolve()
    server = ThreadingHTTPServer((args.host, args.port), PrototypeHandler)
    print(f"Telegram prototype: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
