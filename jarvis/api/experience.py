"""Experience snapshot (Experience Layer 1.0).

One read-only assembly over EXISTING subsystems only: status, missions
HUD, durable tasks, approvals, policy, security history, world config,
voice config, service heartbeat, devices, notifications, EventStore
timeline. No new stores, no new buses, no new state machines — the
presence indicator is a pure VIEW mapping over real states, and every
failing subsystem contributes an explicit `unknown` marker.
"""

from __future__ import annotations

import time
from typing import Any

from .board import _durable_info, _scrub, _service_info, _voice_info

EXPERIENCE_VERSION = 1

# Presence is presentation, not a state machine: a pure function of
# real states, highest priority first. LISTENING/SPEAKING are omitted
# — no live voice-loop flag exists, and we never claim it.
PRESENCE_ORDER = ("E_STOP", "ALERT", "WAITING", "EXECUTING",
                  "VERIFYING", "PLANNING", "IDLE")


def presence_state(*, emergency: bool = False,
                   failed_tasks: int = 0,
                   policy_conflicts: int = 0,
                   approvals_pending: int = 0,
                   running_tasks: int = 0,
                   verifying_tasks: int = 0,
                   ready_tasks: int = 0) -> str:
    """Map real states to one presence indicator. Pure function."""
    if emergency:
        return "E_STOP"
    if failed_tasks > 0 or policy_conflicts > 0:
        return "ALERT"
    if approvals_pending > 0:
        return "WAITING"
    if running_tasks > 0:
        return "EXECUTING"
    if verifying_tasks > 0:
        return "VERIFYING"
    if ready_tasks > 0:
        return "PLANNING"
    return "IDLE"


def _safe(fn: Any, fallback: Any) -> Any:
    try:
        return fn()
    except Exception:
        return fallback


def _mesh(jarvis: Any) -> list[dict[str, Any]]:
    def _read() -> list[dict[str, Any]]:
        system = jarvis.status()
        agents = (system.get("agents", {}) or {}).get("agents", [])
        rows = []
        for agent in agents[:16]:
            rows.append({"name": str(agent.get("name", "?"))[:40],
                         "state": str(agent.get("state", "idle"))[:20],
                         "tasks_done": agent.get("tasks_done", 0),
                         "tasks_failed": agent.get("tasks_failed", 0)})
        return rows
    return _safe(_read, [])


def _approvals(jarvis: Any) -> list[dict[str, Any]]:
    def _read() -> list[dict[str, Any]]:
        policy = getattr(jarvis, "policy", None)
        try:
            loader = getattr(policy, "_load_approvals", None)
            if callable(loader):
                loader()  # file-seeded approvals (e.g. after restart)
        except Exception:
            pass
        records = getattr(policy, "approvals", None)
        if not isinstance(records, dict):
            return []
        out = []
        for token, record in records.items():
            if not isinstance(record, dict):
                continue
            if record.get("status") != "pending":
                continue
            out.append({"action": str(record.get("action",
                                                ""))[:120],
                        "risk": str(record.get("risk", ""))[:20],
                        "requested_at": record.get("requested_at", 0.0),
                        "token_hint": str(token)[:8] + "…"})
        return out[:10]
    return _safe(_read, [])


def _policy(jarvis: Any) -> dict[str, Any]:
    policy = getattr(jarvis, "policy", None)
    return {
        "emergency": _safe(
            lambda: bool(policy._emergency_stop()), "unknown"),
        "conflicts": _safe(lambda: policy.conflicts(), "unknown"),
        "indicator": _safe(
            lambda: ("E-STOP" if policy._emergency_stop()
                     else "SAFE"), "unknown"),
    }


def _security(home: str) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        from ..security.strix import read_history, strix_binary
        history = read_history(home) if home else []
        return {"dynamic_available": bool(strix_binary()),
                "recent_scans": history[-5:],
                "static": "jarvis security review (offline, no LLM)"}
    return _safe(_read, {"status": "unknown"})


def _world(jarvis: Any) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        cfg = getattr(getattr(jarvis, "config", None), "world", None)
        topics = list(getattr(cfg, "topics", []) or [])[:20]
        from ..worldintel.sources import SourceRegistry
        sources = len(SourceRegistry().list()
                      if hasattr(SourceRegistry(), "list") else [])
        return {"topics": [str(t)[:80] for t in topics],
                "sources_configured": sources,
                "live": "unknown — refresh on demand; "
                        "external items are untrusted input"}
    return _safe(_read, {"status": "unknown"})


def _devices(jarvis: Any) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        fabric = getattr(jarvis, "device_fabric", None)
        status = fabric.status() if hasattr(fabric, "status") else {}
        if not isinstance(status, dict) or not status:
            return {"state": "not connected"}
        nodes = status.get("devices", "?")
        transport = status.get("transport", {})
        if isinstance(transport, dict):
            transport = transport.get("transport", "?")
        return {"state": "connected" if nodes else "not connected",
                "devices": nodes,
                "transport": str(transport)[:40]}
    return _safe(_read, {"state": "unknown"})


