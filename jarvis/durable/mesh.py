"""Mesh binding (Durable Autonomous Tasks 10).

Durable steps execute through the EXISTING agent mesh —
Orchestrator bound to the loop's live subsystems (registry, planner,
policy, tools, router, palace, graph). This module only adapts shapes:
mesh result -> executor contract. It owns no planning, tools, policy,
or verification logic of its own.

Honesty rule: a step is `verified` only when the blackboard carries
an explicit `verification` verdict of `verified`. A merely successful
run is `partial` — worked, not independently verified — and the
runner checkpoints only `verified` side effects as confirmed.
"""

from __future__ import annotations

from typing import Any


def mesh_executor(jarvis: Any):
    """Build a step executor bound to a live Jarvis loop/session."""

    def _execute(task: Any, step: Any) -> dict[str, Any]:
        title = str(getattr(step, "title", "") or "").strip()
        if not title:
            return {"ok": False, "error": "empty step",
                    "kind": "permanent", "verification": "failed"}
        if title.lower().startswith("note:"):
            # Record-only step: no tools, no side effects to verify.
            return {"ok": True, "verification": "verified",
                    "side_effects": [],
                    "output_ref": title[5:].strip()[:500]}
        try:
            orchestrator = jarvis._build_orchestrator()
        except Exception as exc:
            return {"ok": False,
                    "error": f"orchestrator unavailable: "
                             f"{type(exc).__name__}",
                    "kind": "unknown", "verification": "unknown"}
        try:
            result = orchestrator.run(
                goal=title, task_id=f"{task.task_id}:"
                                    f"{getattr(step, 'step_id', '')}")
        except Exception as exc:
            return {"ok": False,
                    "error": f"mesh crashed: {type(exc).__name__}",
                    "kind": "unknown", "verification": "unknown"}
        if not isinstance(result, dict):
            return {"ok": False, "error": "bad mesh result",
                    "kind": "unknown", "verification": "unknown"}
        status = str(result.get("status", "failed"))
        failure = str(result.get("failure", ""))[:500]
        if status == "timeout":
            return {"ok": False, "error": failure or "mesh timeout",
                    "kind": "timeout", "verification": "unknown"}
        if status == "cancelled":
            return {"ok": False, "error": failure or "mesh cancelled",
                    "kind": "transient", "verification": "unknown"}
        if not result.get("ok"):
            return {"ok": False, "error": failure or "mesh failed",
                    "kind": "permanent", "verification": "failed"}
        verdict = _board_verdict(result.get("blackboard"))
        verified = verdict == "verified"
        return {"ok": True,
                "verification": "verified" if verified else "partial",
                "side_effects": [],
                "output_ref": str(result.get("outcome", ""))[:500]}

    return _execute


def _board_verdict(blackboard: Any) -> str:
    try:
        sections = (blackboard or {}).get("sections", blackboard or {})
        entries = sections.get("verification", []) or []
        if not entries:
            return ""
        last = entries[-1]
        content = last.get("content", {}) if isinstance(
            last, dict) else {}
        return str(content.get("verdict", ""))
    except Exception:
        return ""


__all__ = ["mesh_executor"]
