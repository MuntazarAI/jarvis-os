"""Scheduled wakeups 3.2 — TriggerEngine → ProactiveEngine → Dot.

No threads, no polling loops, no background workers. `poll_schedules()`
is called on demand (CLI, loop hook, or tests) and processes whatever is
due *right now*, then returns. Safety gates, in order per schedule:

1. schedule exists, enabled, dot exists
2. dot in a wakeable state (READY, or COMPLETED recoverable)
3. emergency stop clear
4. cooldown + failure backoff satisfied
5. per-dot serialization (no overlapping activations)
6. per-poll wake cap (no storms)
7. TriggerEngine fires the due trigger (single source of firing truth)
8. ProactiveEngine evaluates the trigger event (may suppress)
9. DotRuntime.activate runs ONE bounded activation (policy-gated)

A schedule never executes tools. Only the runtime, through the
Orchestrator and PolicyEngine, can cause execution.
"""

from __future__ import annotations

from typing import Any

from ..core.types import now
from .model import DotStatus
from .manager import ACTIVE_STATES, TERMINAL_STATES

WAKE_ACTION_PREFIX = "dot:wake:"
MAX_WAKES_PER_POLL = 5

def _emergency_engaged(policy: Any) -> bool:
    if policy is None:
        return False
    try:
        return bool(policy._emergency_stop())
    except Exception:
        return False


def ensure_trigger(triggers: Any, schedule: Any) -> str:
    """Mirror a DotSchedule into TriggerEngine. Returns the action string."""
    action = f"{WAKE_ACTION_PREFIX}{schedule.dot_id}:{schedule.schedule_id}"
    for trig in triggers.triggers.values():
        if trig.action == action:
            return action
    from ..tasks.engine import Trigger
    kind, spec = _trigger_for(schedule)
    triggers.add(Trigger(kind=kind, spec=spec, action=action))
    return action


def _trigger_for(schedule: Any) -> tuple[str, dict[str, Any]]:
    if schedule.kind == "event":
        return "event", {"event_type": schedule.config.get("event_type", "")}
    if schedule.kind == "interval":
        return "schedule", {"every": float(schedule.config["every"])}
    # one-time / daily / weekly: one-shot fire at the computed next run.
    at = schedule.next_run or 0.0
    return "schedule", {"at": float(at)}


def sync_trigger(triggers: Any, schedule: Any) -> None:
    """Refresh the mirrored trigger spec after next_run changes."""
    action = f"{WAKE_ACTION_PREFIX}{schedule.dot_id}:{schedule.schedule_id}"
    kind, spec = _trigger_for(schedule)
    for trig in triggers.triggers.values():
        if trig.action == action:
            trig.kind = kind
            trig.spec = spec
            trig.enabled = schedule.enabled
            return
    ensure_trigger(triggers, schedule)


def poll_schedules(manager: Any, triggers: Any, proactive: Any,
                   now_ts: float | None = None,
                   signals: dict[str, Any] | None = None,
                   policy: Any = None, bus: Any = None,
                   activate=None) -> list[dict[str, Any]]:
    """Evaluate due schedules once. Returns one report per schedule checked.

    `activate` is an optional callable(dot, reason, event) -> result used
    to run the bounded activation; when None, due wakes stop at the
    ProactiveEngine decision (dry-run mode, still honest).
    """
    from .schedule import compute_next
    stamp = now_ts if now_ts is not None else now()
    signals = dict(signals or {})
    signals.setdefault("now", stamp)
    reports: list[dict[str, Any]] = []
    if _emergency_engaged(policy):
        return [{"status": "blocked", "reason": "emergency stop engaged"}]

    wakes = 0
    for sched in sorted(manager.list_schedules(), key=lambda s: s.created_at):
        if wakes >= MAX_WAKES_PER_POLL:
            reports.append({"schedule_id": sched.schedule_id,
                            "status": "skipped",
                            "reason": "per-poll wake cap reached"})
            continue
        reports.append(_poll_one(manager, triggers, proactive, sched, stamp,
                                 signals, policy, bus, activate))
        if reports[-1]["status"] == "activated":
            wakes += 1
    try:
        manager.persist()
    except Exception:
        pass
    return reports


