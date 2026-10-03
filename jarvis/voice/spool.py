"""Durable offline spool for transcript events (5.1).

When the cognitive loop is unreachable, transcript events persist to
`<home>/audio-spool.jsonl` (bounded, TTL, idempotent by event id).
On reconnect, `drain()` replays them in order with dedupe; corruption
recovers by skipping lines, never crashing. Replay protection comes
from stable event IDs, not timestamps.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

SPOOL_FILENAME = "audio-spool.jsonl"
MAX_SPOOL_BYTES = 1 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024
DEFAULT_TTL_S = 3600.0


class AudioSpoolError(ValueError):
    """Spool misuse (not a delivery failure)."""


class TranscriptSpool:
    """Bounded durable transcript queue with TTL and dedupe."""

    def __init__(self, home: str | Path | None,
                 ttl_s: float = DEFAULT_TTL_S) -> None:
        self.home = Path(home) if home else None
        self.ttl_s = ttl_s
        self.metrics: dict[str, int] = {"appended": 0, "drained": 0,
                                        "expired": 0, "duplicates": 0}

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / SPOOL_FILENAME

    def append(self, event: dict[str, Any]) -> bool:
        """Persist one transcript event. Returns stored or not."""
        if not isinstance(event, dict) or not event.get("event_id"):
            return False
        try:
            line = json.dumps(event, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            return False
        path = self.path
        if path is None:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > MAX_SPOOL_BYTES:
                return False
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            self.metrics["appended"] += 1
            return True
        except OSError:
            return False

    def drain(self, *, now: float = 0.0,
              seen_ids: set[str] | None = None) -> dict[str, Any]:
        """Read all live events oldest-first, then clear the spool.

        Expired (TTL) entries are counted and dropped; duplicates
        (against `seen_ids` or within the file) are counted and
        skipped. The file is removed atomically after a successful
        read so redelivery cannot duplicate.
        """
        stamp = now or time.time()
        path = self.path
        if path is None or not path.exists():
            return {"events": [], "expired": 0, "duplicates": 0}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {"events": [], "expired": 0, "duplicates": 0}
        seen: set[str] = set(seen_ids or ())
        events: list[dict[str, Any]] = []
        expired = duplicates = 0
        for raw in lines:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(item, dict) or not item.get("event_id"):
                continue
            event_id = str(item["event_id"])
            if event_id in seen:
                duplicates += 1
                continue
            seen.add(event_id)
            created = float(item.get("timestamp", stamp) or stamp)
            if stamp - created > self.ttl_s:
                expired += 1
                continue
            events.append(item)
        try:
            path.unlink()
        except OSError:
            pass
        self.metrics["drained"] += len(events)
        self.metrics["expired"] += expired
        self.metrics["duplicates"] += duplicates
        return {"events": events, "expired": expired,
                "duplicates": duplicates}

    def depth(self) -> dict[str, Any]:
        path = self.path
        if path is None or not path.exists():
            return {"pending": 0, "bytes": 0}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            return {"pending": len(lines),
                    "bytes": path.stat().st_size}
        except OSError:
            return {"pending": 0, "bytes": 0}


__all__ = ["TranscriptSpool", "AudioSpoolError"]
