"""Proactive Intelligence 3.0 — event attention and controlled decisions.

Pipeline: world/state/events → attention → candidate → decision
(IGNORE / INFORM / ASK / PLAN) → existing orchestrator → PolicyEngine →
approval → action only when permitted.

This layer PROPOSES. It never executes tools, never grants permissions,
never auto-approves, and never writes to permanent memory on its own.
All execution flows through the existing Orchestrator + PolicyEngine.

Design notes:
- Deterministic scoring with recorded reasons (no opaque weights).
- Event-driven via the existing EventBus; no background threads or polling.
- Bounded persisted state (candidates, decisions, cooldowns).
- Unknown stays unknown; untrusted stays untrusted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import new_id, now

PROACTIVE_EVENT_TYPES = (
    "world_changed",
    "state_changed",
    "memory_created",
    "goal_changed",
    "task_changed",
    "agent_completed",
    "agent_failed",
    "evidence_changed",
    "conflict_detected",
    "schedule_triggered",
)

# Base urgency per event type. Deterministic and documented.
URGENCY = {
    "agent_failed": 0.9,
    "conflict_detected": 0.85,
    "task_changed": 0.6,
    "world_changed": 0.5,
    "state_changed": 0.5,
    "evidence_changed": 0.45,
    "goal_changed": 0.55,
    "memory_created": 0.2,
    "agent_completed": 0.25,
    "schedule_triggered": 0.5,
}

LEVELS = ((0.8, "critical"), (0.6, "high"), (0.35, "elevated"), (0.0, "low"))

DECISION_IGNORE = "IGNORE"
DECISION_INFORM = "INFORM"
DECISION_ASK = "ASK"
DECISION_PLAN = "PLAN"


def _fingerprint(event_type: str, entity: str, summary: str) -> str:
    raw = f"{event_type}|{entity}|{summary}".lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ProactiveEvent:
    """Normalized internal signal. Observations, never instructions."""

    type: str
    source: str = ""
    entity: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.6
    provenance: dict[str, Any] = field(default_factory=dict)
    trusted: bool = True
    event_id: str = field(default_factory=lambda: new_id("pev"))
    timestamp: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "type": self.type,
            "source": self.source, "entity": self.entity,
            "summary": self.summary, "payload": self.payload,
            "confidence": self.confidence, "provenance": self.provenance,
            "trusted": self.trusted, "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProactiveEvent":
        return cls(
            type=data.get("type", "state_changed"),
            source=data.get("source", ""),
            entity=data.get("entity", ""),
            summary=data.get("summary", ""),
            payload=data.get("payload", {}),
            confidence=data.get("confidence", 0.6),
            provenance=data.get("provenance", {}),
            trusted=data.get("trusted", True),
            event_id=data.get("event_id", new_id("pev")),
            timestamp=data.get("timestamp", now()))

    @classmethod
    def from_bus_event(cls, event: Any) -> "ProactiveEvent":
        """Adapt a loop EventBus event. Unknown shapes stay explicit."""
        etype = getattr(event, "type", "state_changed")
        payload = getattr(event, "payload", {}) or {}
        return cls(
            type=etype if etype in PROACTIVE_EVENT_TYPES else "state_changed",
            source="event-bus",
            entity=str(payload.get("entity", payload.get("tool", ""))),
            summary=str(payload.get("summary", etype)),
            payload=dict(payload),
            confidence=float(payload.get("confidence", 0.5)),
            provenance={"bus_event_id": getattr(event, "event_id", ""),
                        "original_type": etype},
            trusted=True,
            timestamp=float(getattr(event, "timestamp", now())))


@dataclass
class AttentionCandidate:
    candidate_id: str = field(default_factory=lambda: new_id("cand"))
    fingerprint: str = ""
    source_event_id: str = ""
    event_ids: list[str] = field(default_factory=list)
    type: str = ""
    entity: str = ""
    summary: str = ""
    level: str = "low"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.5
    created_at: float = field(default_factory=now)
    expires_at: float | None = None
    status: str = "pending"  # pending | decided | suppressed | expired
    suppressed_duplicates: int = 0
    trusted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "fingerprint": self.fingerprint,
            "source_event_id": self.source_event_id,
            "event_ids": self.event_ids, "type": self.type,
            "entity": self.entity, "summary": self.summary,
            "level": self.level, "score": self.score,
            "reasons": self.reasons, "confidence": self.confidence,
            "created_at": self.created_at, "expires_at": self.expires_at,
            "status": self.status,
            "suppressed_duplicates": self.suppressed_duplicates,
            "trusted": self.trusted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AttentionCandidate":
        return cls(
            candidate_id=data.get("candidate_id", new_id("cand")),
            fingerprint=data.get("fingerprint", ""),
            source_event_id=data.get("source_event_id", ""),
            event_ids=list(data.get("event_ids", [])),
            type=data.get("type", ""), entity=data.get("entity", ""),
            summary=data.get("summary", ""),
            level=data.get("level", "low"), score=data.get("score", 0.0),
            reasons=list(data.get("reasons", [])),
            confidence=data.get("confidence", 0.5),
            created_at=data.get("created_at", now()),
            expires_at=data.get("expires_at"),
            status=data.get("status", "pending"),
            suppressed_duplicates=data.get("suppressed_duplicates", 0),
            trusted=data.get("trusted", True))

    def explain(self) -> str:
        lines = [f"candidate {self.candidate_id} [{self.level}] "
                 f"score={self.score:.2f} status={self.status}",
                 f"  event: {self.type} entity={self.entity or '?'}",
                 f"  trigger: {self.summary or '(no summary)'}"]
        for reason in self.reasons:
            lines.append(f"  reason: {reason}")
        lines.append(f"  confidence={self.confidence:.2f} "
                         f"trusted={self.trusted}")
        if self.suppressed_duplicates:
            lines.append(f"  suppressed {self.suppressed_duplicates} duplicate(s) "
                         f"under cooldown (events preserved)")
        return "\n".join(lines)


class AttentionEngine:
    """Deterministic 'is this worth considering?' scoring."""

    def __init__(self, cooldown_s: float = 3600.0) -> None:
        self.cooldown_s = cooldown_s
        self._seen: dict[str, dict[str, Any]] = {}

    #: Adaptive multipliers keyed by scoring factor. Bounded [0.5, 1.5].
    #: Base urgency, confidence scaling and safety caps are NEVER weighted.
    WEIGHT_FACTORS = ("novelty", "recurrence", "goal_relevance")
    WEIGHT_MIN = 0.5
    WEIGHT_MAX = 1.5

    def score(self, event: ProactiveEvent,
              goal_texts: list[str] | None = None,
              weights: dict[str, float] | None = None) -> AttentionCandidate:
        reasons: list[str] = []
        weights = weights or {}
        base = URGENCY.get(event.type, 0.3)
        reasons.append(f"base urgency {base:.2f} for type {event.type}")
        score = base
        fp = _fingerprint(event.type, event.entity, event.summary)
        # Confidence scales the signal; it never invents one.
        # Zero confidence carries no signal at all.
        if event.confidence <= 0.0:
            reasons.append("zero confidence: no signal")
            return AttentionCandidate(
                fingerprint=fp, source_event_id=event.event_id,
                event_ids=[event.event_id], type=event.type,
                entity=event.entity, summary=event.summary,
                level="low", score=0.0,
                reasons=reasons, confidence=0.0, trusted=event.trusted)
        score *= 0.5 + 0.5 * max(0.0, min(1.0, event.confidence))
        reasons.append(f"scaled by confidence {event.confidence:.2f}")
        # Novelty: first sighting of this fingerprint matters more.
        # (fp already computed above for the zero-confidence guard.)
        seen = self._seen.get(fp)
        w_novel = float(weights.get("novelty", 1.0))
        w_recur = float(weights.get("recurrence", 1.0))
        if seen is None:
            score += 0.15 * w_novel
            reasons.append("novel: first occurrence of this signal"
                           + (f" (weight {w_novel:.2f})" if w_novel != 1.0 else ""))
        else:
            score += min(0.2, 0.05 * seen["count"]) * w_recur
            reasons.append(
                f"recurring: seen {seen['count']}x before "
                f"(raises urgency, cooldown still applies)"
                + (f" (weight {w_recur:.2f})" if w_recur != 1.0 else ""))
        # Goal relevance: entity or keywords overlap stated goals.
        goal_hit = False
        for goal in goal_texts or []:
            hay = f"{event.entity} {event.summary}".lower()
            tokens = [t for t in goal.lower().split() if len(t) > 3]
            if any(t in hay for t in tokens[:12]):
                goal_hit = True
                break
        if goal_hit:
            w_goal = float(weights.get("goal_relevance", 1.0))
            score += 0.2 * w_goal
            reasons.append("relevant to a stated user goal"
                           + (f" (weight {w_goal:.2f})" if w_goal != 1.0 else ""))
        # Untrusted content is capped: it may inform, never drive action.
        if not event.trusted:
            score = min(score, 0.65)
            reasons.append("capped: untrusted source cannot drive action")
        # Disputed facts need a human: conflicts cap at ASK, never PLAN.
        if event.type == "conflict_detected":
            score = min(score, 0.79)
            reasons.append("capped: conflicting evidence needs human judgment")
        score = round(max(0.0, min(1.0, score)), 3)
        level = next(label for bound, label in LEVELS if score >= bound)
        return AttentionCandidate(
            fingerprint=fp, source_event_id=event.event_id,
            event_ids=[event.event_id], type=event.type, entity=event.entity,
            summary=event.summary,
            level=level, score=score, reasons=reasons,
            confidence=event.confidence, trusted=event.trusted)

    def note_seen(self, fingerprint: str) -> None:
        entry = self._seen.get(fingerprint)
        if entry is None:
            self._seen[fingerprint] = {"count": 1, "first_at": now()}
        else:
            entry["count"] += 1

    def snapshot(self) -> dict[str, Any]:
        return {"cooldown_s": self.cooldown_s, "seen": self._seen}

    def restore(self, data: dict[str, Any]) -> None:
        self.cooldown_s = data.get("cooldown_s", self.cooldown_s)
        self._seen = data.get("seen", {})


@dataclass
class ProactiveDecision:
    candidate_id: str
    decision: str = DECISION_IGNORE
    reasons: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.5
    policy_status: str = "not-evaluated"
    timestamp: float = field(default_factory=now)
    plan: dict[str, Any] | None = None
    question: str = ""
    notification: str = ""
    source_dot: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "decision": self.decision,
            "reasons": self.reasons, "evidence_refs": self.evidence_refs,
            "confidence": self.confidence, "policy_status": self.policy_status,
            "timestamp": self.timestamp, "plan": self.plan,
            "question": self.question, "notification": self.notification,
            "source_dot": self.source_dot,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProactiveDecision":
        return cls(
            candidate_id=data["candidate_id"],
            decision=data.get("decision", DECISION_IGNORE),
            reasons=list(data.get("reasons", [])),
            evidence_refs=list(data.get("evidence_refs", [])),
            confidence=data.get("confidence", 0.5),
            policy_status=data.get("policy_status", "not-evaluated"),
            timestamp=data.get("timestamp", now()),
            plan=data.get("plan"),
            question=data.get("question", ""),
            notification=data.get("notification", ""),
            source_dot=data.get("source_dot", ""))

    def explain(self) -> str:
        lines = [f"decision {self.decision} for {self.candidate_id} "
                 f"(confidence {self.confidence:.2f}, policy: {self.policy_status})"]
        for reason in self.reasons:
            lines.append(f"  reason: {reason}")
        if self.evidence_refs:
            lines.append(f"  evidence: {', '.join(self.evidence_refs[:5])}")
        if self.question:
            lines.append(f"  question: {self.question}")
        if self.plan:
            lines.append(f"  proposed plan: team={self.plan.get('team')} "
                         f"depth={self.plan.get('depth')} "
                         f"(NOT executed — requires orchestrator + policy)")
        if self.notification:
            lines.append(f"  notify: {self.notification}")
        return "\n".join(lines)


class ProactiveEngine:
    """Owns candidates, cooldowns, decisions, notifications, persistence.

    No threads, no polling, no model calls, no tool execution.
    """

    #: Explicit user settings. Learning and notifications below always
    #: defer to these; behavior is never inferred.
    DEFAULT_OVERRIDES = {
        "notifications_enabled": True,
        "learning_enabled": True,
        "quiet_hours": None,  # [start_hour, end_hour] or None
        "notification_cooldown_s": 600.0,
        "max_notifications_per_hour": 10,
        "per_dot": {},  # dot_id -> {"notifications": bool}
    }

    #: Observable outcome fields. Only these keys are stored.
    OUTCOME_FIELDS = ("notified", "interacted", "approved", "task_succeeded",
                      "ignored", "useful", "note")

    def __init__(self, home: str | Path | None = None,
                 cooldown_s: float = 3600.0, max_records: int = 200) -> None:
        self._goal_texts: list[str] = []
        self.attention = AttentionEngine(cooldown_s=cooldown_s)
        self.candidates: dict[str, AttentionCandidate] = {}
        self.decisions: dict[str, ProactiveDecision] = {}
        self.notifications: list[dict[str, Any]] = []
        self.outcomes: list[dict[str, Any]] = []
        self.weights: dict[str, float] = {f: 1.0 for f in
                                          AttentionEngine.WEIGHT_FACTORS}
        self.weight_history: list[dict[str, Any]] = []
        self.overrides: dict[str, Any] = json.loads(
            json.dumps(self.DEFAULT_OVERRIDES))
        self._notifier: Any = None
        self.max_records = max_records
        self.home = Path(home) if home else None
        if self.home is not None:
            self.load()

    # -- paths ------------------------------------------------------
    @property
    def _path(self) -> Path | None:
        return self.home / "proactive.json" if self.home else None

    def save(self) -> None:
        path = self._path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "candidates": [c.to_dict() for c in
                               list(self.candidates.values())[-self.max_records:]],
                "decisions": [d.to_dict() for d in
                              list(self.decisions.values())[-self.max_records:]],
                "notifications": self.notifications[-self.max_records:],
                "attention": self.attention.snapshot(),
                "outcomes": self.outcomes[-self.max_records:],
                "weights": dict(self.weights),
                "weight_history": self.weight_history[-self.max_records:],
                "overrides": self.overrides,
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, default=str, indent=2))
            tmp.replace(path)
        except OSError:
            pass

    def load(self) -> None:
        path = self._path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        for raw in data.get("candidates", [])[-self.max_records:]:
            try:
                cand = AttentionCandidate.from_dict(raw)
            except (KeyError, TypeError):
                continue
            self.candidates[cand.candidate_id] = cand
        for raw in data.get("decisions", [])[-self.max_records:]:
            try:
                dec = ProactiveDecision.from_dict(raw)
            except (KeyError, TypeError):
                continue
            self.decisions[dec.candidate_id] = dec
        self.notifications = data.get("notifications", [])[-self.max_records:]
        if "attention" in data:
            self.attention.restore(data["attention"])
        self.outcomes = [o for o in data.get("outcomes", [])
                         if isinstance(o, dict)][-self.max_records:]
        if isinstance(data.get("weights"), dict):
            for factor in AttentionEngine.WEIGHT_FACTORS:
                value = data["weights"].get(factor, 1.0)
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
                self.weights[factor] = max(AttentionEngine.WEIGHT_MIN, min(
                    AttentionEngine.WEIGHT_MAX, value))
        if isinstance(data.get("weight_history"), list):
            self.weight_history = data["weight_history"][-self.max_records:]
        if isinstance(data.get("overrides"), dict):
            for key in self.DEFAULT_OVERRIDES:
                if key in data["overrides"]:
                    self.overrides[key] = data["overrides"][key]

    # -- intake -----------------------------------------------------
    def attach(self, bus: Any) -> None:
        """Subscribe to the existing EventBus. Event-driven, no polling."""
        bus.subscribe("world.*", self._on_bus_event, name="proactive-world")
        bus.subscribe("task.*", self._on_bus_event, name="proactive-task")
        bus.subscribe("cycle.*", self._on_bus_event, name="proactive-cycle")

    def _on_bus_event(self, event: Any) -> None:
        try:
            etype = getattr(event, "type", "")
            # Routine lifecycle heartbeat is not a proactive signal; every
            # conversation turn would otherwise spam candidates. Failures
            # still surface via agent_failed/task paths with real evidence.
            if etype in ("cycle.started", "cycle.completed"):
                payload = getattr(event, "payload", {}) or {}
                if not any(k in payload for k in ("error", "failure", "failed")):
                    return
            self.notify(ProactiveEvent.from_bus_event(event))
        except Exception:
            pass

    def notify(self, event: ProactiveEvent) -> AttentionCandidate | None:
        """Accept one normalized event. Returns a live candidate, or None
        when the signal is a cooled-down duplicate (event still preserved
        on the original candidate's event list)."""
        if event.type not in PROACTIVE_EVENT_TYPES:
            return None
        fp = _fingerprint(event.type, event.entity, event.summary)
        for cand in self.candidates.values():
            if cand.fingerprint == fp and cand.status == "pending":
                last = cand.created_at
                if now() - last < self.attention.cooldown_s:
                    cand.event_ids.append(event.event_id)
                    cand.suppressed_duplicates += 1
                    self.attention.note_seen(fp)
                    return None
        candidate = self.attention.score(
            event, goal_texts=getattr(self, "_goal_texts", None),
            weights=dict(self.weights))
        candidate.event_ids = [event.event_id]
        self.attention.note_seen(fp)
        self.candidates[candidate.candidate_id] = candidate
        self._trim()
        return candidate

    def _trim(self) -> None:
        while len(self.candidates) > self.max_records:
            oldest = min(self.candidates.values(), key=lambda c: c.created_at)
            del self.candidates[oldest.candidate_id]

    # -- decisions --------------------------------------------------
    def decide(self, candidate_id: str,
               emergency_stop: bool = False) -> ProactiveDecision | None:
        """IGNORE / INFORM / ASK / PLAN. Never executes anything."""
        cand = self.candidates.get(candidate_id)
        if cand is None or cand.status != "pending":
            return None
        if cand.expires_at is not None and now() >= cand.expires_at:
            decision = self._record(cand, DECISION_IGNORE,
                                    ["candidate expired before decision"],
                                    cand.confidence)
            cand.status = "expired"
            return decision
        if emergency_stop:
            return self._record(
                cand, DECISION_IGNORE, ["emergency stop active: no action proposed"],
                cand.confidence, policy_status="emergency-stop")
        reasons = list(cand.reasons)
        evidence = [cand.source_event_id]
        if cand.score < 0.35:
            return self._record(cand, DECISION_IGNORE,
                                reasons + ["score below action threshold"],
                                cand.confidence)
        if cand.score < 0.6:
            note = f"noticed: {cand.type} {cand.entity or '(no entity)'}".strip()
            decision = self._record(cand, DECISION_INFORM,
                                    reasons + ["worth surfacing, no action needed"],
                                    cand.confidence)
            decision.notification = note
            self.notifications.append(
                {"candidate_id": cand.candidate_id, "text": note,
                 "at": now(), "level": cand.level})
            self._maybe_notify(decision, cand)
            return decision
        if cand.score < 0.8 or not _trusted_candidate(cand):
            question = (f"I noticed {cand.type}"
                        + (f" involving {cand.entity}" if cand.entity else "")
                        + ". Want me to look into it?")
            decision = self._record(cand, DECISION_ASK,
                                    reasons + ["needs human judgment"],
                                    cand.confidence,
                                    question=question,
                                    evidence_refs=evidence)
            self._maybe_notify(decision, cand)
            return decision
        plan = {"team": _team_for(cand.type), "depth": 2,
                "goal": f"investigate: {cand.type} {cand.entity}".strip()}
        return self._record(cand, DECISION_PLAN,
                            reasons + ["high urgency, propose bounded investigation"],
                            cand.confidence, evidence_refs=evidence, plan=plan)

    def _record(self, cand: AttentionCandidate, decision: str,
                reasons: list[str], confidence: float,
                policy_status: str = "not-evaluated",
                evidence_refs: list[str] | None = None,
                plan: dict[str, Any] | None = None,
                question: str = "") -> ProactiveDecision:
        cand.status = "decided"
        record = ProactiveDecision(
            candidate_id=cand.candidate_id, decision=decision,
            reasons=reasons, evidence_refs=evidence_refs or [cand.source_event_id],
            confidence=confidence, policy_status=policy_status,
            plan=plan, question=question)
        self.decisions[cand.candidate_id] = record
        return record

    def execute_plan(self, decision: ProactiveDecision,
                     orchestrator: Any) -> dict[str, Any]:
        """Run a PLAN decision through the EXISTING orchestrator.

        Policy, approvals, budgets, and failure handling all belong to the
        orchestrator — this method only forwards the proposal.
        """
        if decision.decision != DECISION_PLAN or not decision.plan:
            return {"ok": False, "error": "decision is not an executable plan"}
        try:
            out = orchestrator.run(
                decision.plan.get("goal", ""),
                team=decision.plan.get("team") or None,
                depth=decision.plan.get("depth", 2))
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        decision.policy_status = "executed-via-orchestrator"
        return {"ok": out.get("ok", False), "task_id": out.get("task_id", ""),
                "failure": out.get("failure", "")}

    # -- scanning (on-demand, no background work) -------------------
    def scan(self, tasks: Any = None, triggers: Any = None,
             world: Any = None, goals: list[str] | None = None,
             now_ts: float | None = None) -> list[AttentionCandidate]:
        """Derive candidates from current subsystem state. Read-only."""
        stamp = now_ts if now_ts is not None else now()
        out: list[AttentionCandidate] = []
        if tasks is not None:
            out.extend(self._scan_tasks(tasks, stamp))
        if triggers is not None:
            out.extend(self._scan_triggers(triggers, stamp))
        if world is not None:
            out.extend(self._scan_world(world, stamp))
        if goals and tasks is not None:
            out.extend(self._scan_goal_blockage(tasks, goals, stamp))
        self._goal_texts = list(goals or [])
        return [c for c in out if c is not None]

    def _scan_goal_blockage(self, tasks: Any, goals: list[str],
                            stamp: float) -> list[AttentionCandidate]:
        """A stated goal whose supporting tasks keep failing may be blocked."""
        found = []
        task_list = list(getattr(tasks, "tasks", {}).values())
        max_retries = getattr(tasks, "max_retries", 3)
        for goal in goals:
            keywords = {t for t in goal.lower().split() if len(t) > 3}
            if not keywords:
                continue
            failing = [
                t for t in task_list
                if getattr(getattr(t, "state", ""), "value", "") == "failed"
                and keywords & set(getattr(t, "goal", "").lower().split())
                and getattr(t, "attempts", 0) >= max_retries]
            if failing:
                names = ", ".join(getattr(t, "goal", "?")[:60] for t in failing[:3])
                cand = self.notify(ProactiveEvent(
                    type="goal_changed", source="goal-monitor",
                    entity=goal[:80],
                    summary=f"goal potentially blocked: {len(failing)} "
                            f"supporting task(s) exhausted retries ({names})",
                    payload={"goal": goal,
                             "failed_tasks": [getattr(t, "task_id", "")
                                              for t in failing]},
                    confidence=0.75,
                    provenance={"failed_tasks": [getattr(t, "task_id", "")
                                                 for t in failing]},
                    timestamp=stamp))
                if cand is not None:
                    found.append(cand)
        return found

    def _scan_tasks(self, tasks: Any, stamp: float) -> list[AttentionCandidate]:
        found = []
        for task in list(getattr(tasks, "tasks", {}).values()):
            state = getattr(getattr(task, "state", ""), "value", "")
            if not isinstance(state, str):
                state = str(state)
            attempts = getattr(task, "attempts", 0)
            goal, tid = getattr(task, "goal", ""), getattr(task, "task_id", "")
            if state == "failed" and attempts >= getattr(tasks, "max_retries", 3):
                cand = self.notify(ProactiveEvent(
                    type="agent_failed", source="task-engine", entity=goal,
                    summary=f"task failed after {attempts} attempts: {goal[:80]}",
                    payload={"task_id": tid, "attempts": attempts},
                    confidence=0.85,
                    provenance={"task_id": tid}, timestamp=stamp))
            elif state in ("blocked", "waiting"):
                cand = self.notify(ProactiveEvent(
                    type="task_changed", source="task-engine", entity=goal,
                    summary=f"task {state}: {goal[:80]}",
                    payload={"task_id": tid, "state": state},
                    confidence=0.7,
                    provenance={"task_id": tid}, timestamp=stamp))
            else:
                continue
            if cand is not None:
                found.append(cand)
        return found

    def _scan_triggers(self, triggers: Any, stamp: float) -> list[AttentionCandidate]:
        found = []
        for fired in getattr(triggers, "fired", [])[-20:]:
            cand = self.notify(ProactiveEvent(
                type="schedule_triggered", source="trigger-engine",
                entity=str(fired.get("action", fired.get("trigger", ""))),
                summary=f"trigger fired: {fired.get('action', '?')}",
                payload=dict(fired), confidence=0.7,
                provenance={"trigger": fired.get("trigger", "")},
                timestamp=stamp))
            if cand is not None:
                found.append(cand)
        return found

    def _scan_world(self, world: Any, stamp: float) -> list[AttentionCandidate]:
        found = []
        changes = []
        try:
            tracker = getattr(world, "tracker", None)
            if tracker is None:
                tracker = getattr(world, "state", None)
            if tracker is not None and hasattr(tracker, "latest_changes"):
                changes = tracker.latest_changes(3) or []
        except Exception:
            changes = []
        for change in changes:
            describe = getattr(change, "describe", lambda: str(change))
            cand = self.notify(ProactiveEvent(
                type="world_changed", source="world-2.0",
                entity=str(getattr(change, "entity", "")),
                summary=describe()[:160],
                confidence=float(getattr(change, "confidence", 0.6)),
                provenance={"kind": getattr(change, "kind", "")},
                timestamp=stamp))
            if cand is not None:
                found.append(cand)
        return found

    # -- explain ----------------------------------------------------
    def explain(self, candidate_id: str) -> str:
        cand = self.candidates.get(candidate_id)
        if cand is None:
            return f"no candidate {candidate_id}"
        parts = [cand.explain()]
        decision = self.decisions.get(candidate_id)
        parts.append(decision.explain() if decision
                     else "no decision recorded yet")
        parts.append("attention weights: " + ", ".join(
            f"{f}={self.weights.get(f, 1.0):.2f}"
            for f in AttentionEngine.WEIGHT_FACTORS)
            + " (explicit user settings always win; see overrides)")
        return "\n".join(parts)

    def _quiet_tuple(self) -> tuple[int, int] | None:
        raw = self.overrides.get("quiet_hours")
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return (int(raw[0]), int(raw[1]))
        return None

    def status(self) -> dict[str, Any]:
        pending = [c for c in self.candidates.values() if c.status == "pending"]
        return {"candidates": len(self.candidates), "pending": len(pending),
                "decided": len(self.decisions),
                "notifications": len(self.notifications),
                "outcomes": len(self.outcomes),
                "weights": dict(self.weights),
                "learning_enabled": self.overrides.get("learning_enabled", True),
                "levels": {c.candidate_id: c.level for c in pending}}

    def _maybe_notify(self, decision: ProactiveDecision,
                      cand: AttentionCandidate) -> None:
        """Deliver INFORM/ASK decisions through the attached notifier, if any.

        Explicit user overrides always win: notifications_enabled off,
        quiet hours, per-dot preference, cooldowns and rate limits are
        applied here; adaptive weights never affect delivery.
        Delivery failures never affect the decision itself.
        """
        if self._notifier is None:
            return
        try:
            policy = getattr(self._notifier, "policy", None)
            if policy is not None:
                policy.enabled = bool(self.overrides.get(
                    "notifications_enabled", True))
                policy.quiet_hours = self._quiet_tuple()
                policy.cooldown_s = float(self.overrides.get(
                    "notification_cooldown_s", policy.cooldown_s))
                policy.max_per_hour = int(self.overrides.get(
                    "max_notifications_per_hour", policy.max_per_hour))
                per_dot = self.overrides.get("per_dot", {}) or {}
                dot_pref = per_dot.get(decision.source_dot, {})
                if isinstance(dot_pref, dict) and \
                        dot_pref.get("notifications") is False:
                    return
            from ..notify.notifications import Notification, scrub_notification
            payload = scrub_notification({
                "source_dot": "",
                "type": ("question" if decision.decision == DECISION_ASK
                         else "info"),
                "title": f"JARVIS noticed: {cand.type}",
                "message": decision.question or decision.notification,
                "priority": "high" if cand.level in ("high", "critical")
                else "normal",
                "dedup_key": f"proactive:{cand.fingerprint}",
                "related_event": cand.source_event_id,
                "evidence_refs": decision.evidence_refs,
                "requires_approval": decision.decision == DECISION_ASK,
                "expires_at": cand.expires_at,
            })
            notification = Notification(**payload)
            self._notifier.deliver(notification)
        except Exception:
            pass

    # -- notifier ---------------------------------------------------
    def set_notifier(self, notifier: Any) -> None:
        """Attach a notification dispatcher (see jarvis.notify)."""
        self._notifier = notifier

    def _maybe_notify(self, decision: ProactiveDecision,
                      candidate: AttentionCandidate) -> None:
        if self._notifier is None:
            return
        if decision.decision not in (DECISION_INFORM, DECISION_ASK):
            return
        try:
            self._notifier.deliver_decision(self, decision, candidate)
        except Exception:
            pass

    # -- overrides ----------------------------------------------------
    def set_override(self, key: str, value: Any) -> dict[str, Any]:
        """Explicit user setting. Unknown keys rejected, never inferred."""
        if key not in self.DEFAULT_OVERRIDES:
            raise KeyError(f"unknown override: {key}")
        if key == "quiet_hours" and value is not None:
            if (not isinstance(value, (list, tuple)) or len(value) != 2
                    or not all(isinstance(h, int) and 0 <= h <= 23
                               for h in value)):
                raise ValueError("quiet_hours must be [start_hour, end_hour]")
            value = [int(value[0]), int(value[1])]
        self.overrides[key] = value
        return dict(self.overrides)

    def reset_weights(self) -> dict[str, float]:
        """Restore default attention weights. History is preserved."""
        self.weights = {f: 1.0 for f in AttentionEngine.WEIGHT_FACTORS}
        self.weight_history.append(
            {"at": now(), "action": "reset", "weights": dict(self.weights)})
        return dict(self.weights)

    # -- outcomes + adaptive weights ------------------------------------
    def record_outcome(self, candidate_id: str, **fields: Any) -> dict[str, Any]:
        """Record an OBSERVED outcome. Only documented fields are stored.

        Useful/redundant/interacted/approved/ignored come from explicit
        user actions or verifiable task results — never inferred.
        """
        cand = self.candidates.get(candidate_id)
        if cand is None:
            raise KeyError(f"unknown candidate: {candidate_id}")
        unknown = set(fields) - set(self.OUTCOME_FIELDS)
        if unknown:
            raise ValueError(f"unknown outcome fields: {sorted(unknown)}")
        record = {"candidate_id": candidate_id,
                  "event_type": cand.type, "decision": None,
                  "at": now(), "applied": False}
        decision = self.decisions.get(candidate_id)
        if decision is not None:
            record["decision"] = decision.decision
        for key in self.OUTCOME_FIELDS:
            if key in fields:
                record[key] = fields[key]
        self.outcomes.append(record)
        self.outcomes = self.outcomes[-self.max_records:]
        return record

    def update_weights(self) -> list[dict[str, Any]]:
        """Apply small bounded updates from unapplied outcomes.

        Rules (transparent, conservative):
        - useful notification/interaction → +0.05 on factors that fired
        - ignored or explicitly useless → -0.05
        - bounds [0.5, 1.5]; learning toggle respected; security caps
          and thresholds in scoring are never touched.
        """
        applied: list[dict[str, Any]] = []
        if not self.overrides.get("learning_enabled", True):
            return applied
        for outcome in self.outcomes:
            if outcome.get("applied"):
                continue
            outcome["applied"] = True
            useful = bool(outcome.get("useful")) or bool(
                outcome.get("interacted")) or bool(outcome.get("approved"))
            # Explicit redundancy signals: ignored, or useful=False.
            redundant = (outcome.get("useful") is False) or (
                bool(outcome.get("ignored")) and not useful)
            if useful == redundant:
                continue  # no usable signal either way
            delta = 0.05 if useful else -0.05
            cand = self.candidates.get(outcome["candidate_id"])
            factors = self._factors_for(outcome.get("event_type", ""),
                                        cand)
            for factor in factors:
                old = self.weights.get(factor, 1.0)
                new = round(max(AttentionEngine.WEIGHT_MIN,
                                min(AttentionEngine.WEIGHT_MAX,
                                    old + delta)), 3)
                if new != old:
                    self.weights[factor] = new
                    applied.append({
                        "at": now(), "factor": factor,
                        "old": old, "new": new,
                        "candidate_id": outcome["candidate_id"],
                        "reason": ("positive outcome observed"
                                   if delta > 0 else
                                   "ignored/redundant outcome observed")})
        self.weight_history.extend(applied)
        return applied

    @staticmethod
    def _factors_for(event_type: str,
                     cand: Any | None) -> list[str]:
        """Which scoring factors participated. Conservative default: all
        additive factors share credit/blame equally."""
        factors = ["novelty"]
        if cand is not None:
            reasons = " ".join(getattr(cand, "reasons", []))
            if "recurring" in reasons:
                factors.append("recurrence")
            if "stated user goal" in reasons:
                factors.append("goal_relevance")
        return factors

    def explain_weights(self) -> str:
        lines = ["attention weights (bounded [0.5, 1.5]):"]
        for factor in AttentionEngine.WEIGHT_FACTORS:
            lines.append(f"  {factor}: {self.weights.get(factor, 1.0):.2f}")
        lines.append(f"learning: {'on' if self.overrides.get('learning_enabled', True) else 'off (explicit user setting)'}")
        recent = self.weight_history[-5:]
        if recent:
            lines.append("recent updates:")
            for entry in recent:
                lines.append(
                    f"  {entry.get('factor')}: {entry.get('old')} → "
                    f"{entry.get('new')} ({entry.get('reason')})")
        else:
            lines.append("no adaptive updates yet (defaults in effect)")
        return "\n".join(lines)


def _trusted_candidate(cand: AttentionCandidate) -> bool:
    return bool(cand.trusted)


def _team_for(event_type: str) -> str:
    return {"agent_failed": "debugging"}.get(event_type, "decision")
