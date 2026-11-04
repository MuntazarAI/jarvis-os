"""Read-only SQL reports over existing JARVIS SQLite stores.

SQL is used here as a bounded query language, not as a second store,
runtime, or action surface:

- report names and SQL files are fixed in this repository;
- the caller supplies only a name and a row limit, never SQL;
- the database is opened with a read-only URI and ``PRAGMA query_only``;
- every report must start with SELECT/WITH, be one statement, and bind
  its rows with ``:limit``;
- returned values are bounded and secret-scrubbed.

Python remains the coordinator. Nothing here writes, approves, or
executes an action.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..api.board import _SECRET_HINTS, _scrub
from ..security.findings import scrub_text

REPORT_DIR = Path(__file__).with_name("sql")
DEFAULT_LIMIT = 20
MAX_LIMIT = 200

REPORTS: dict[str, dict[str, str]] = {
    "events-summary": {
        "database": "events.db",
        "sql": "events_summary.sql",
        "description": "event counts, first/last timestamp by type",
    },
    "events-recent": {
        "database": "events.db",
        "sql": "events_recent.sql",
        "description": "most recent events with a bounded payload preview",
    },
    "memory-rooms": {
        "database": "jarvis.db",
        "sql": "memory_rooms.sql",
        "description": "active memory counts by room and tier",
    },
}

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|replace|drop|alter|create|attach|detach|"
    r"pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)


def list_reports() -> list[dict[str, str]]:
    return [
        {"name": name, **spec}
        for name, spec in sorted(REPORTS.items())
    ]


def _validate_read_only(sql: str) -> None:
    """Reject anything that is not one bounded SELECT/WITH statement."""
    clean = re.sub(r"--[^\n]*", " ", sql)
    clean = re.sub(r"/\*.*?\*/", " ", clean, flags=re.DOTALL).strip()
    if not clean:
        raise ValueError("empty report SQL")
    if not re.match(r"(?is)^(select|with)\b", clean):
        raise ValueError("report SQL must start with SELECT or WITH")
    body = clean.rstrip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        raise ValueError("report SQL must be a single statement")
    if _FORBIDDEN.search(body):
        raise ValueError("report SQL contains a write/DDL keyword")
    if ":limit" not in body:
        raise ValueError("report SQL must bound rows with :limit")


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                clean = json.dumps(_scrub(parsed), default=str)
                return scrub_text(clean, limit=400)
        return scrub_text(value, limit=400)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, (int, float)) or value is None:
        return value
    return scrub_text(str(value), limit=400)


def _clean_row(row: sqlite3.Row) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in row.keys():
        name = str(key)
        if any(hint in name.lower() for hint in _SECRET_HINTS):
            out[name] = "[redacted]"
        else:
            out[name] = _clean_value(row[key])
    return out


def run_report(name: str, home: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Run one bundled report against a fixed database name."""
    spec = REPORTS.get(name)
    if spec is None:
        raise ValueError(
            f"unknown report: {name} (choose from {', '.join(sorted(REPORTS))})")
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    limit = max(1, min(limit, MAX_LIMIT))

    sql_path = REPORT_DIR / spec["sql"]
    sql = sql_path.read_text(encoding="utf-8")
    _validate_read_only(sql)

    db_path = Path(home).expanduser() / spec["database"]
    if not db_path.is_file():
        return {
            "ok": False,
            "report": name,
            "database": spec["database"],
            "error": f"database not found: {spec['database']}",
        }

    try:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            cursor = conn.execute(sql, {"limit": limit})
            columns = [column[0] for column in (cursor.description or [])]
            rows = cursor.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "report": name,
            "database": spec["database"],
            "error": f"sqlite: {exc}"[:300],
        }

    cleaned = [_clean_row(row) for row in rows]
    return {
        "ok": True,
        "report": name,
        "database": spec["database"],
        "generated_at": time.time(),
        "limit": limit,
        "columns": columns,
        "row_count": len(cleaned),
        "rows": cleaned,
    }


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "REPORTS",
    "list_reports",
    "run_report",
]
