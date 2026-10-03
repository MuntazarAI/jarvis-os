"""Perception pipeline: observation -> bus -> world -> memory (4.3).

One-shot, bounded, synchronous. This is a pipeline, NOT a second
intelligence engine: no planning, no policy decisions, no actions.
Every step degrades safely when its subsystem is absent, and privacy
class governs persistence (PRIVATE observations are never persisted
anywhere; SENSITIVE skips durable memory).

World rule: perception records *claims* (WorldRegistry observations).
Only file observations auto-apply, and only to their own path-keyed
document entity (idempotent upsert, conflicts stay visible).
"""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .contract import (
    MAX_OBJECTS,
    Modality,
    Observation,
    PerceptionError,
    PrivacyClass,
)

STORE_FILENAME = "perception-observations.jsonl"
MAX_STORE_BYTES = 4 * 1024 * 1024
MAX_INDEX_ENTRIES = 500
MAX_DEDUP_ENTRIES = 500
MAX_LINE_BYTES = 64 * 1024
MEMORY_CONFIDENCE_FLOOR = 0.5
AUTO_APPLY_CONFIDENCE = 0.85
MAX_SPATIAL_ELEMENTS = 10


class ChangeDetector:
    """Bounded fingerprint cache: repeats suppress downstream work."""

    def __init__(self, max_entries: int = MAX_DEDUP_ENTRIES) -> None:
        self._seen: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.max_entries = max_entries
        self.duplicates = 0

    def check(self, observation: Observation) -> tuple[bool, str]:
        """Returns (is_new, prior_observation_id)."""
        fingerprint = observation.fingerprint()
        prior = self._seen.get(fingerprint)
        if prior is not None:
            prior["hits"] = int(prior.get("hits", 1)) + 1
            self._seen.move_to_end(fingerprint)
            self.duplicates += 1
            return False, str(prior.get("observation_id", ""))
        self._seen[fingerprint] = {
            "observation_id": observation.observation_id,
            "at": observation.timestamp, "hits": 1}
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)
        return True, ""


