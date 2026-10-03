"""Bounded evidence cache (World Intelligence 1.0).

Keyed by (source_id, normalized query/url). Entries carry retrieved
time, freshness domain, and provenance; reads re-validate shape
(cache-poisoning guard: corrupt entries are dropped, never served).
Stale entries are served ONLY when explicitly allowed by the caller,
and always labeled stale — cached data is never presented as live.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

CACHE_FILENAME = "worldintel-cache.json"
MAX_ENTRIES = 200
MAX_ENTRY_BYTES = 64 * 1024


def cache_key(*parts: str) -> str:
    canonical = "\n".join(p.strip().lower() for p in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class EvidenceCache:
    def __init__(self, home: str | Path | None,
                 max_entries: int = MAX_ENTRIES) -> None:
        self.home = Path(home) if home else None
        self.max_entries = max(1, max_entries)
        self._items: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.dropped = 0
        self.load()

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / CACHE_FILENAME

    def load(self) -> None:
        path = self.path
        if path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.dropped += 1
            return
        if not isinstance(raw, dict):
            self.dropped += 1
            return
        for key, item in (raw.get("items") or {}).items():
            if self._valid(key, item):
                self._items[str(key)] = item
            else:
                self.dropped += 1
        self._enforce_bounds()

    def save(self) -> None:
        path = self.path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".worldintel-cache-",
                                       dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"version": 1, "items": self._items},
                              handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError:
            pass

    @staticmethod
    def _valid(key: object, item: object) -> bool:
        if not isinstance(key, str) or not key:
            return False
        if not isinstance(item, dict):
            return False
        for field in ("retrieved_at", "source_id", "freshness_domain",
                      "payload"):
            if field not in item:
                return False
        try:
            line = json.dumps(item, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False
        return len(line.encode("utf-8")) <= MAX_ENTRY_BYTES

    def _enforce_bounds(self) -> None:
        if len(self._items) <= self.max_entries:
            return
        ordered = sorted(self._items.items(),
                         key=lambda kv: float(
                             kv[1].get("retrieved_at", 0.0)))
        for key, _ in ordered[:len(self._items) - self.max_entries]:
            del self._items[key]

    def put(self, key: str, payload: dict[str, Any], *,
            source_id: str, freshness_domain: str = "general",
            at: float = 0.0) -> bool:
        item = {"retrieved_at": at or time.time(),
                "source_id": source_id[:120],
                "freshness_domain": freshness_domain[:40],
                "payload": payload}
        if not self._valid(key, item):
            return False
        self._items[key] = item
        self._enforce_bounds()
        self.save()
        return True

    def get(self, key: str) -> dict[str, Any] | None:
        item = self._items.get(key)
        if item is None:
            self.misses += 1
            return None
        if not self._valid(key, item):
            self.dropped += 1
            del self._items[key]
            self.misses += 1
            return None
        self.hits += 1
        return dict(item)

    def stats(self) -> dict[str, Any]:
        return {"entries": len(self._items), "hits": self.hits,
                "misses": self.misses, "dropped": self.dropped}


__all__ = ["EvidenceCache", "cache_key", "CACHE_FILENAME"]