def _poll_one(manager: Any, triggers: Any, proactive: Any, sched: Any,
              stamp: float, signals: dict[str, Any], policy: Any,
              bus: Any, activate: Any) -> dict[str, Any]:
    from .schedule import compute_next
    base = {"schedule_id": sched.schedule_id, "dot_id": sched.dot_id}
    if not sched.enabled:
        return {**base, "status": "skipped", "reason": "schedule disabled"}
    dot = manager.get(sched.dot_id)
    if dot is None:
        return {**base, "status": "skipped",
                "reason": "stale schedule: dot no longer exists"}
    if dot.status in (DotStatus.STOPPED, DotStatus.PAUSED):
        return {**base, "status": "skipped",
                "reason": f"dot is {dot.status.value}"}
    if sched.max_activations and sched.activations >= sched.max_activations:
        return {**base, "status": "skipped",
                "reason": "max activations reached"}
    # Cooldown + failure backoff (exponential, capped at 8x).
    effective_cooldown = sched.cooldown_s * (2 ** min(sched.failure_count, 3))
    if sched.last_run and stamp - sched.last_run < effective_cooldown:
        return {**base, "status": "skipped", "reason": "cooldown active"}
    # Serialize per dot: no overlapping activations.
    if dot.status in ACTIVE_STATES or manager.pending(dot.dot_id):
        return {**base, "status": "skipped",
                "reason": "dot busy or activation already pending"}
    # Terminal dots restart a fresh cycle via recover(); failed/blocked
    # dots never auto-restart (needs a human).
    if dot.status == DotStatus.COMPLETED:
        try:
            manager.recover(dot.dot_id,
                            reason=f"scheduled wake {sched.schedule_id}")
            dot = manager.get(sched.dot_id)
        except Exception as exc:
            return {**base, "status": "blocked",
                    "reason": f"recover failed: {exc}"}
    elif dot.status != DotStatus.READY:
        return {**base, "status": "skipped",
                "reason": f"dot is {dot.status.value}"}
    # Due check + TriggerEngine firing (single source of truth).
    if sched.kind != "event":
        if sched.next_run is None or stamp < sched.next_run:
            return {**base, "status": "skipped", "reason": "not due"}
    ensure_trigger(triggers, sched)
    fired = triggers.poll(signals)
    mine = [t for t in fired if t.action ==
            f"{WAKE_ACTION_PREFIX}{sched.dot_id}:{sched.schedule_id}"]
    if not mine:
        return {**base, "status": "skipped",
                "reason": "trigger did not fire"}
    return _fire(manager, proactive, sched, dot, stamp, signals, policy,
                 bus, activate)


def fire_dot(manager: Any, proactive: Any, dot: Any, summary: str,
             runtime: Any, ctx: Any, policy: Any = None,
             event: dict[str, Any] | None = None) -> dict[str, Any]:
    """Manual wake for one Dot (explicit user intent).

    Still gated: dot must exist and be wakeable, emergency stop blocks,
    event content is injection-scanned, and the activation runs through
    DotRuntime → Orchestrator → PolicyEngine. The proactive notify/decide
    pair is recorded for audit but an explicit manual wake is not
    suppressed by low attention scores.
    """
    from ..proactive.engine import ProactiveEvent
    base: dict[str, Any] = {"dot_id": dot.dot_id}
    if dot.status in (DotStatus.STOPPED, DotStatus.PAUSED):
        return {**base, "status": "skipped",
                "reason": f"dot is {dot.status.value}"}
    if dot.status == DotStatus.COMPLETED:
        try:
            manager.recover(dot.dot_id, reason="manual wake")
            dot = manager.get(dot.dot_id)
        except Exception as exc:
            return {**base, "status": "blocked",
                    "reason": f"recover failed: {exc}"}
    elif dot.status != DotStatus.READY:
        return {**base, "status": "skipped",
                "reason": f"dot is {dot.status.value}"}
    if _emergency_engaged(policy):
        return {**base, "status": "blocked",
                "reason": "emergency stop engaged"}
    evt = dict(event or {})
    evt.setdefault("type", "manual")
    evt.setdefault("entity", dot.name)
    evt.setdefault("summary", summary)
    evt.setdefault("trusted", True)
    clean, why = _event_content_ok(evt)
    if not clean:
        return {**base, "status": "blocked", "reason": why}
    pro_event = ProactiveEvent(
        type="schedule_triggered" if evt["type"] == "manual" else evt["type"],
        source="dot-wake", entity=dot.name, summary=evt["summary"],
        payload={"dot_id": dot.dot_id, "manual": True},
        confidence=0.9,
        provenance={"dot_id": dot.dot_id, "manual": True})
    candidate = proactive.notify(pro_event)
    if candidate is not None:
        decision = proactive.decide(
            candidate.candidate_id,
            emergency_stop=_emergency_engaged(policy))
        if decision is not None:
            decision.source_dot = dot.dot_id
    try:
        result = runtime.activate(
            dot, reason=f"manual wake: {summary[:80]}", ctx=ctx,
            event=evt)
    except Exception as exc:
        return {**base, "status": "failed",
                "reason": f"activation error: {type(exc).__name__}: {exc}"}
    manager.persist()
    outcome = result.outcome if hasattr(result, "outcome") else "unknown"
    return {**base, "status": "activated" if outcome == "completed"
            else outcome,
            "reason": getattr(result, "reason", "")}


