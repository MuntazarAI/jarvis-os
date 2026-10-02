"""World Model 2.0: continuous state, snapshots, change, expectations.

Layered on top of jarvis.world.model (which is NOT modified). A StateTracker
polls cheap probes into StateSnapshots, diffs them into structured
StateChanges, and answers temporal queries. Everything unknown stays
unknown: a missing sensor never becomes a negative fact.

Honesty contracts (enforced, tested):
- state only advances on explicit observation (no continuous awareness claim)
- predictions carry basis + expiry + verification status, never stated as fact
- correlations are labeled candidates; causation needs mechanism/intervention
- memory writes preserve Memory 3.0 origin semantics
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field as dc_field, asdict
from pathlib import Path
from typing import Any, Callable

from ..core.types import new_id, now


class _Unknown:
    """Sentinel for missing sensor data. Never equals anything, never false."""

    _instance = None

    def __new__(cls) -> "_Unknown":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __bool__(self) -> bool:
        return False


UNKNOWN = _Unknown()
UNKNOWN_KEY = "__unknown__"

CHANGE_KINDS = (
    "created", "removed", "opened", "closed", "started", "stopped",
    "modified", "moved", "changed", "connected", "disconnected",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _is_unknown(value: Any) -> bool:
    return value is UNKNOWN or (
        isinstance(value, dict) and UNKNOWN_KEY in value
    )


# -- snapshots -----------------------------------------------------------
@dataclass
class StateSnapshot:
    snapshot_id: str = dc_field(default_factory=lambda: new_id("snap"))
    timestamp: float = dc_field(default_factory=now)
    source: str = "poll"
    confidence: float = 0.8
    domains: dict[str, Any] = dc_field(default_factory=dict)
    entities: list[dict[str, Any]] = dc_field(default_factory=list)
    note: str = ""

    def content_hash(self) -> str:
        return hashlib.sha256(
            _canonical({"domains": self.domains, "entities": self.entities}
                       ).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateSnapshot":
        return cls(
            snapshot_id=data.get("snapshot_id", new_id("snap")),
            timestamp=data.get("timestamp", 0.0),
            source=data.get("source", "poll"),
            confidence=data.get("confidence", 0.8),
            domains=data.get("domains", {}),
            entities=data.get("entities", []),
            note=data.get("note", ""),
        )


@dataclass
class StateChange:
    entity: str
    field: str
    old: Any
    new: Any
    kind: str
    timestamp: float = dc_field(default_factory=now)
    confidence: float = 0.8
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind not in CHANGE_KINDS:
            raise ValueError(f"unknown change kind: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateChange":
        return cls(entity=data["entity"], field=data.get("field", ""),
                   old=data.get("old"), new=data.get("new"),
                   kind=data["kind"], timestamp=data.get("timestamp", 0.0),
                   confidence=data.get("confidence", 0.8),
                   note=data.get("note", ""))

    def describe(self) -> str:
        if self.kind in ("created", "opened", "started", "connected"):
            return f"{self.entity} {self.kind}"
        if self.kind in ("removed", "closed", "stopped", "disconnected"):
            return f"{self.entity} {self.kind}"
        return f"{self.entity} {self.kind}: {self.old} → {self.new}"


# -- tracker -------------------------------------------------------------
class StateTracker:
    """Poll-based continuous state. History is bounded; persistence is JSON."""

    def __init__(self, max_history: int = 50) -> None:
        self.history: deque[StateSnapshot] = deque(maxlen=max_history)
        self.changes: deque[StateChange] = deque(maxlen=500)

    def capture(self, model: Any, source: str = "poll",
                domains: tuple[str, ...] = ("resources", "apps", "network", "rooms"),
                extras: dict[str, Any] | None = None) -> StateSnapshot:
        """Observe the world through cheap probes. One failing probe marks
        only its own domain unknown; everything else still records."""
        captured: dict[str, Any] = {}
        if "resources" in domains:
            captured["resources"] = self._safe(model.system_state)
        if "apps" in domains:
            apps = self._safe(model.applications)
            captured["apps"] = sorted(apps) if isinstance(apps, list) else apps
        if "network" in domains:
            captured["network"] = self._safe(model.network_topology)
        if "rooms" in domains:
            captured["rooms"] = self._safe(model.rooms)
        if "files" in domains:
            path = (extras or {}).get("files_path", ".")
            try:
                captured["files"] = model.filesystem_state(path)
            except Exception as exc:  # noqa: BLE001 — probe isolation
                captured["files"] = {UNKNOWN_KEY: f"{type(exc).__name__}"}
        if extras:
            for key, value in extras.items():
                if key != "files_path":
                    captured[key] = value
        snap = StateSnapshot(source=source, domains=captured)
        self._ingest(snap)
        return snap

    @staticmethod
    def _safe(probe: Callable[[], Any]) -> Any:
        try:
            return probe()
        except Exception as exc:  # noqa: BLE001 — probe isolation
            return {UNKNOWN_KEY: f"{type(exc).__name__}: {exc}"}

    def _ingest(self, snap: StateSnapshot) -> None:
        if self.history:
            for change in compare_snapshots(self.history[-1], snap):
                change.confidence = min(change.confidence, snap.confidence)
                self.changes.append(change)
        self.history.append(snap)

    def latest(self) -> StateSnapshot | None:
        return self.history[-1] if self.history else None

    def previous(self) -> StateSnapshot | None:
        return self.history[-2] if len(self.history) >= 2 else None

    def changes_since(self, timestamp: float) -> list[StateChange]:
        return [c for c in self.changes if c.timestamp >= timestamp]

    def latest_changes(self, n: int = 1) -> list[StateChange]:
        """Changes from the last n snapshot transitions."""
        if len(self.history) < 2:
            return []
        out: list[StateChange] = []
        pairs = list(self.history)[-(n + 1):]
        for older, newer in zip(pairs, pairs[1:]):
            out.extend(compare_snapshots(older, newer))
        return out

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(json.dumps({
            "snapshots": [s.to_dict() for s in self.history],
            "changes": [c.to_dict() for c in self.changes],
            "saved_at": now(),
        }, default=str, indent=2))
        return target

    def load(self, path: str | Path) -> int:
        data = json.loads(Path(path).read_text())
        self.history.clear()
        self.changes.clear()
        for raw in data.get("snapshots", []):
            self.history.append(StateSnapshot.from_dict(raw))
        for raw in data.get("changes", []):
            self.changes.append(StateChange.from_dict(raw))
        return len(self.history)


def compare_snapshots(older: StateSnapshot, newer: StateSnapshot) -> list[StateChange]:
    """Diff two snapshots. Any side unknown → no change emitted for it."""
    out: list[StateChange] = []
    for domain in sorted(set(older.domains) | set(newer.domains)):
        old, new = older.domains.get(domain), newer.domains.get(domain)
        if _is_unknown(old) or _is_unknown(new):
            continue  # unknown is not evidence of anything
        if domain == "apps":
            out.extend(_diff_sets("application", set(old), set(new),
                                  newer.timestamp, "opened", "closed"))
        elif domain == "network":
            out.extend(_diff_network(old, new, newer.timestamp))
        elif domain == "resources":
            out.extend(_diff_resources(old, new, newer.timestamp))
        elif domain == "rooms":
            out.extend(_diff_rooms(old, new, newer.timestamp))
        elif domain == "files":
            out.extend(_diff_files(old, new, newer.timestamp))
        else:
            if _canonical(old) != _canonical(new):
                out.append(StateChange(entity=domain, field="state",
                                       old=old, new=new, kind="changed",
                                       timestamp=newer.timestamp))
    return out


def _diff_sets(entity: str, old: set, new: set, ts: float,
               added_kind: str, removed_kind: str) -> list[StateChange]:
    return ([StateChange(entity=f"{entity}:{name}", field="presence",
                         old=None, new="present", kind=added_kind,
                         timestamp=ts) for name in sorted(new - old)]
            + [StateChange(entity=f"{entity}:{name}", field="presence",
                           old="present", new=None, kind=removed_kind,
                           timestamp=ts) for name in sorted(old - new)])


def _diff_network(old: Any, new: Any, ts: float) -> list[StateChange]:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    return _diff_sets("address",
                      set(old.get("addresses", [])), set(new.get("addresses", [])),
                      ts, "connected", "disconnected")


def _diff_resources(old: Any, new: Any, ts: float,
                    threshold: float = 0.05) -> list[StateChange]:
    """Numeric drift beyond relative threshold becomes a 'changed' event."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    out: list[StateChange] = []
    for section in ("disk", "memory"):
        old_sec = old.get(section, {}) if isinstance(old.get(section), dict) else {}
        new_sec = new.get(section, {}) if isinstance(new.get(section), dict) else {}
        for key in ("percent_used", "free", "available_mb"):
            if key not in old_sec or key not in new_sec:
                continue
            before, after = old_sec[key], new_sec[key]
            if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
                continue
            base = abs(before) if before else 1.0
            if abs(after - before) / base >= threshold:
                out.append(StateChange(entity=f"system:{section}", field=key,
                                       old=before, new=after, kind="changed",
                                       timestamp=ts, confidence=0.9))
    return out


