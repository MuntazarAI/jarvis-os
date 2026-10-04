"""Scheduled refresh over subscribed topics (World Intel 1.1).

`refresh_all` walks every subscribed topic, skips topics refreshed
within the interval, runs bounded research otherwise, appends a
snapshot, diffs against the previous snapshot, and optionally emits
one `world_changed` proactive event per topic with genuine changes.
No background threads: the caller (CLI, cron, dots tick) drives it;
all bounds come from the existing research/cache/snapshot machinery.
"""

from __future__ import annotations

import time
from typing import Any

from .cache import EvidenceCache
from .changes import diff_snapshots
from .research import Researcher
from .sources import SourceRegistry
from .subscriptions import TopicStore
from .worldsync import sync_answer

SNAPSHOT_KEY = "worldintel-refresh-snapshots"


def _now() -> float:
    return time.time()


def refresh_all(home: str, *, registry: SourceRegistry | None = None,
                cache: EvidenceCache | None = None,
                topics: list[str] | None = None,
                interval_s: float = 3600.0,
                max_searches: int = 2, max_evidence: int = 8,
                budget_s: float = 60.0, notifier: Any = None,
                world_registry: Any = None, graph: Any = None,
                now: float = 0.0) -> dict[str, Any]:
    """Refresh every due topic. Returns per-topic outcomes + totals."""
    stamp = now or _now()
    store = TopicStore(home)
    watched = topics if topics is not None else store.names()
    registry = registry or SourceRegistry()
    cache = cache or EvidenceCache(home)
    researcher = Researcher(registry, cache, max_searches=max_searches,
                            max_evidence=max_evidence, budget_s=budget_s)
    import json as _json
    from pathlib import Path as _Path
    snap_path = _Path(home) / "worldintel-refresh.jsonl"
    previous: dict[str, dict[str, Any]] = {}
    try:
        if snap_path.exists():
            for raw in snap_path.read_text(
                    encoding="utf-8").splitlines()[-50:]:
                try:
                    item = _json.loads(raw)
                    previous[str(item.get("topic", ""))] = {
                        "claims": item.get("claims", {}),
                        "_at": item.get("_at", 0.0)}
                except ValueError:
                    continue
    except OSError:
        pass
    summary: dict[str, Any] = {"topics": {}, "refreshed": 0,
                               "skipped": 0, "notified": 0,
                               "at": stamp}
    fresh_lines: list[str] = []
    for topic in watched[:50]:
        last = previous.get(topic, {}).get("_at", 0.0)
        if stamp - float(last or 0.0) < interval_s:
            summary["topics"][topic] = {"status": "skipped",
                                        "reason": "within interval"}
            summary["skipped"] += 1
            continue
        try:
            answer = researcher.research(topic)
            claims = {f"{c['subject']}|{c['predicate']}": {
                "object": c["object"],
                "confidence": c["confidence"],
                "conflicting": False} for c in answer.claims}
            if world_registry is not None or graph is not None:
                try:
                    sync_answer(answer, registry=world_registry,
                                graph=graph)
                except Exception:
                    pass
            changes = diff_snapshots(previous.get(topic, {}).get(
                "claims", {}), claims)
            summary["topics"][topic] = {
                "status": "refreshed",
                "claims": len(claims), "changes": len(changes),
                "uncertainty": answer.uncertainty[:3]}
            summary["refreshed"] += 1
            fresh_lines.append(_json.dumps(
                {"topic": topic, "_at": stamp, "claims": claims},
                sort_keys=True, default=str))
            # Notify only on deltas against an existing baseline:
            # the first refresh establishes it silently.
            if changes and topic in previous and \
                    notifier is not None:
                try:
                    from ..proactive.engine import ProactiveEvent
                    kinds = sorted({c["status"] for c in changes})
                    event = ProactiveEvent(
                        type="world_changed", source="world-refresh",
                        entity=topic[:120],
                        summary=f"{topic}: "
                                f"{', '.join(kinds)} "
                                f"({len(changes)} change(s))",
                        payload={"topic": topic, "changes": kinds},
                        confidence=0.6,
                        provenance={"observer": "world-refresh"},
                        trusted=False)
                    if notifier(event) is not None:
                        summary["notified"] += 1
                except Exception:
                    pass
        except Exception as exc:
            summary["topics"][topic] = {"status": "failed",
                                        "error": f"{type(exc).__name__}"}
    if fresh_lines:
        try:
            with open(snap_path, "a", encoding="utf-8") as handle:
                for line in fresh_lines:
                    handle.write(line + "\n")
        except OSError:
            pass
    return summary


__all__ = ["refresh_all"]