def _event_content_ok(event: dict[str, Any]) -> tuple[bool, str]:
    try:
        from ..security.guards import scan_injection
    except Exception:
        return True, ""
    text = f"{event.get('summary', '')} {event.get('entity', '')}"
    result = scan_injection(text)
    if not result.get("clean", True):
        return False, f"injection markers in trigger: {result.get('verdict')}"
    return True, ""


def _fire(manager: Any, proactive: Any, sched: Any, dot: Any, stamp: float,
          signals: dict[str, Any], policy: Any, bus: Any,
          activate: Any) -> dict[str, Any]:
    from ..proactive.engine import ProactiveEvent
    base = {"schedule_id": sched.schedule_id, "dot_id": dot.dot_id}
    event = ProactiveEvent(
        type="schedule_triggered", source="dot-schedule",
        entity=dot.name,
        summary=f"scheduled wake for dot {dot.name}: {sched.reason or sched.kind}",
        payload={"dot_id": dot.dot_id, "schedule_id": sched.schedule_id,
                 "kind": sched.kind},
        confidence=0.8,
        provenance={"schedule_id": sched.schedule_id,
                    "dot_id": dot.dot_id},
        timestamp=stamp)
    clean, why = _event_content_ok(
        {"summary": event.summary, "entity": event.entity})
    if not clean:
        _advance(sched, stamp, manager)
        return {**base, "status": "blocked", "reason": why}
    if bus is not None:
        try:
            from ..events.store import Event as BusEvent
            bus.publish(BusEvent(type="schedule_triggered",
                                 payload=event.to_dict()))
        except Exception:
            pass
    candidate = proactive.notify(event)
    if candidate is None:
        _advance(sched, stamp, manager)
        return {**base, "status": "skipped",
                "reason": "proactive dedup: cooled-down duplicate"}
    decision = proactive.decide(candidate.candidate_id,
                                emergency_stop=_emergency_engaged(policy))
    if decision is not None:
        decision.source_dot = dot.dot_id
    if decision is None or decision.decision == "IGNORE":
        _advance(sched, stamp, manager)
        return {**base, "status": "suppressed",
                "reason": "proactive attention: IGNORE"}
    # An enabled schedule is standing user intent to wake: only IGNORE
    # suppresses. ASK still surfaces its question (via notification) but
    # does not block — execution itself stays behind Orchestrator/policy.
    question = decision.question if decision.decision == "ASK" else ""
    if decision.decision == "ASK":
        base["attention_question"] = decision.question
    if activate is None:
        _advance(sched, stamp, manager)
        return {**base, "status": "proposed",
                "reason": "dry-run: no runtime bound",
                "candidate_id": candidate.candidate_id}
    # The schedule itself is the subscription: this wake targets a known
    # dot, so register (and consume) a schedule-scoped pending marker
    # directly instead of re-matching subscriptions.
    marker = f"sched:{sched.schedule_id}:{int(stamp)}"
    if manager.pending(dot.dot_id) or not manager.mark_pending(
            dot.dot_id, marker):
        _advance(sched, stamp, manager)
        return {**base, "status": "skipped",
                "reason": "dot has a pending activation already"}
    manager.consume_pending(dot.dot_id, marker)
    try:
        result = activate(dot, f"scheduled wake {sched.schedule_id}",
                          event.to_dict())
    except Exception as exc:
        sched.failure_count += 1
        _advance(sched, stamp, manager)
        return {**base, "status": "failed",
                "reason": f"activation error: {type(exc).__name__}: {exc}"}
    outcome = result.outcome if hasattr(result, "outcome") else "unknown"
    sched.activations += 1
    if outcome in ("failed",):
        sched.failure_count += 1
    else:
        sched.failure_count = 0
    _advance(sched, stamp, manager)
    return {**base, "status": "activated" if outcome == "completed"
            else outcome,
            "reason": getattr(result, "reason", ""),
            "candidate_id": candidate.candidate_id}


def _advance(sched: Any, stamp: float, manager: Any) -> None:
    """Bookkeeping after any firing: last_run, next_run, one-time retire."""
    from .schedule import compute_next
    sched.last_run = stamp
    if sched.kind == "one-time":
        sched.enabled = False
        sched.next_run = None
        return
    if sched.kind in ("interval", "daily", "weekly"):
        sched.next_run = compute_next(
            sched.kind, sched.config, sched.timezone, stamp,
            created_at=sched.created_at)