def _diff_rooms(old: Any, new: Any, ts: float) -> list[StateChange]:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    out: list[StateChange] = []
    for room in sorted(set(old) | set(new)):
        before = (old.get(room) or {}).get("objects", {})
        after = (new.get(room) or {}).get("objects", {})
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        for key in sorted(set(after) - set(before)):
            out.append(StateChange(entity=f"room:{room}", field=key, old=None,
                                   new=after[key], kind="created", timestamp=ts))
        for key in sorted(set(before) - set(after)):
            out.append(StateChange(entity=f"room:{room}", field=key,
                                   old=before[key], new=None, kind="removed",
                                   timestamp=ts))
        for key in sorted(set(before) & set(after)):
            if before[key] != after[key]:
                out.append(StateChange(entity=f"room:{room}", field=key,
                                       old=before[key], new=after[key],
                                       kind="moved", timestamp=ts))
    return out


def _diff_files(old: Any, new: Any, ts: float) -> list[StateChange]:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    before = {e["name"]: e for e in old.get("entries", [])
              if isinstance(e, dict) and "name" in e}
    after = {e["name"]: e for e in new.get("entries", [])
             if isinstance(e, dict) and "name" in e}
    out: list[StateChange] = []
    for name in sorted(set(after) - set(before)):
        out.append(StateChange(entity=f"file:{name}", field="presence",
                               old=None, new="present", kind="created",
                               timestamp=ts))
    for name in sorted(set(before) - set(after)):
        out.append(StateChange(entity=f"file:{name}", field="presence",
                               old="present", new=None, kind="removed",
                               timestamp=ts))
    for name in sorted(set(before) & set(after)):
        old_e, new_e = before[name], after[name]
        if old_e.get("size") != new_e.get("size") or \
                old_e.get("modified") != new_e.get("modified"):
            out.append(StateChange(entity=f"file:{name}", field="content",
                                   old={"size": old_e.get("size"),
                                        "modified": old_e.get("modified")},
                                   new={"size": new_e.get("size"),
                                        "modified": new_e.get("modified")},
                                   kind="modified", timestamp=ts))
    return out