def _notifications(jarvis: Any, durable: Any,
                   approvals: list) -> list[dict[str, Any]]:
    def _read() -> list[dict[str, Any]]:
        notes: dict[str, dict[str, Any]] = {}
        proactive = getattr(jarvis, "proactive", None)
        items = getattr(proactive, "notifications", None) or []
        for item in items[-10:]:
            if isinstance(item, dict):
                key = str(item.get("text", ""))[:120]
                notes[f"proactive:{key}"] = {
                    "category": "system",
                    "text": key,
                    "level": str(item.get("level", ""))[:20]}
        for task in (durable if isinstance(durable, list) else []):
            if isinstance(task, dict) and task.get("state") in (
                    "failed",):
                notes[f"task:{task.get('task_id')}"] = {
                    "category": "task failed",
                    "text": f"{task.get('task_id')}: "
                            f"{task.get('title', '')}"[:120],
                    "level": "high"}
        if approvals:
            notes["approvals:pending"] = {
                "category": "approval needed",
                "text": f"{len(approvals)} approval(s) waiting",
                "level": "high"}
        return list(notes.values())[-15:]
    return _safe(_read, [])


def _timeline(jarvis: Any, limit: int = 30) -> list[dict[str, Any]]:
    def _read() -> list[dict[str, Any]]:
        events = getattr(jarvis, "events", None)
        last = int(events.last_seq())
        rows = []
        for event in events.stream(
                since=max(0, last - limit), limit=limit):
            payload = getattr(event, "payload", {})
            summary = ""
            if isinstance(payload, dict):
                for key in ("input", "action", "outcome", "detail",
                            "subject", "error"):
                    if payload.get(key):
                        summary = str(payload[key])[:160]
                        break
            rows.append({"seq": getattr(event, "seq", 0),
                         "type": str(getattr(event, "type",
                                             "?"))[:80],
                         "at": getattr(event, "timestamp", 0.0),
                         "correlation_id": str(
                             getattr(event, "correlation_id",
                                     ""))[:40],
                         "summary": summary})
        return rows
    return _safe(_read, [])


def build_experience(jarvis: Any) -> dict[str, Any]:
    """Assemble the command-center snapshot. Never raises."""
    try:
        from ..missions.hud import HudContext, build_snapshot
        home = ""
        try:
            home = str(jarvis.config.paths.home)
        except Exception:
            pass
        policy = getattr(jarvis, "policy", None)
        world = getattr(jarvis, "world", None)
        missions = _safe(lambda: build_snapshot(HudContext(
            missions=getattr(jarvis, "missions", None),
            dots=getattr(jarvis, "dots", None),
            tasks=getattr(jarvis, "tasks", None),
            notifier=getattr(jarvis, "notifier", None),
            policy=policy,
            system_state=_safe(lambda: world.system_state, None),
            emergency_engaged=_safe(
                lambda: bool(policy._emergency_stop()), False),
            proposals=getattr(jarvis, "missions", None))),
            {"status": "unknown"})
        durable = _durable_info(home)
        counts = {"ready": 0, "running": 0, "verifying": 0,
                  "failed": 0}
        if isinstance(durable, list):
            for task in durable:
                state = task.get("state", "")
                if state == "ready":
                    counts["ready"] += 1
                elif state == "running":
                    counts["running"] += 1
                elif state == "verifying":
                    counts["verifying"] += 1
                elif state == "failed":
                    counts["failed"] += 1
        approvals = _approvals(jarvis)
        policy_info = _policy(jarvis)
        conflicts = policy_info["conflicts"]
        snapshot = {
            "experience": EXPERIENCE_VERSION,
            "generated_at": time.time(),
            "presence": presence_state(
                emergency=policy_info["emergency"] is True,
                failed_tasks=counts["failed"],
                policy_conflicts=(conflicts
                                  if isinstance(conflicts, int) else 0),
                approvals_pending=len(approvals),
                running_tasks=counts["running"],
                verifying_tasks=counts["verifying"],
                ready_tasks=counts["ready"]),
            "system": _safe(lambda: jarvis.status(),
                            {"status": "unknown"}),
            "mesh": _mesh(jarvis),
            "missions": missions,
            "durable": durable,
            "task_counts": counts,
            "approvals": approvals,
            "policy": policy_info,
            "security": _security(home),
            "world": _world(jarvis),
            "voice": _voice_info(jarvis),
            "service": _service_info(home),
            "devices": _devices(jarvis),
            "notifications": [],
            "timeline": _timeline(jarvis),
            "settings_mode": "read-only in 1.0 — edit config files; "
                             "no duplicate config store",
        }
        snapshot["notifications"] = _notifications(
            jarvis, durable, approvals)
        return _scrub(snapshot)
    except Exception as exc:
        return {"experience": EXPERIENCE_VERSION, "status": "unknown",
                "error": f"{type(exc).__name__}"}


__all__ = ["build_experience", "presence_state", "EXPERIENCE_VERSION",
           "PRESENCE_ORDER"]
