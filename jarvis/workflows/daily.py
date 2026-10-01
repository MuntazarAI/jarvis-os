"""Daily-driver workflows: status, continue, changes, tests, errors, remember."""

from __future__ import annotations

from typing import Any

from ..memory.consolidation import summarize_text


def what_am_i_working_on(jarvis: Any, limit: int = 8) -> dict[str, Any]:
    """Recent episodes + open tasks, summarized."""
    episodes = jarvis.palace.all(tier="episodic", limit=limit)
    texts = [m.content for m in episodes]
    open_tasks = [t for t in jarvis.tasks.tasks.values()
                  if t.state.value in ("queued", "running", "waiting", "planning")]
    return {"summary": summarize_text(texts) if texts else "nothing recorded yet",
            "recent": texts[:5],
            "open_tasks": [(t.task_id, t.goal) for t in open_tasks[:5]]}


def continue_project(jarvis: Any, name: str = "") -> dict[str, Any]:
    """Reconstruct project state: episodes, facts, open tasks, recent errors."""
    query = name or "project"
    recalled = jarvis.palace.search(query, limit=12)
    episodes = [m.content for m, _ in recalled if m.tier == "episodic"][:5]
    facts = [m.content for m, _ in recalled if m.tier in ("semantic", "fact")] [:5]
    if not facts:
        facts = [m.content for m, _ in
                 jarvis.palace.search(f"{query} decision", limit=6)
                 if m.tier == "semantic"][:5]
    open_tasks = [(t.task_id, t.goal) for t in jarvis.tasks.tasks.values()
                  if t.state.value in ("queued", "running", "waiting", "planning")][:5]
    errors = [m.content for m, _ in jarvis.palace.search("error failed", limit=5)][:3]
    related = jarvis.graph.related_entities(name, limit=5) if name else []
    return {"project": name or "latest activity",
            "recent_work": episodes, "decisions": facts,
            "open_tasks": open_tasks, "recent_errors": errors,
            "related": related}


def what_changed_since(jarvis: Any, hours: float = 24.0) -> dict[str, Any]:
    """Memory + world events inside the window."""
    from ..core.types import now
    start = now() - hours * 3600
    mems = jarvis.palace.temporal_search(start, now(), limit=30)
    events = [e.description for e in jarvis.world.timeline(start=start)]
    gaps = jarvis.world.timeline_gaps()
    return {"since_hours": hours,
            "memory_events": [m.content[:160] for m in mems[:10]],
            "world_events": events[-10:],
            "timeline_gaps": gaps[:5]}


def run_tests(jarvis: Any, path: str = ".", timeout: float = 300.0) -> dict[str, Any]:
    """Run pytest through the policy gate. Returns a parsed summary."""
    from ..core.types import ActionPlan
    plan = ActionPlan(action="terminal_run run project tests",
                      args={"command": f"python3 -m pytest {path} -q",
                            "timeout": timeout},
                      required_permissions=["exec"])
    decision = jarvis.policy.evaluate("jarvis", plan)
    if not decision.allow:
        return {"ok": False, "error": "blocked: " + "; ".join(decision.reasons)}
    if decision.requires_approval:
        token = jarvis.policy.request_approval("jarvis", plan, decision)
        return {"ok": False, "needs_approval": token,
                "risk": decision.risk, "reasons": decision.reasons}
    result = jarvis.tools.call("terminal_run", command=f"python3 -m pytest {path} -q",
                               timeout=timeout)
    if not result.ok:
        return {"ok": False, "error": result.error}
    out = str(result.output.get("stdout", ""))
    tail = out.strip().splitlines()[-3:] if out.strip() else []
    passed = "passed" in out
    jarvis.palace.store_episode(f"ran tests in {path}: {'PASS' if passed else 'CHECK'}",
                                room="Experiences", importance=0.6)
    return {"ok": True, "passed": passed, "tail": tail}


def explain_error(jarvis: Any, error_text: str) -> dict[str, Any]:
    """Failure analysis + similar past episodes + model explanation."""
    analysis = jarvis.reflector.analyze_failure("reported error", error_text)
    similar = [m.content[:200] for m, _ in
               jarvis.palace.search(error_text[:120], limit=4)]
    explanation = ""
    try:
        result = jarvis.router.complete(
            task="explain error",
            prompt=(f"Explain this error briefly and suggest the most likely fix.\n"
                    f"Error: {error_text[:800]}\n"
                    f"Likely cause from analysis: {analysis['likely_cause']}"),
            system="You are a concise debugging assistant.")
        if result.get("ok"):
            explanation = str(result.get("text", "")).strip()
    except Exception:
        explanation = ""
    return {"likely_cause": analysis["likely_cause"],
            "suggested_fix": analysis["suggested_fix"],
            "similar_past": similar, "explanation": explanation}


def remember_this(jarvis: Any, text: str, room: str = "Knowledge Library") -> dict[str, Any]:
    mem = jarvis.palace.store_fact(text, room=room, source="user", importance=0.85)
    return {"ok": True, "id": mem.id, "room": room}