# -- temporal helpers ----------------------------------------------------
def describe_relative(ts: float, ref: float | None = None) -> str:
    """Human 'x minutes ago / in x hours' for a timestamp."""
    delta = (ref if ref is not None else now()) - ts
    if delta < 0:
        future = -delta
        if future < 60:
            return f"in {int(future)}s"
        if future < 3600:
            return f"in {int(future // 60)}m"
        return f"in {int(future // 3600)}h"
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def in_window(ts: float, start: float, end: float) -> bool:
    return start <= ts <= end


# -- expectations ----------------------------------------------------------
@dataclass
class Expectation:
    """'I expect Firefox to be open' — with basis, confidence and expiry."""
    name: str
    entity: str
    field: str = "presence"
    expected: Any = None
    basis: str = ""
    confidence: float = 0.7
    created: float = dc_field(default_factory=now)
    expires_at: float | None = None

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and now() >= self.expires_at

    def check(self, actual: Any) -> dict[str, Any] | None:
        """Compare one observed value. Unknown actual → no verdict, ever."""
        if _is_unknown(actual):
            return {"expectation": self.name, "status": "unknown",
                    "note": "no observation to check against"}
        if actual == self.expected:
            return None
        return {"expectation": self.name, "status": "violated",
                "expected": self.expected, "actual": actual,
                "basis": self.basis, "confidence": self.confidence}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Expectation":
        return cls(**{k: data[k] for k in
                       ("name", "entity", "field", "expected", "basis",
                        "confidence", "created", "expires_at")
                       if k in data})


