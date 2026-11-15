"""The status snapshot (read-only).

One JSON snapshot (`build_board`) assembled ONLY from existing
subsystems — status, missions HUD, durable tasks, voice config,
service heartbeat, approvals, events. It is the data behind whatever
interface someone builds on top of it.

Rules: read-only (no POST route), defensive (any failing subsystem
contributes an explicit `unknown` marker, the snapshot never raises),
and secret-scrubbed (tokens/keys never enter the payload).
"""

from __future__ import annotations

import time
from typing import Any

BOARD_VERSION = 1

_SECRET_HINTS = ("token", "secret", "password", "api_key", "apikey",
                 "authorization", "private_key")


def _safe(fn: Any, fallback: Any) -> Any:
    try:
        return fn()
    except Exception:
        return fallback


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key).lower()
            if name == "token_hint":
                # Designed for display (truncated at the source).
                out[key] = str(item)[:12]
            elif any(hint in name for hint in _SECRET_HINTS):
                out[key] = "[redacted]"
            else:
                out[key] = _scrub(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(item, depth + 1) for item in value[:50]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def _home(jarvis: Any) -> str:
    return str(_safe(lambda: jarvis.config.paths.home, "") or "")


def _service_info(home: str) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        from ..service.runtime import BackgroundService, read_pid_info
        info = read_pid_info(home) if home else {}
        heart = _safe(lambda: BackgroundService(home).read_heartbeat()
                      if home else {}, {})
        return {"running": bool(info.get("running")),
                "pid": info.get("pid"),
                "heartbeat_age_s": heart.get("age_s"),
                "heartbeat_state": heart.get("state", "unknown")}
    return _safe(_read, {"running": "unknown"})


def _presence_info(home: str) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        from ..autonomy.presence import PresenceRuntime
        return PresenceRuntime(home).health() if home else {}
    return _safe(_read, {"status": "unknown"})


def _durable_info(home: str) -> Any:
    def _read() -> list[dict[str, Any]]:
        from ..durable import TaskStore
        store = TaskStore(home) if home else None
        if store is None:
            return []
        if store.corrupt:
            return [{"status": "unknown",
                     "detail": f"store fail-closed: {store.corrupt}"}]
        rows = []
        for task in store.list():
            done = sum(1 for s in task.steps
                       if s.state.value == "succeeded")
            rows.append({"task_id": task.task_id,
                         "title": task.title[:120],
                         "state": task.state.value,
                         "progress": f"{done}/{len(task.steps)}"})
        return rows[-20:]
    return _safe(_read, {"status": "unknown"})


def _voice_info(jarvis: Any) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        cfg = jarvis.config.voice
        return {"provider": str(getattr(cfg, "tts_provider",
                                       "unknown"))[:40],
                "profile": str(getattr(cfg, "profile", ""))[:40],
                "style": str(getattr(cfg, "style", ""))[:40]}
    return _safe(_read, {"status": "unknown"})


def _missions_info(jarvis: Any) -> Any:
    def _read() -> Any:
        from ..missions.hud import HudContext, build_snapshot
        world = getattr(jarvis, "world", None)
        policy = getattr(jarvis, "policy", None)
        return build_snapshot(HudContext(
            missions=getattr(jarvis, "missions", None),
            dots=getattr(jarvis, "dots", None),
            tasks=getattr(jarvis, "tasks", None),
            notifier=getattr(jarvis, "notifier", None),
            policy=policy,
            system_state=_safe(
                lambda: world.system_state, None),
            emergency_engaged=_safe(
                lambda: bool(policy._emergency_stop()), False),
            proposals=getattr(jarvis, "missions", None)))
    return _safe(_read, {"status": "unknown"})


def _approvals(policy: Any) -> list[dict[str, Any]]:
    def _read() -> list[dict[str, Any]]:
        records = getattr(policy, "approvals", None)
        if not isinstance(records, dict):
            return []
        out = []
        for token, record in records.items():
            if not isinstance(record, dict):
                continue
            if record.get("status") != "pending":
                continue
            out.append({"action": str(record.get("action", ""))[:120],
                        "requested_at": record.get("requested_at", 0.0),
                        "token_hint": str(token)[:8] + "…"})
        return out[:10]
    return _safe(_read, [])


def _reach_info(jarvis: Any) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        from ..agents.reach import reach_summary
        return reach_summary(jarvis)
    return _safe(_read, {"status": "unknown"})


def _security_info(home: str) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        from ..security.intel import board_security_info
        return board_security_info(home)
    return _safe(_read, {"posture": "unknown"})


def _models_info(jarvis: Any) -> dict[str, Any]:
    """Which model provider answers which kind of work, and is it up."""
    def _snapshot() -> dict[str, Any]:
        from ..models.backends import (build_client, configured_backends,
                                       resolve_selection)
        cfg = getattr(jarvis, "config", None)
        selection = resolve_selection(cfg)
        backends = []
        for spec in configured_backends(cfg):
            alive = False
            count = 0
            client = build_client(spec, cfg)
            if client is not None:
                try:
                    available = client.models()
                    count = len(available)
                    alive = bool(available) or client.alive()
                except Exception:
                    alive = False
            backends.append({
                "name": spec.name,
                "type": spec.type,
                "local": spec.local,
                "alive": alive,
                "models": count,
                "serves": sorted(k for k, v in selection.items()
                                 if v[0] == spec.name),
            })
        return {
            "backends": backends,
            "selection": {kind: f"{name}:{model}"
                          for kind, (name, model) in selection.items()},
            "local_only": bool(getattr(cfg.policy, "local_only", True))
            if cfg is not None else True,
        }
    return _safe(_snapshot, {"status": "unknown"})


def build_board(jarvis: Any) -> dict[str, Any]:
    """Assemble the snapshot. Never raises; unknowns are explicit."""
    try:
        home = _home(jarvis)
        policy = getattr(jarvis, "policy", None)
        events = getattr(jarvis, "events", None)
        snapshot = {
            "board": BOARD_VERSION,
            "generated_at": time.time(),
            "service": _service_info(home),
            "presence": _presence_info(home),
            "system": _safe(lambda: jarvis.status(),
                            {"status": "unknown"}),
            "missions": _missions_info(jarvis),
            "durable": _durable_info(home),
            "voice": _voice_info(jarvis),
            "models": _models_info(jarvis),
            "approvals": _approvals(policy),
            "reach": _reach_info(jarvis),
            "security": _security_info(home),
            "events": _safe(lambda: {
                "count": events.count(),
                "types": events.types()}, {"status": "unknown"}),
            "policy": {
                "emergency": _safe(
                    lambda: bool(policy._emergency_stop()), "unknown"),
                "conflicts": _safe(lambda: policy.conflicts(),
                                   "unknown"),
            },
        }
        return _scrub(snapshot)
    except Exception as exc:
        return {"board": BOARD_VERSION, "status": "unknown",
                "error": f"{type(exc).__name__}"}


__all__ = ["build_board", "BOARD_VERSION"]
