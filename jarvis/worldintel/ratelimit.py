"""Per-client API rate limiting (World Intelligence 1.0, issue #58).

Bounded in-memory sliding window per client key (auth token, else
anonymous). Stdlib only, monotonic clock (injectable for tests),
no persistence, no new services. Returns structured 429 guidance;
records metadata-only telemetry via the caller's recorder.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable


class RateLimiter:
    """N calls per window seconds, per key. Bounded memory."""

    def __init__(self, max_calls: int = 10, window_s: float = 60.0,
                 max_keys: int = 256,
                 clock: Callable[[], float] | None = None) -> None:
        self.max_calls = max(1, int(max_calls))
        self.window_s = max(1.0, float(window_s))
        self.max_keys = max(1, int(max_keys))
        self._clock = clock or time.monotonic
        self._hits: dict[str, deque[float]] = {}
        self.throttled = 0

    def _prune(self, key: str, now: float) -> deque[float]:
        calls = self._hits.get(key)
        if calls is None:
            calls = deque()
            self._hits[key] = calls
        while calls and now - calls[0] >= self.window_s:
            calls.popleft()
        return calls

    def check(self, key: str) -> dict[str, Any]:
        """Allow or reject one call. Never raises."""
        key = str(key or "anonymous")[:120]
        now = self._clock()
        if key not in self._hits and len(self._hits) >= self.max_keys:
            self.throttled += 1
            return {"allowed": False, "retry_after_s": self.window_s,
                    "reason": "too many clients"}
        calls = self._prune(key, now)
        if len(calls) >= self.max_calls:
            self.throttled += 1
            retry = round(self.window_s - (now - calls[0]), 1)
            return {"allowed": False,
                    "retry_after_s": max(0.1, retry),
                    "reason": "rate limit exceeded"}
        calls.append(now)
        return {"allowed": True, "retry_after_s": 0.0,
                "remaining": self.max_calls - len(calls)}

    def stats(self) -> dict[str, Any]:
        return {"keys": len(self._hits), "throttled": self.throttled,
                "max_calls": self.max_calls, "window_s": self.window_s}


__all__ = ["RateLimiter"]