class ExpectationBoard:
    def __init__(self) -> None:
        self._items: dict[str, Expectation] = {}

    def add(self, exp: Expectation) -> Expectation:
        self._items[exp.name] = exp
        return exp

    def expect(self, name: str, entity: str, expected: Any = True,
               basis: str = "", confidence: float = 0.7,
               ttl: float | None = None, field: str = "presence") -> Expectation:
        return self.add(Expectation(
            name=name, entity=entity, field=field, expected=expected,
            basis=basis, confidence=confidence,
            expires_at=(now() + ttl) if ttl else None))

    def check_all(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """state maps entity names to observed values. Missing entity →
        status unknown, never a violation."""
        out: list[dict[str, Any]] = []
        for exp in self._items.values():
            if exp.expired:
                continue
            if exp.entity not in state:
                out.append({"expectation": exp.name, "status": "unknown",
                            "note": f"no observation of {exp.entity}"})
                continue
            result = exp.check(state[exp.entity])
            if result is not None:
                out.append(result)
        return out

    def prune_expired(self) -> int:
        dead = [k for k, v in self._items.items() if v.expired]
        for key in dead:
            del self._items[key]
        return len(dead)

    def pending(self) -> list[Expectation]:
        return [e for e in self._items.values() if not e.expired]

    def to_dict(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._items.values()]

    def restore(self, items: list[dict[str, Any]]) -> None:
        for raw in items:
            exp = Expectation.from_dict(raw)
            self._items[exp.name] = exp


# -- predictions -------------------------------------------------------------
@dataclass
class Prediction:
    """Evidence-based forecast. Always labeled unverified until checked."""
    text: str
    basis: list[str] = dc_field(default_factory=list)
    confidence: float = 0.5
    created: float = dc_field(default_factory=now)
    expires_at: float | None = None
    status: str = "unverified"  # unverified | verified | falsified | expired

    def verify(self, outcome: bool) -> "Prediction":
        self.status = "verified" if outcome else "falsified"
        return self

    def refresh(self) -> "Prediction":
        if self.status == "unverified" and self.expires_at is not None \
                and now() >= self.expires_at:
            self.status = "expired"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Prediction":
        return cls(**{k: data.get(k, v) for k, v in
                       (("text", ""), ("basis", []), ("confidence", 0.5),
                        ("created", 0.0), ("expires_at", None),
                        ("status", "unverified"))})


def linear_trend(points: list[tuple[float, float]]) -> dict[str, Any] | None:
    """Least-squares rate per second. <2 points → None (no evidence)."""
    if len(points) < 2:
        return None
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    denom = sum((p[0] - mean_x) ** 2 for p in points)
    if not denom:
        return None
    slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / denom
    return {"rate_per_second": slope, "points": n,
            "from": points[0][0], "to": points[-1][0]}


class PredictionBoard:
    def __init__(self) -> None:
        self._items: list[Prediction] = []

    def predict(self, text: str, basis: list[str], confidence: float = 0.5,
                ttl: float | None = 3600.0) -> Prediction:
        if not basis:
            raise ValueError("predictions require evidence basis")
        pred = Prediction(text=text, basis=list(basis), confidence=confidence,
                          expires_at=(now() + ttl) if ttl else None)
        self._items.append(pred)
        return pred

    def due(self) -> list[Prediction]:
        return [p.refresh() for p in self._items if p.status == "unverified"]

    def history(self) -> list[Prediction]:
        return list(self._items)


# -- causality (candidates only) -----------------------------------------------
@dataclass
class CausalLink:
    cause: str
    effect: str
    evidence: list[str] = dc_field(default_factory=list)
    confidence: float = 0.4
    mechanism: str = ""  # how it works; empty = unverified correlation
    verified: bool = False

    @property
    def is_candidate(self) -> bool:
        return not self.verified

    def verify(self, mechanism: str, confidence: float) -> "CausalLink":
        self.mechanism = mechanism
        self.confidence = confidence
        self.verified = True
        return self

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_candidate"] = self.is_candidate
        return data


def candidate_correlations(
    series_a: list[tuple[float, str]], series_b: list[tuple[float, str]],
    window: float = 60.0,
) -> list[dict[str, Any]]:
    """Find A-before-B co-occurrences. Returned as CANDIDATES with an
    explicit warning — temporal order is not causation."""
    out: list[dict[str, Any]] = []
    for ts_a, label_a in series_a:
        for ts_b, label_b in series_b:
            delta = ts_b - ts_a
            if 0 <= delta <= window:
                out.append({"candidate_cause": label_a,
                            "candidate_effect": label_b,
                            "lag_seconds": round(delta, 2),
                            "warning": "correlation only — needs mechanism "
                                       "or intervention to verify"})
    return out


# -- memory integration (Memory 3.0 origins preserved) ---------------------------
def commit_snapshot(snapshot: StateSnapshot, palace: Any) -> Any:
    """Persist a snapshot summary as an OBSERVED memory."""
    domains = sorted(snapshot.domains)
    return palace.store_observation(
        f"world snapshot {snapshot.snapshot_id[:8]}: domains {', '.join(domains)}",
        room="Observation Room", source="world-state",
        confidence=snapshot.confidence,
        metadata={"snapshot_id": snapshot.snapshot_id,
                  "origin": "observed"})


def commit_change(change: StateChange, palace: Any) -> Any:
    """A detected change is itself an observation — origin stays observed."""
    return palace.store_observation(
        f"world change: {change.describe()}",
        room="Observation Room", source="world-diff",
        confidence=change.confidence,
        metadata={"origin": "observed", "kind": change.kind})


def commit_prediction(pred: Prediction, palace: Any) -> Any:
    """Predictions are stored as HYPOTHESES, never as facts."""
    return palace.remember(
        f"prediction ({pred.status}): {pred.text} "
        f"[basis: {'; '.join(pred.basis[:3])}]",
        tier="hypothesis", room="Hypothesis Room", source="world-model",
        confidence=pred.confidence,
        metadata={"origin": "hypothesis"})


# -- graph integration (no graph rewrite) ------------------------------------------
def link_world_entity(graph: Any, entity_id: str, node: str,
                      rel: str = "observed_as",
                      confidence: float = 0.7) -> Any:
    """Connect a world entity to a knowledge-graph node via relate()."""
    return graph.relate(entity_id, rel, node, confidence=confidence,
                        attrs={"layer": "world-2.0"})


# -- query interface ---------------------------------------------------------------
class WorldQuery:
    """Human questions over tracker + model. Unknowns stay unknown."""

    def __init__(self, tracker: StateTracker, model: Any,
                 expectations: ExpectationBoard | None = None,
                 predictions: PredictionBoard | None = None) -> None:
        self.tracker = tracker
        self.model = model
        self.expectations = expectations or ExpectationBoard()
        self.predictions = predictions or PredictionBoard()

    def what_is_happening(self) -> dict[str, Any]:
        """What is happening right now: latest changes + resources."""
        latest = self.tracker.latest()
        if latest is None:
            return {"status": "unknown",
                    "note": "no snapshots yet — world has not been observed"}
        changes = self.tracker.latest_changes()
        resources = latest.domains.get("resources", {})
        if _is_unknown(resources):
            resources = {"status": "unknown"}
        return {"status": "known",
                "at": latest.timestamp,
                "changes": [c.describe() for c in changes],
                "resources": resources}

    def what_changed(self, since: float | None = None,
                     limit: int = 20) -> list[str]:
        """What changed: since timestamp, else last transition."""
        if since is not None:
            return [c.describe() for c in self.tracker.changes_since(since)][-limit:]
        return [c.describe() for c in self.tracker.latest_changes()][:limit]

    def what_was_open_before(self, kind: str = "application",
                             limit: int = 20) -> list[str]:
        """Entities of a kind seen in any snapshot but absent from latest."""
        if not self.tracker.history:
            return []
        latest = self.tracker.history[-1]
        seen: set[str] = set()
        if kind == "application":
            for snap in self.tracker.history:
                apps = snap.domains.get("apps")
                if isinstance(apps, list):
                    seen.update(apps)
            current = set(latest.domains.get("apps", [])
                          if isinstance(latest.domains.get("apps"), list) else [])
            return sorted(seen - current)[:limit]
        names: set[str] = set()
        for snap in self.tracker.history:
            for entity in snap.entities:
                if isinstance(entity, dict) and entity.get("kind") == kind:
                    names.add(str(entity.get("name", "")))
        current_names = {str(e.get("name", "")) for e in latest.entities
                         if isinstance(e, dict) and e.get("kind") == kind}
        return sorted(names - current_names)[:limit]

    def what_do_you_expect(self) -> list[dict[str, Any]]:
        return [{"expectation": e.name, "entity": e.entity,
                 "expected": e.expected, "basis": e.basis,
                 "confidence": e.confidence,
                 "expired": e.expired} for e in self.expectations.pending()]

    def predictions_due(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.predictions.due()]

    def why(self, entity: str) -> dict[str, Any]:
        """Why do you believe this state is true: provenance chain."""
        for change in reversed(self.tracker.changes):
            if change.entity == entity or entity in change.entity:
                return {"entity": entity, "status": "known",
                        "last_change": change.to_dict(),
                        "description": change.describe(),
                        "confidence": change.confidence}
        if self.tracker.latest() is not None:
            return {"entity": entity, "status": "unknown",
                    "note": f"{entity} never appeared in any snapshot"}
        return {"entity": entity, "status": "unknown",
                "note": "no snapshots yet — nothing has been observed"}
