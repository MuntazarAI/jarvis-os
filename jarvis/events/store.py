"""Immutable event log with snapshots, replay and causality."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from ..core.types import content_hash, new_id, now


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    dedup_key TEXT,
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_corr ON events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_dedup ON events(dedup_key);
CREATE TABLE IF NOT EXISTS snapshots (
    seq INTEGER PRIMARY KEY,
    state TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("ev"))
    schema_version: int = 1
    correlation_id: str = ""
    causation_id: str = ""
    dedup_key: str = ""
    timestamp: float = field(default_factory=now)
    seq: int = 0

    def fingerprint(self) -> str:
        return content_hash(f"{self.type}|{json.dumps(self.payload, sort_keys=True, default=str)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "event_id": self.event_id,
            "type": self.type,
            "schema_version": self.schema_version,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "dedup_key": self.dedup_key,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Event":
        return cls(
            seq=row["seq"],
            event_id=row["event_id"],
            type=row["type"],
            schema_version=row["schema_version"],
            payload=json.loads(row["payload"]),
            correlation_id=row["correlation_id"] or "",
            causation_id=row["causation_id"] or "",
            dedup_key=row["dedup_key"] or "",
            timestamp=row["timestamp"],
        )


class EventStore:
    """Append-only event log. Events are never mutated or deleted."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._seen_dedup: set[str] = set(self._dedup_keys())

    def _dedup_keys(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT dedup_key FROM events WHERE dedup_key != ''"
        ).fetchall()
        return [r["dedup_key"] for r in rows]

    def append(self, event: Event) -> Event:
        """Append an event. Duplicate dedup_keys are dropped."""
        with self._lock:
            if event.dedup_key:
                if event.dedup_key in self._seen_dedup:
                    existing = self._find_by_dedup(event.dedup_key)
                    if existing is not None:
                        return existing
                event.dedup_key = event.dedup_key or event.fingerprint()
            if event.dedup_key in self._seen_dedup:
                existing = self._find_by_dedup(event.dedup_key)
                if existing is not None:
                    return existing
            cur = self._conn.execute(
                "INSERT INTO events (event_id, type, schema_version, payload, correlation_id,"
                " causation_id, dedup_key, timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.type,
                    event.schema_version,
                    json.dumps(event.payload, default=str),
                    event.correlation_id,
                    event.causation_id,
                    event.dedup_key,
                    event.timestamp,
                ),
            )
            self._conn.commit()
            event.seq = int(cur.lastrowid or 0)
            if event.dedup_key:
                self._seen_dedup.add(event.dedup_key)
            return event

    def _find_by_dedup(self, key: str) -> Event | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE dedup_key = ? ORDER BY seq LIMIT 1", (key,)
        ).fetchone()
        return Event.from_row(row) if row else None

    def record(
        self,
        type: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str = "",
        causation_id: str = "",
        dedup_key: str = "",
    ) -> Event:
        return self.append(
            Event(
                type=type,
                payload=payload or {},
                correlation_id=correlation_id,
                causation_id=causation_id,
                dedup_key=dedup_key,
            )
        )

    # -- reads -----------------------------------------------------------
    def stream(
        self, since: int = 0, event_type: str | None = None, limit: int | None = None
    ) -> Iterator[Event]:
        sql = "SELECT * FROM events WHERE seq > ?"
        args: list[Any] = [since]
        if event_type:
            sql += " AND type = ?"
            args.append(event_type)
        sql += " ORDER BY seq"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        for row in rows:
            yield Event.from_row(row)

    def by_correlation(self, correlation_id: str) -> list[Event]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE correlation_id = ? ORDER BY seq", (correlation_id,)
            ).fetchall()
        return [Event.from_row(r) for r in rows]

    def causes(self, event_id: str) -> list[Event]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE causation_id = ? ORDER BY seq", (event_id,)
            ).fetchall()
        return [Event.from_row(r) for r in rows]

    def last_seq(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) AS s FROM events").fetchone()
        return int(row["s"])

    def count(self) -> int:
        return self.last_seq()

    def types(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT type, COUNT(*) AS c FROM events GROUP BY type ORDER BY c DESC"
            ).fetchall()
        return {r["type"]: r["c"] for r in rows}

    # -- snapshots / replay ---------------------------------------------
    def snapshot(self, state: dict[str, Any]) -> None:
        seq = self.last_seq()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO snapshots (seq, state, created_at) VALUES (?,?,?)",
                (seq, json.dumps(state, default=str), now()),
            )
            self._conn.commit()

    def latest_snapshot(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT seq, state FROM snapshots ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        if not row:
            return 0, {}
        return int(row["seq"]), json.loads(row["state"])

    def replay(
        self, reducer: Callable[[dict[str, Any], Event], dict[str, Any]], since: int | None = None
    ) -> dict[str, Any]:
        """Rebuild state by folding events through a reducer.

        Uses the latest snapshot when available, then replays forward.
        """
        state: dict[str, Any] = {}
        start = since if since is not None else 0
        if since is None:
            snap_seq, snap_state = self.latest_snapshot()
            if snap_state:
                state = snap_state
                start = snap_seq
        for event in self.stream(since=start):
            state = reducer(state, event)
        return state

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class EventBus:
    """Async-friendly publish/subscribe over the event store."""

    def __init__(self, store: EventStore) -> None:
        self.store = store
        self._subs: dict[str, list[tuple[str, Callable[[Event], None]]]] = {}
        self._lock = threading.RLock()
        self._history: list[Event] = []

    def subscribe(self, pattern: str, handler: Callable[[Event], None], name: str = "") -> None:
        with self._lock:
            self._subs.setdefault(pattern, []).append((name or handler.__name__, handler))

    def unsubscribe(self, pattern: str, name: str) -> None:
        with self._lock:
            handlers = self._subs.get(pattern, [])
            self._subs[pattern] = [h for h in handlers if h[0] != name]

    def publish(self, event: Event) -> Event:
        stored = self.store.append(event)
        with self._lock:
            self._history.append(stored)
            targets: list[Callable[[Event], None]] = []
            for pattern, handlers in self._subs.items():
                if self._matches(pattern, stored.type):
                    targets.extend(h for _, h in handlers)
        for handler in targets:
            try:
                handler(stored)
            except Exception:  # handler isolation: one bad subscriber must not break the bus
                continue
        return stored

    @staticmethod
    def _matches(pattern: str, event_type: str) -> bool:
        if pattern in ("*", "**"):
            return True
        if pattern.endswith(".*"):
            return event_type.startswith(pattern[:-1])
        return pattern == event_type

    def history(self, limit: int = 50) -> list[Event]:
        with self._lock:
            return self._history[-limit:]