class ObservationStore:
    """Append-only JSONL + bounded in-memory index. Crash-safe reads."""

    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None
        self._index: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / STORE_FILENAME

    def append(self, observation: Observation) -> bool:
        try:
            from ..intelligence.snapshot import scrub
            clean = scrub(observation.to_dict())
            line = json.dumps(clean, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            return False
        self._index[observation.observation_id] = json.loads(line)
        while len(self._index) > MAX_INDEX_ENTRIES:
            self._index.popitem(last=False)
        path = self.path
        if path is None:
            return True
        try:
            if path.exists() and path.stat().st_size > MAX_STORE_BYTES:
                return True  # bounded file: keep serving memory, stop growing
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            return True
        except OSError:
            return False

    def get(self, observation_id: str) -> dict[str, Any] | None:
        item = self._index.get(observation_id)
        return dict(item) if item is not None else None

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        items = list(self._index.values())
        return [dict(i) for i in items[-max(limit, 1):]][::-1]

    def count(self) -> int:
        return len(self._index)


def summarize_observation(observation: Observation) -> str:
    """One-line bounded human summary (no raw media, no secrets)."""
    payload = observation.payload
    modality = observation.modality.value
    if modality == "screen":
        text = str(payload.get("visible_text", ""))[:200]
        app = str(payload.get("active_app", "") or
                  payload.get("window_title", ""))[:80]
        return f"screen{(':' + app) if app else ''}" + \
            (f" shows {text!r}" if text else " (no text)")
    if modality in ("camera", "image"):
        objects = payload.get("objects") or []
        labels = [str(o.get("label", ""))[:40] for o in objects[:5]
                  if isinstance(o, dict)]
        scene = str(payload.get("scene", ""))[:120]
        bits = ", ".join(l for l in labels if l)
        return f"{modality} sees " + (bits or scene or "nothing distinct")
    if modality in ("file", "document"):
        return str(payload.get("summary", "file observed"))[:300]
    return f"{modality} observation ({observation.observation_id[:16]})"


class PerceptionPipeline:
    """One-shot observe -> validate -> bus -> world -> memory -> spatial.

    All subsystems optional (degrade to skipped). Read-only w.r.t. the
    outside world: the only writes are the observation store, the bus,
    world claims, memory observations, and spatial nodes — never
    devices, tools, or the network.
    """

    def __init__(self, *, bus: Any = None, world: Any = None,
                 palace: Any = None, spatial: Any = None,
                 home: str | Path | None = None) -> None:
        self.bus = bus
        self.world = world
        self.palace = palace
        self.spatial = spatial
        self.store = ObservationStore(home)
        self.dedup = ChangeDetector()
        self.metrics: dict[str, Any] = {
            "observed": 0, "duplicates": 0, "rejected": 0,
            "bus_published": 0, "world_recorded": 0, "memorized": 0,
            "spatial": 0, "errors": 0,
        }
        self._latencies: dict[str, list[float]] = {}

    # -- main entry ------------------------------------------------------

    def ingest(self, observation: Observation | dict[str, Any], *,
               publish: bool = True) -> dict[str, Any]:
        """Validate and fan out one observation. Never raises for
        malformed input (returns rejected); raises nothing at all."""
        started = time.perf_counter()
        try:
            if isinstance(observation, dict):
                obs = Observation.from_dict(observation)
            elif isinstance(observation, Observation):
                obs = observation
            else:
                return self._rejected("observation must be an object")
        except PerceptionError as exc:
            return self._rejected(str(exc)[:200])
        self.metrics["observed"] += 1
        is_new, prior_id = self.dedup.check(obs)
        if not is_new:
            self.metrics["duplicates"] += 1
            return {"ok": True, "duplicate": True,
                    "observation_id": obs.observation_id,
                    "prior_observation_id": prior_id}
        out: dict[str, Any] = {"ok": True, "duplicate": False,
                               "observation_id": obs.observation_id,
                               "modality": obs.modality.value}
        if obs.privacy_class == PrivacyClass.PRIVATE:
            # Ephemeral: bus only, nothing persisted anywhere.
            if publish:
                out["bus"] = self._publish(obs)
            self._timed("ingest", started)
            return out
        self.store.append(obs)
        if publish:
            out["bus"] = self._publish(obs)
        out["world"] = self._to_world(obs)
        out["memory"] = self._to_memory(obs)
        out["spatial"] = self._to_spatial(obs)
        self._timed("ingest", started)
        return out

    def _rejected(self, reason: str) -> dict[str, Any]:
        self.metrics["rejected"] += 1
        return {"ok": False, "error": reason}

    def _timed(self, key: str, started: float) -> None:
        elapsed = (time.perf_counter() - started) * 1000.0
        series = self._latencies.setdefault(key, [])
        series.append(elapsed)
        del series[:-100]

    # -- fan-out -----------------------------------------------------------

    def _publish(self, obs: Observation) -> dict[str, Any]:
        if self.bus is None:
            return {"published": False, "reason": "no bus bound"}
        try:
            from ..intelligence.sensory import event_from_observation
            event = event_from_observation(obs)
            delivered = self.bus.publish(event)
            self.metrics["bus_published"] += 1
            return {"published": True, "delivered": delivered,
                    "event_id": event.event_id}
        except Exception as exc:
            self.metrics["errors"] += 1
            return {"published": False,
                    "reason": f"{type(exc).__name__}"[:120]}

    def _to_world(self, obs: Observation) -> dict[str, Any]:
        if self.world is None:
            return {"recorded": False, "reason": "no world bound"}
        summary = summarize_observation(obs)
        try:
            record = self.world.observe(
                summary, observer=str(obs.source)[:80],
                source="perception", confidence=obs.confidence,
                evidence=[obs.observation_id])
            self.metrics["world_recorded"] += 1
            applied: dict[str, Any] = {"applied": False}
            if obs.modality == Modality.FILE and obs.confidence >= \
                    AUTO_APPLY_CONFIDENCE:
                applied = self._apply_file_fact(obs)
            return {"recorded": True, "observation_id": record.id,
                    **applied}
        except Exception as exc:
            self.metrics["errors"] += 1
            return {"recorded": False,
                    "reason": f"{type(exc).__name__}"[:120]}

    def _apply_file_fact(self, obs: Observation) -> dict[str, Any]:
        """Idempotent path-keyed document entity (conflicts stay visible)."""
        path = str(obs.payload.get("path", ""))
        if not path:
            return {"applied": False}
        entity_id = "document:" + path.strip().lower().replace(" ", "-")[-80:]
        try:
            existing = self.world.get_entity(entity_id)
        except Exception:
            existing = None
        try:
            if existing is None:
                entity, _ = self.world.upsert_entity(
                    "document", Path(path).name[:80],
                    state={"path": path[:300],
                           "content_hash": str(obs.payload.get(
                               "content_hash", ""))[:64]},
                    provenance={"observer": str(obs.source)[:80],
                                "observation": obs.observation_id},
                    confidence=obs.confidence,
                    entity_id=entity_id)
            else:
                new_hash = str(obs.payload.get("content_hash", ""))
                old_hash = str(existing.state.get("content_hash", ""))
                if new_hash and new_hash != old_hash:
                    entity, _ = self.world.upsert_entity(
                        existing.type, existing.name,
                        state={"content_hash": new_hash[:64]},
                        provenance={"observer": str(obs.source)[:80],
                                    "observation": obs.observation_id},
                        confidence=obs.confidence,
                        entity_id=entity_id)
                else:
                    entity = existing
            return {"applied": True, "entity_id": entity.id}
        except Exception as exc:
            return {"applied": False,
                    "reason": f"{type(exc).__name__}"[:120]}

    def _to_memory(self, obs: Observation) -> dict[str, Any]:
        if self.palace is None:
            return {"stored": False, "reason": "no palace bound"}
        if obs.privacy_class in (PrivacyClass.SENSITIVE,
                                 PrivacyClass.PRIVATE):
            return {"stored": False,
                    "reason": f"privacy {obs.privacy_class.value}: "
                              "working context only"}
        if obs.confidence < 0.5:
            return {"stored": False,
                    "reason": "below memory confidence floor"}
        try:
            from ..intelligence.snapshot import scrub
            content = scrub(summarize_observation(obs) +
                            f" [{obs.modality.value} "
                            f"{obs.confidence:.2f}]")[:500]
            memory = self.palace.store_observation(
                content, source="perception",
                confidence=obs.confidence)
            self.metrics["memorized"] += 1
            return {"stored": True,
                    "memory_id": getattr(memory, "id", "")}
        except Exception as exc:
            self.metrics["errors"] += 1
            return {"stored": False,
                    "reason": f"{type(exc).__name__}"[:120]}

    def _to_spatial(self, obs: Observation) -> dict[str, Any]:
        if self.spatial is None:
            return {"nodes": [], "reason": "no spatial bound"}
        try:
            if obs.modality == Modality.SCREEN:
                return self._screen_spatial(obs)
            if obs.modality in (Modality.CAMERA, Modality.IMAGE):
                return self._camera_spatial(obs)
        except Exception as exc:
            self.metrics["errors"] += 1
            return {"nodes": [], "reason": f"{type(exc).__name__}"[:120]}
        return {"nodes": [], "reason": "no spatial content"}

    def _screen_spatial(self, obs: Observation) -> dict[str, Any]:
        elements = [e for e in (obs.payload.get("ui_elements") or [])
                    if isinstance(e, dict)][:MAX_SPATIAL_ELEMENTS]
        nodes: list[str] = []
        for element in elements:
            bbox = element.get("bbox") or []
            position = None
            if len(bbox) == 4 and all(
                    isinstance(v, (int, float)) for v in bbox):
                position = {"x": round((bbox[0] + bbox[2] / 2.0), 3),
                            "y": round((bbox[1] + bbox[3] / 2.0), 3),
                            "z": 0.0}
            node = self.spatial.add_node(
                "object", str(element.get("label", "ui element"))[:80],
                position=position, confidence=min(
                    obs.confidence,
                    float(element.get("confidence", obs.confidence) or 0.0)),
                provenance={"observer": str(obs.source)[:80],
                            "observation": obs.observation_id,
                            "approximate": True})
            nodes.append(node.id)
        self.metrics["spatial"] += len(nodes)
        return {"nodes": nodes}

    def _camera_spatial(self, obs: Observation) -> dict[str, Any]:
        objects = [o for o in (obs.payload.get("objects") or [])
                   if isinstance(o, dict) and o.get("bbox")][:MAX_OBJECTS]
        placed: list[tuple[str, dict[str, Any]]] = []
        for item in objects[:MAX_SPATIAL_ELEMENTS]:
            node = self.spatial.add_node(
                "object", str(item.get("label", "object"))[:80],
                confidence=min(obs.confidence,
                               float(item.get("confidence", 0.5) or 0.0)),
                provenance={"observer": str(obs.source)[:80],
                            "observation": obs.observation_id,
                            "approximate": True,
                            "note": "no depth: relations only, "
                                    "never coordinates"})
            placed.append((node.id, item))
        # Qualitative left-to-right relations from x-ordering only.
        ordered = sorted(
            placed, key=lambda pair: pair[1]["bbox"][0]
            if len(pair[1].get("bbox") or []) == 4 else 2.0)
        relations = 0
        for (left_id, _), (right_id, _) in zip(ordered, ordered[1:]):
            if left_id == right_id:
                continue
            try:
                self.spatial.relate(
                    left_id, "left_of", right_id,
                    confidence=min(obs.confidence, 0.6),
                    provenance={"observer": str(obs.source)[:80],
                                "observation": obs.observation_id})
                relations += 1
                if relations >= 5:
                    break
            except (ValueError, KeyError):
                continue
        self.metrics["spatial"] += len(placed)
        return {"nodes": [node_id for node_id, _ in placed],
                "relations": relations}

    # -- observability -------------------------------------------------------

    def status(self) -> dict[str, Any]:
        latencies = {k: {"samples": len(v),
                          "p50_ms": round(sorted(v)[len(v) // 2], 2)}
                     for k, v in self._latencies.items() if v}
        return {"metrics": dict(self.metrics),
                "latency_ms": latencies,
                "dedup_cache": len(self.dedup._seen),
                "stored": self.store.count()}

    def stats(self) -> dict[str, Any]:
        return self.status()


__all__ = [
    "PerceptionPipeline",
    "ChangeDetector",
    "ObservationStore",
    "summarize_observation",
]
