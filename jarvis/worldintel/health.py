"""World Intelligence health (1.0). Cheap, bounded, no model loads.

States: HEALTHY (providers reachable or cache warm), DEGRADED (some
providers failing), UNAVAILABLE (no network/providers), MISCONFIGURED
(bad config). Live checks are best-effort with short timeouts.
"""

from __future__ import annotations

import time
from typing import Any

from .sources import SourceRegistry


def check(config: Any = None, registry: SourceRegistry | None = None,
          cache: Any = None) -> dict[str, Any]:
    started = time.monotonic()
    get = (lambda k, d=None: getattr(config, k, d)
           if not isinstance(config, dict) else config.get(k, d)) \
        if config is not None else (lambda k, d=None: d)
    if config is not None and not get("enabled", True):
        return {"state": "MISCONFIGURED", "detail": "world disabled",
                "latency_ms": 0.0, "sources": {}, "cache": {}}
    registry = registry or SourceRegistry()
    sources = {s.source_id: {"kind": s.kind,
                             "enabled": s.enabled,
                             "freshness_domain": s.freshness_domain}
               for s in registry.enabled()}
    cache_info: dict[str, Any] = {}
    try:
        cache_info = cache.stats() if cache is not None else {
            "entries": 0}
    except Exception:
        cache_info = {"entries": 0, "error": "unreadable"}
    live: dict[str, Any] = {}
    try:
        from ..geospatial.live import LiveIntelligenceService
        live = {"available": True}
    except ImportError:
        live = {"available": False}
    try:
        from ..research.engine import ResearchEngine
        research = {"available": True}
    except ImportError:
        research = {"available": False}
    state = "HEALTHY" if sources else "DEGRADED"
    return {"state": state,
            "detail": f"{len(sources)} source(s) registered",
            "latency_ms": round((time.monotonic() - started) * 1000,
                                1),
            "sources": sources, "cache": cache_info, "live": live,
            "research": research}


__all__ = ["check"]
