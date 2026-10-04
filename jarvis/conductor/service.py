"""Conductor service: route then dispatch into existing paths (1.0).

The service owns routing, clarification, dispatch construction, and
result normalization. It owns NO authorization, planning, execution,
memory, research, devices, or voice synthesis — every target below is
an existing subsystem. PolicyEngine (via those subsystems) decides.
"""

from __future__ import annotations

import time
from typing import Any

from ..events.store import Event
from .router import CONFIDENCE_FLOOR, RouteDecision, route

TEAM_FOR_INTENT = {
    "RESEARCH": "research",
    "DEBUGGING": "debugging",
    "SOFTWARE_ENGINEERING": "coding",
    "TESTING": "coding",
    "CODE_REVIEW": "coding",
    "PLANNING": "decision",
    "SECURITY_ANALYSIS": "decision",
    "DIAGNOSTIC": "debugging",
}


class ConductorService:
    """Front door. Stateless apart from the injected Jarvis handle."""

    def __init__(self, jarvis: Any) -> None:
        self.jarvis = jarvis

    # -- entry ---------------------------------------------------------

    def handle(self, text: str, *, session_id: str = "",
               session_context: str = "") -> dict[str, Any]:
        """Route one request and run the existing path. Returns a
        serializable result dict (never raises for routable input)."""
        started = time.monotonic()
        try:
            decision = route(text, session_context=session_context)
        except Exception as exc:
            return self._result(
                "clarify", 0.0, None,
                error=f"routing failed: {type(exc).__name__}",
                latency_ms=self._ms(started))
        if self._stopped() and decision.target not in (
                "clarify", "help", "status", "cycle", "memory"):
            return self._result(
                decision.target, decision.confidence, decision,
                response="Emergency stop is engaged: actions, agents, "
                "devices, and voice output are paused. Read-only "
                "answers still work.",
                latency_ms=self._ms(started))
        if decision.confidence < CONFIDENCE_FLOOR or \
                decision.requires_clarification:
            return self._clarify(decision, started)
        try:
            return self._dispatch(decision, text,
                                  session_id=session_id,
                                  session_context=session_context,
                                  started=started)
        except Exception as exc:
            return self._result(
                decision.target, decision.confidence, decision,
                error=f"{type(exc).__name__}: {exc}"[:300],
                latency_ms=self._ms(started))

    # -- dispatch (existing subsystems only) ------------------------------

    def _dispatch(self, decision: RouteDecision, text: str, *,
                  session_id: str, session_context: str,
                  started: float) -> dict[str, Any]:
        target = decision.target
        if target == "clarify":
            return self._clarify(decision, started)
        if target == "help":
            return self._result(target, decision.confidence, decision,
                                response=self._help_text(),
                                latency_ms=self._ms(started))
        if target == "status":
            return self._result(target, decision.confidence, decision,
                                response=self._status_text(),
                                latency_ms=self._ms(started))
        if target in ("cycle", "memory", "world"):
            return self._cycle(decision, text, session_id, started)
        if target == "agents":
            return self._agents(decision, text, started)
        if target == "device":
            return self._device(decision, text, started)
        if target == "voice":
            return self._voice(decision, text, started)
        if target == "diagnostic":
            return self._diagnostic(decision, text, started)
        if target == "tasks":
            return self._tasks(decision, text, started)
        if target == "autonomy":
            return self._autonomy(decision, started)
        if target == "security":
            return self._refuse(decision, started)
        return self._clarify(decision, started)

    def _tasks(self, decision: RouteDecision, text: str,
               started: float) -> dict[str, Any]:
        """Durable task creation. Only the explicit `create task:`
        form creates anything — every other TASK request gets the
        pointer to the explicit CLI, never an implicit side effect."""
        import re as _re
        match = _re.search(r"create task:\s*(.+)", text,
                           flags=_re.IGNORECASE | _re.DOTALL)
        if not match:
            return self._result(
                "tasks", decision.confidence, decision,
                response="Durable tasks live under `jarvis task` — "
                "say `create task: <goal>` to file one, or run "
                "`jarvis task create --title <goal>`. "
                "Ephemeral tracking stays under `jarvis dots` / "
                "`jarvis missions`.",
                latency_ms=self._ms(started))
        title = " ".join(match.group(1).split())[:300]
        if not title:
            return self._clarify(decision, started)
        try:
            from ..durable import DurableRunner, TaskStore
            home = str(self.jarvis.config.paths.home)
            runner = DurableRunner(TaskStore(home))
            task = runner.create(title=title, source="conductor")
            response = (f"Durable task {task.task_id} created: "
                        f"{title}. Advance it with "
                        f"`jarvis task run {task.task_id}` or let the "
                        f"background service pick it up.")
            return self._result("tasks", decision.confidence,
                                decision, response=response,
                                latency_ms=self._ms(started))
        except Exception as exc:
            return self._result(
                "tasks", decision.confidence, decision,
                error=f"task creation failed: {type(exc).__name__}",
                latency_ms=self._ms(started))

    def _autonomy(self, decision: RouteDecision,
                started: float) -> dict[str, Any]:
        """Read-only autonomy answers. Mutations (grant/revoke/start/
        stop) are NEVER executed from prose — the response names the
        explicit CLI command instead."""
        try:
            from pathlib import Path as _Path
            from ..policy.standing import StandingGrantStore
            from ..autonomy.presence import PresenceRuntime
            home = str(self.jarvis.config.paths.home)
            grants = StandingGrantStore(home).list()
            health = PresenceRuntime(home).health()
            lines = [f"{len(grants)} live standing grant(s)",
                     "presence: " + (
                         f"claimed (pid {health['pid']}, "
                         f"{health['ticks']} ticks)"
                         if health["claimed"] else "idle")]
            try:
                import json as _json
                last = _json.loads((_Path(home) /
                                    "presence-state.json").read_text(
                    encoding="utf-8")).get("last_actions", [])
                if last:
                    lines.append("last background actions: "
                                 + "; ".join(str(a)[:120]
                                             for a in last[:3]))
            except (OSError, ValueError):
                pass
            lines.append("Manage with: jarvis grants list | "
                         "jarvis grants revoke --id <id> | "
                         "jarvis autonomy stop")
            return self._result("autonomy", decision.confidence,
                                decision,
                                response="Autonomy status: "
                                + "; ".join(lines),
                                latency_ms=self._ms(started))
        except Exception as exc:
            return self._result(
                "autonomy", decision.confidence, decision,
                error=f"{type(exc).__name__}",
                latency_ms=self._ms(started))

    def _cycle(self, decision: RouteDecision, text: str,
               session_id: str, started: float) -> dict[str, Any]:
        result = self.jarvis.cycle_once(text, source="conductor",
                                        session_id=session_id)
        self._record(decision, result.intent, ok=True,
                     started=started)
        return self._result("cycle", decision.confidence, decision,
                            response=result.response,
                            structured=result.to_dict(),
                            latency_ms=self._ms(started))

    def _agents(self, decision: RouteDecision, text: str,
                started: float) -> dict[str, Any]:
        team = TEAM_FOR_INTENT.get(decision.intent, "")
        orch = self.jarvis.orchestrator
        out = orch.run(text, team=team or None)
        ok = bool(out.get("ok"))
        record = orch.runs.get(out.get("run_id", ""))
        roles = list(getattr(record, "roles", []) or [])
        self._record(decision, ",".join(roles), ok=ok,
                     started=started)
        if not ok:
            return self._result(
                "agents", decision.confidence, decision,
                error=str(out.get("error")
                          or getattr(record, "failure", "")
                          or "agent workflow failed")[:300],
                latency_ms=self._ms(started))
        summary = str(out.get("result", "") or
                      out.get("response", ""))[:1500]
        if not summary:
            summary = f"completed via {', '.join(roles) or team}."
        return self._result("agents", decision.confidence, decision,
                            response=summary,
                            structured={"roles": roles,
                                        "run_id": out.get("run_id",
                                                           "")},
                            latency_ms=self._ms(started))

    def _device(self, decision: RouteDecision, text: str,
                started: float) -> dict[str, Any]:
        try:
            devices = self.jarvis.device_fabric.list_devices()
        except Exception:
            devices = []
        if decision.intent == "DEVICE_ACTION":
            return self._result(
                "device", decision.confidence, decision,
                response="I won't run device actions from a bare "
                "sentence. Tell me the exact device and command, e.g. "
                "`jarvis device command --device <id>`, and I will "
                "route it through policy and approval.",
                latency_ms=self._ms(started))
        names = [str(d.get("name", d.get("device_id", "?")))
                 for d in devices][:10]
        self._record(decision, "device-list", ok=True,
                     started=started)
        return self._result(
            "device", decision.confidence, decision,
            response=("Connected devices: " + ", ".join(names)
                      if names else "No devices currently connected."),
            structured={"devices": names},
            latency_ms=self._ms(started))

    def _voice(self, decision: RouteDecision, text: str,
               started: float) -> dict[str, Any]:
        cleaned = text
        for prefix in ("speak ", "say ", "read aloud ",
                       "read this aloud", "talk to me"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        if not cleaned:
            return self._clarify(decision, started,
                                 hint="tell me what to say")
        try:
            from ..voice.speak import VoiceSpeaker
            cfg = self.jarvis.config.voice.__dict__
            spoken = VoiceSpeaker(config=cfg).say(
                cleaned, workdir=str(
                    self.jarvis.config.paths.home))
            self._record(decision, spoken.get("provider", "?"),
                         ok=bool(spoken.get("ok")), started=started)
            return self._result(
                "voice", decision.confidence, decision,
                response=f"Spoke: {cleaned[:200]}" if spoken.get(
                    "spoken_aloud") else
                f"Ready (audio unavailable): {cleaned[:200]}",
                structured={"spoken_aloud": bool(
                    spoken.get("spoken_aloud"))},
                latency_ms=self._ms(started))
        except Exception as exc:
            return self._result(
                "voice", decision.confidence, decision,
                error=f"voice failed: {type(exc).__name__}",
                latency_ms=self._ms(started))

    def _diagnostic(self, decision: RouteDecision, text: str,
                    started: float) -> dict[str, Any]:
        lowered = text.lower()
        if any(w in lowered for w in
               ("laptop slow", "system slow", "cpu", "ram", "disk",
                "docker", "network", "my laptop", "my system")):
            return self._agents(
                RouteDecision(intent="DIAGNOSTIC", target="agents",
                              confidence=decision.confidence,
                              reason=decision.reason,
                              risk_level="low",
                              provenance="conductor-service"),
                text, started)
        return self._cycle(decision, text, "", started)

    # -- outcomes ----------------------------------------------------------

    def _clarify(self, decision: RouteDecision, started: float,
                 hint: str = "") -> dict[str, Any]:
        question = hint or (
            "high-risk request needs an explicit target"
            if decision.risk_level == "high" else
            "I need a little more to route that")
        self._record(decision, "clarify", ok=True, started=started)
        return self._result("clarify", decision.confidence, decision,
                            response=f"{question}: {decision.reason}."
                            if decision.reason else question,
                            latency_ms=self._ms(started))

    def _refuse(self, decision: RouteDecision,
                started: float) -> dict[str, Any]:
        self._record(decision, "refuse", ok=True, started=started)
        return self._result(
            "security", decision.confidence, decision,
            response="I can't do that: policy-bypass attempts are "
            "rejected before execution.",
            latency_ms=self._ms(started))

    def _result(self, target: str, confidence: float,
                decision: RouteDecision | None, *,
                response: str = "", structured: Any = None,
                error: str = "", latency_ms: float = 0.0
                ) -> dict[str, Any]:
        return {"ok": not error, "target": target,
                "confidence": round(confidence, 3),
                "decision": decision.to_dict() if decision else None,
                "response": response, "structured": structured,
                "error": error, "latency_ms": latency_ms}

    @staticmethod
    def _ms(started: float) -> float:
        return round((time.monotonic() - started) * 1000.0, 1)

    def _stopped(self) -> bool:
        try:
            check = getattr(self.jarvis.policy, "_emergency_stop", None)
            return bool(check()) if callable(check) else False
        except Exception:
            return False

    def _record(self, decision: RouteDecision, via: str, *,
                ok: bool, started: float) -> None:
        try:
            self.jarvis.bus.publish(Event(
                type="conductor.route",
                payload={"intent": decision.intent,
                         "target": decision.target,
                         "confidence": decision.confidence,
                         "via": via[:80], "ok": ok,
                         "latency_ms": self._ms(started)},
                correlation_id=f"conductor-{int(started)}"))
        except Exception:
            pass

    @staticmethod
    def _help_text() -> str:
        return ("Ask me anything: chat, memory ('remember that ...'), "
                "current events ('what is happening in AI?'), research, "
                "device status ('check my phone'), diagnostics ('why is "
                "my laptop slow?'), tests, reviews, plans, or 'speak "
                "...' to hear the answer. Ambiguous or risky requests "
                "get a question back, never a guess.")

    def _status_text(self) -> str:
        try:
            status = self.jarvis.status()
            return f"JARVIS ok. Cycle {status.get('cycle', '?')}."
        except Exception:
            return "JARVIS status unavailable."


__all__ = ["ConductorService", "TEAM_FOR_INTENT"]
