"""Reliability: persistence, restart, rollback (1.0).

Real SQLite-backed EventStore throughout this file — no mocks for
the durability claims. Deterministic, offline, bounded.
"""

from __future__ import annotations

import sqlite3

import pytest

from jarvis.events.store import Event, EventBus, EventStore


def _store(home, name="events.db"):
    return EventStore(str(home / name))


def test_write_close_reopen_retrieve(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = _store(home)
    first.record("cycle.started", {"input": "hello"},
                 correlation_id="cycle-1")
    first.record("cycle.completed", {"intent": "greeting"},
                 correlation_id="cycle-1")
    first.close()
    second = _store(home)
    try:
        found = second.by_correlation("cycle-1")
        assert [e.type for e in found] == ["cycle.started",
                                           "cycle.completed"]
        assert found[0].payload["input"] == "hello"
    finally:
        second.close()


def test_multiple_correlations_isolated(tmp_path):
    store = _store(tmp_path)
    try:
        for i in range(5):
            store.record("cycle.started", {"n": i},
                         correlation_id=f"cycle-{i}")
        for i in range(5):
            found = store.by_correlation(f"cycle-{i}")
            assert len(found) == 1 and found[0].payload["n"] == i
        assert store.by_correlation("cycle-zzz") == []
    finally:
        store.close()


def test_duplicate_event_id_rejected(tmp_path):
    store = _store(tmp_path)
    try:
        event = Event(type="x", payload={}, event_id="ev-fixed")
        store.append(event)
        with pytest.raises(Exception):
            store.append(Event(type="y", payload={},
                               event_id="ev-fixed"))
        assert len(store.by_correlation("")) >= 1
    finally:
        store.close()


def test_dedup_key_suppresses_replay(tmp_path):
    store = _store(tmp_path)
    try:
        first = store.record("alert", {"n": 1}, dedup_key="dup-1")
        second = store.record("alert", {"n": 2}, dedup_key="dup-1")
        assert first.event_id == second.event_id  # replay absorbed
        assert store.count() == 1
    finally:
        store.close()


def test_malformed_record_surfaced(tmp_path):
    path = tmp_path / "events.db"
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY "
            "KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, "
            "type TEXT NOT NULL, schema_version INTEGER NOT NULL "
            "DEFAULT 1, payload TEXT NOT NULL, correlation_id TEXT, "
            "causation_id TEXT, dedup_key TEXT, timestamp REAL NOT NULL);"
            "INSERT INTO events (event_id, type, payload, timestamp) "
            "VALUES ('ev-bad', 'broken', '{not-json', 1.0);"
            "INSERT INTO events (event_id, type, payload, timestamp) "
            "VALUES ('ev-good', 'fine', '{}', 2.0);")
        conn.commit()
    finally:
        conn.close()
    store = EventStore(str(path))
    try:
        # Good records survive alongside corrupt ones; corruption is
        # visible (flagged marker) rather than silently dropped, and
        # never breaks iteration.
        rows = list(store.stream())
        assert {e.event_id for e in rows} >= {"ev-bad", "ev-good"}
        bad = next(e for e in rows if e.event_id == "ev-bad")
        assert "_corrupt" in bad.payload
    finally:
        store.close()


def test_uncommitted_does_not_appear(tmp_path):
    path = tmp_path / "events.db"
    committed = EventStore(str(path))
    committed.record("a", {}, correlation_id="c1")
    committed.close()
    # A writer that never commits leaves no trace.
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO events (event_id, type, payload, timestamp,"
            " correlation_id) VALUES ('ev-ghost', 'x', '{}', 1.0, 'c9')")
        conn.rollback()
    finally:
        conn.close()
    reopened = EventStore(str(path))
    try:
        assert reopened.by_correlation("c9") == []
        assert len(reopened.by_correlation("c1")) == 1
    finally:
        reopened.close()


def test_bus_survives_subscriber_crash(tmp_path):
    store = _store(tmp_path)
    try:
        bus = EventBus(store)
        seen: list[str] = []

        def _bad(event: Event) -> None:
            raise RuntimeError("subscriber blew up")

        def _good(event: Event) -> None:
            seen.append(event.type)

        bus.subscribe("cycle.*", _bad)
        bus.subscribe("cycle.*", _good)
        bus.publish(Event(type="cycle.started", payload={},
                          correlation_id="c1"))
        assert seen == ["cycle.started"]  # isolation held
        assert len(store.by_correlation("c1")) == 1
    finally:
        store.close()


def test_beliefstore_restart_durable(tmp_path):
    from jarvis.cognition.beliefs import BeliefStore
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = BeliefStore(home)
    belief = first.upsert("sky is blue", 0.8, privacy_class="local")
    assert belief.revision == 0
    second = BeliefStore(home)
    assert second.get(belief.belief_id) is not None
    assert second.get(belief.belief_id).confidence == 0.8


def test_beliefstore_bounded(tmp_path):
    import jarvis.cognition.beliefs as beliefs_mod
    from jarvis.cognition.beliefs import BeliefStore
    old_max, beliefs_mod.MAX_BELIEFS = beliefs_mod.MAX_BELIEFS, 5
    try:
        store = BeliefStore(tmp_path)
        for i in range(9):
            store.upsert(f"statement {i}", 0.5)
        assert len(store._beliefs) == 5
    finally:
        beliefs_mod.MAX_BELIEFS = old_max
