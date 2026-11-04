"""Bounded SQL reports: fixed queries, read-only DB, bounds, scrubbing."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.events.store import Event, EventStore  # noqa: E402
from jarvis.memory.palace import MemoryPalace  # noqa: E402
from jarvis.reports.runner import (  # noqa: E402
    MAX_LIMIT,
    REPORTS,
    _validate_read_only,
    list_reports,
    run_report,
)


def _events_home(tmp_path):
    store = EventStore(tmp_path / "events.db")
    try:
        store.append(Event(type="cycle.started", payload={"input": "hello"}))
        store.append(Event(type="cycle.started", payload={"input": "again"}))
        store.append(Event(type="tool.called", payload={
            "tool": "screen_understand",
            "token": "supersecret",
            "note": "token=plaintext",
        }))
    finally:
        store.close()
    return tmp_path


def test_events_summary_counts_by_type(tmp_path):
    home = _events_home(tmp_path)
    out = run_report("events-summary", str(home))
    assert out["ok"]
    rows = {row["type"]: row for row in out["rows"]}
    assert rows["cycle.started"]["count"] == 2
    assert rows["tool.called"]["count"] == 1
    assert out["columns"] == ["type", "count", "first_at", "last_at"]


def test_events_recent_respects_limit_and_scrubs_payload(tmp_path):
    home = _events_home(tmp_path)
    out = run_report("events-recent", str(home), limit=2)
    assert out["ok"] and out["row_count"] == 2
    dumped = json.dumps(out)
    assert "supersecret" not in dumped
    assert "plaintext" not in dumped
    assert "[redacted]" in dumped


def test_memory_rooms_report(tmp_path):
    palace = MemoryPalace(str(tmp_path / "jarvis.db"))
    try:
        palace.store_fact("deploy key rotates monthly", room="Office")
        palace.store_fact("coffee is ready", room="Kitchen")
    finally:
        palace.close()
    out = run_report("memory-rooms", str(tmp_path))
    assert out["ok"]
    rooms = {row["room"]: row for row in out["rows"]}
    assert rooms["Office"]["count"] >= 1
    assert rooms["Kitchen"]["count"] >= 1


def test_missing_database_fails_honestly(tmp_path):
    out = run_report("events-summary", str(tmp_path))
    assert not out["ok"] and "database not found" in out["error"]


def test_unknown_report_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown report"):
        run_report("drop-everything", str(tmp_path))


def test_limit_is_bounded(tmp_path):
    home = _events_home(tmp_path)
    out = run_report("events-recent", str(home), limit=10_000)
    assert out["ok"] and out["limit"] == MAX_LIMIT


def test_report_sql_is_single_read_only_and_bounded():
    with pytest.raises(ValueError, match="SELECT or WITH"):
        _validate_read_only("DELETE FROM events LIMIT :limit;")
    with pytest.raises(ValueError, match="single statement"):
        _validate_read_only("SELECT 1 LIMIT :limit; DROP TABLE events;")
    with pytest.raises(ValueError, match="bound rows"):
        _validate_read_only("SELECT * FROM events;")
    with pytest.raises(ValueError, match="write/DDL"):
        _validate_read_only("WITH x AS (SELECT 1) DELETE FROM events "
                            "LIMIT :limit;")
    _validate_read_only("SELECT * FROM events LIMIT :limit;")


def test_all_bundled_reports_are_read_only_and_bounded():
    assert REPORTS
    for name in REPORTS:
        sql = (Path(__file__).resolve().parent.parent / "jarvis" / "reports"
               / "sql" / REPORTS[name]["sql"]).read_text()
        _validate_read_only(sql)
    names = {item["name"] for item in list_reports()}
    assert names == set(REPORTS)


def test_report_does_not_modify_database(tmp_path):
    home = _events_home(tmp_path)
    before = (tmp_path / "events.db").read_bytes()
    assert run_report("events-summary", str(home))["ok"]
    after = (tmp_path / "events.db").read_bytes()
    assert before == after
