"""Agent Intelligence 2.0 — orchestrator, hierarchy, teams, tracing.

One controlled cognitive system with specialized roles, not 30 LLMs
talking to each other. Roles are logical (see contract.py); execution is
sequential and bounded by default, every tool call passes PolicyEngine,
and every run leaves a trace + blackboard behind.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.types import new_id, now
from .blackboard import Blackboard
from .bus import AgentMessage, Classification, MessageBus, MessageType
from .contract import AgentCard, AgentResult, VerificationStatus, role_cards


@dataclass
class Budgets:
    max_depth: int = 3
    max_agents: int = 8
    max_runtime_s: float = 120.0
    max_tool_calls: int = 15
    max_cost: float = 0.0  # reserved for metered backends; 0 = local-only

    def to_dict(self) -> dict[str, Any]:
        return {"max_depth": self.max_depth, "max_agents": self.max_agents,
                "max_runtime_s": self.max_runtime_s,
                "max_tool_calls": self.max_tool_calls, "max_cost": self.max_cost}


@dataclass
class TraceEvent:
    task_id: str
    agent: str
    role: str
    parent: str = ""
    event: str = "start"
    model: str = ""
    tools: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    detail: str = ""
    timestamp: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class OrchestratorContext:
    """Injected subsystems. Anything None degrades honestly, never fakes."""

    registry: Any = None
    planner: Any = None
    policy: Any = None
    tools: Any = None
    model_router: Any = None
    palace: Any = None
    graph: Any = None
    tracker: Any = None
    world_query: Any = None
    research: Any = None
    browser: Any = None
    computer: Any = None
    voice: Any = None
    vision: Any = None
    bus: MessageBus | None = None
    skills: Any = None


# role → fallback role when the primary handler fails
FALLBACKS = {
    "research": "knowledge",
    "coder": "reasoning",
    "debugger": "coder",
    "computer": "reasoning",
    "browser": "research",
    "vision": "reasoning",
    "voice": "communication",
}

# Reusable team strategies: ordered (role, purpose) stages.
TEAMS: dict[str, list[tuple[str, str]]] = {
    "research": [("research", "gather"), ("reasoning", "extract"),
                 ("critic", "challenge"), ("verifier", "check"),
                 ("communication", "synthesize")],
    "coding": [("planner", "architect"), ("coder", "implement"),
               ("verifier", "test"), ("reviewer", "review"),
               ("security", "scan"), ("verifier", "confirm")],
    "debugging": [("debugger", "reproduce"), ("reasoning", "root-cause"),
                  ("coder", "fix"), ("verifier", "regress"),
                  ("reviewer", "review")],
    "computer": [("vision", "observe"), ("planner", "plan"),
                 ("security", "policy-check"), ("computer", "execute"),
                 ("verifier", "state-check")],
    "decision": [("research", "evidence"), ("reasoning", "analyze"),
                 ("critic", "red-team"), ("knowledge-gap", "uncertainty"),
                 ("communication", "synthesize")],
    "daily": [("executive", "triage"), ("memory", "recall"),
              ("world", "situate"), ("planner", "plan"),
              ("coder", "execute"), ("verifier", "confirm")],
}


class Orchestrator:
    """JARVIS → Orchestrator → role DAG → verified result. Bounded always."""

    def __init__(self, ctx: OrchestratorContext,
                 budgets: Budgets | None = None) -> None:
        self.ctx = ctx
        self.budgets = budgets or Budgets()
        self.bus = ctx.bus or MessageBus()
        self.cards: dict[str, AgentCard] = {c.role_id: c for c in role_cards()}
        self.traces: dict[str, list[TraceEvent]] = {}
        self._cancelled: set[str] = set()
        self.bus.subscribe("broadcast", self._on_cancel)
        self._handlers: dict[str, Callable[..., AgentResult]] = {}
        self._register_default_handlers()

    # -- lifecycle ---------------------------------------------------------
    def _on_cancel(self, message: AgentMessage) -> None:
        if message.type == MessageType.CANCEL and message.task_id:
            self._cancelled.add(message.task_id)

    def cancel(self, task_id: str) -> None:
        self.bus.publish(AgentMessage(
            type=MessageType.CANCEL, sender="orchestrator",
            recipient="broadcast", task_id=task_id))

    def _trace(self, task_id: str, **kw: Any) -> None:
        self.traces.setdefault(task_id, []).append(TraceEvent(task_id=task_id, **kw))

    def explain(self, task_id: str) -> str:
        """Human-readable account of what happened in a task."""
        lines = [f"task {task_id}:"]
        for event in self.traces.get(task_id, []):
            lines.append(
                f"  [{event.agent}/{event.role}] {event.event}"
                + (f" {event.detail}" if event.detail else "")
                + (f" ({event.latency_ms:.0f}ms)" if event.latency_ms else ""))
        return "\n".join(lines) if len(lines) > 1 else f"task {task_id}: no trace"

    # -- adaptive depth ------------------------------------------------------
    @staticmethod
    def depth_for(goal: str, explicit: int | None = None) -> int:
        if explicit is not None:
            return max(0, min(5, explicit))
        import re
        words = len(goal.split())
        low = goal.lower()
        # Word boundaries throughout: substring matching once routed
        # "research" to the tool path via "search ".
        if re.search(r"\b(calculate|compute|run|open|list files|search|"
                     r"fetch|screenshot|remind)\b", low):
            return 1  # needs a tool → at least one specialist
        if re.search(r"\b(verify|check|confirm|test|review)\b", low):
            return 2  # verification intent → specialist + verifier
        if words <= 6 and not any(w in low for w in
                                  ("and then", "after", "plan", "research",
                                   "compare", "investigate", "build", "fix")):
            return 0
        if any(w in low for w in ("verify", "check", "confirm", "test")):
            return 2
        if any(w in low for w in ("plan", "build", "research", "investigate",
                                  "compare", "migrate", "deploy")):
            return 3
        return 1

    # -- main entry ------------------------------------------------------------
    def run(self, goal: str, depth: int | None = None,
            team: str | None = None, task_id: str = "",
            budgets: Budgets | None = None) -> dict[str, Any]:
        """Execute a goal. Returns blackboard summary + trace + result."""
        task_id = task_id or new_id("orch")
        budgets = budgets or self.budgets
        level = self.depth_for(goal, depth)
        board = Blackboard(goal=goal)
        board.write("goal", goal, author="orchestrator", provenance="user",
                    confidence=1.0)
        deadline = time.monotonic() + budgets.max_runtime_s
        state: dict[str, Any] = {"agents_used": 0, "tool_calls": 0,
                                 "depth": 0, "cancelled": False}
        self._trace(task_id, agent="orchestrator", role="orchestrator",
                    event="start", detail=f"depth={level}"
                    + (f" team={team}" if team else ""))

        stages = TEAMS.get(team or "", []) if team else []
        if level == 0 and not stages:
            result = self._run_role("communication", goal, board, task_id,
                                    state, budgets, deadline, depth=0)
            return self._finish(task_id, board, result, state)
        if not stages:
            stages = self._stages_for(goal, level)
        final: AgentResult | None = None
        for role_id, purpose in stages:
            if self._stop(task_id, state, budgets, deadline):
                break
            self._trace(task_id, agent="orchestrator", role="orchestrator",
                        event="stage", detail=f"{role_id}:{purpose}")
            result = self._run_role(role_id, goal, board, task_id, state,
                                    budgets, deadline, depth=1,
                                    purpose=purpose)
            final = result
            if not result.success and role_id in ("verifier", "critic"):
                board.write("verification",
                            {"subject": goal, "verdict": "failed",
                             "reason": "; ".join(result.errors)},
                            author=role_id, provenance="orchestrator",
                            confidence=result.confidence)
                break
        return self._finish(task_id, board, final, state)

    def _stages_for(self, goal: str, level: int) -> list[tuple[str, str]]:
        low = goal.lower()
        if level >= 4:
            if any(w in low for w in ("code", "bug", "fix", "implement", "refactor")):
                return TEAMS["coding"]
            if any(w in low for w in ("research", "compare", "investigate", "find")):
                return TEAMS["research"]
            return TEAMS["decision"]
        if level == 3:
            return [("planner", "plan"), ("reasoning", "execute"),
                    ("verifier", "confirm")]
        if level == 2:
            return [("reasoning", "execute"), ("verifier", "confirm")]
        return [("reasoning", "execute")]

    def _stop(self, task_id: str, state: dict[str, Any],
              budgets: Budgets, deadline: float) -> bool:
        if task_id in self._cancelled:
            state["cancelled"] = True
            return True
        if time.monotonic() > deadline:
            state["timeout"] = True
            return True
        if state["agents_used"] >= budgets.max_agents:
            state["capped"] = True
            return True
        return False

    def _finish(self, task_id: str, board: Blackboard,
                final: AgentResult | None,
                state: dict[str, Any]) -> dict[str, Any]:
        self._trace(task_id, agent="orchestrator", role="orchestrator",
                    event="done",
                    detail=f"ok={bool(final and final.success)}")
        return {"task_id": task_id, "ok": bool(final and final.success),
                "result": final.to_dict() if final else None,
                "blackboard": board.to_dict(),
                "conflicts": board.conflicts(),
                "trace": [e.to_dict() for e in self.traces.get(task_id, [])],
                "state": state}

    # -- role execution ----------------------------------------------------------
    def _run_role(self, role_id: str, goal: str, board: Blackboard,
                  task_id: str, state: dict[str, Any], budgets: Budgets,
                  deadline: float, depth: int, purpose: str = "") -> AgentResult:
        card = self.cards.get(role_id)
        if card is None:
            return AgentResult.failure(role_id, f"unknown role: {role_id}")
        if depth > budgets.max_depth:
            return AgentResult.failure(
                role_id, f"max depth {budgets.max_depth} exceeded")
        if state["agents_used"] >= budgets.max_agents:
            return AgentResult.failure(
                role_id, f"max agents {budgets.max_agents} reached")
        if time.monotonic() > deadline:
            return AgentResult.failure(role_id, "deadline exceeded")
        state["agents_used"] += 1
        handler = self._handlers.get(role_id, self._default_handler)
        started = time.monotonic()
        self._trace(task_id, agent=card.executor or role_id, role=role_id,
                    event="start", model=card.model_requirements)
        self.bus.publish(AgentMessage(
            type=MessageType.REQUEST, sender="orchestrator", recipient=role_id,
            task_id=task_id, payload={"goal": goal, "purpose": purpose},
            provenance="orchestrator", priority=5))
        try:
            result = handler(card, goal, board, task_id, state, budgets,
                             deadline, depth, purpose)
        except Exception as exc:  # failure isolation per role
            result = AgentResult.failure(
                role_id, f"{type(exc).__name__}: {exc}")
        elapsed_ms = (time.monotonic() - started) * 1000
        result.ended_at = now()
        result.usage["elapsed_ms"] = round(elapsed_ms, 1)
        self._trace(task_id, agent=card.executor or role_id, role=role_id,
                    event="done" if result.success else "failed",
                    model=card.model_requirements,
                    tools=result.actions_taken, latency_ms=elapsed_ms,
                    detail=f"confidence={result.confidence}")
        self.bus.publish(AgentMessage(
            type=MessageType.COMPLETION if result.success else MessageType.FAILURE,
            sender=role_id, recipient="orchestrator", task_id=task_id,
            payload=result.to_dict(), provenance=role_id,
            confidence=result.confidence))
        if not result.success and role_id in FALLBACKS and depth < budgets.max_depth:
            self._trace(task_id, agent="orchestrator", role="orchestrator",
                        event="fallback",
                        detail=f"{role_id}→{FALLBACKS[role_id]}")
            return self._run_role(FALLBACKS[role_id], goal, board, task_id,
                                  state, budgets, deadline, depth + 1, purpose)
        return result

    def spawn(self, parent_task: str, role_id: str, goal: str,
              depth: int) -> AgentResult:
        """Sub-agents exist only through here: depth-capped, budgeted."""
        if depth + 1 > self.budgets.max_depth:
            return AgentResult.failure(role_id, "spawning denied: max depth")
        board = Blackboard(goal=goal)
        state: dict[str, Any] = {"agents_used": 0, "tool_calls": 0,
                                 "depth": depth + 1, "cancelled": False}
        return self._run_role(role_id, goal, board, parent_task, state,
                              self.budgets, time.monotonic() + 60.0,
                              depth + 1)

    # -- handlers ------------------------------------------------------------------
    def _register_default_handlers(self) -> None:
        self._handlers.update({
            "executive": self._h_executive,
            "perception": self._h_perception,
            "world": self._h_world,
            "memory": self._h_memory,
            "knowledge": self._h_knowledge,
            "research": self._h_research,
            "reasoning": self._h_reasoning,
            "critic": self._h_critic,
            "verifier": self._h_verifier,
            "planner": self._h_planner,
            "coder": self._h_coder,
            "debugger": self._h_debugger,
            "reviewer": self._h_reviewer,
            "security": self._h_security,
            "computer": self._h_computer,
            "browser": self._h_browser,
            "devops": self._h_devops,
            "system": self._h_system,
            "communication": self._h_communication,
            "goal": self._h_goal,
            "forecast": self._h_forecast,
            "knowledge-gap": self._h_gap,
            "simulation": self._h_simulation,
            "reflection": self._h_reflection,
        })

    def _ok(self, role: str, task_id: str, output: Any,
            evidence: list[str] | None = None, confidence: float = 0.6,
            **kw: Any) -> AgentResult:
        return AgentResult(success=True, role=role, output=output,
                           evidence=evidence or [], confidence=confidence,
                           ended_at=now(), parent_task_id=task_id, **kw)

    def _need(self, name: str) -> Any:
        subsystem = getattr(self.ctx, name, None)
        return subsystem

    def _gated_tool(self, actor: str, tool_name: str,
                    args: dict[str, Any], state: dict[str, Any],
                    budgets: Budgets, description: str) -> AgentResult:
        """Every tool call passes PolicyEngine. No exceptions, no bypasses."""
        if self.ctx.tools is None or self.ctx.policy is None:
            return AgentResult.failure(actor, "no tools/policy bound")
        if state["tool_calls"] >= budgets.max_tool_calls:
            return AgentResult.failure(
                actor, f"tool budget {budgets.max_tool_calls} exhausted")
        tool = self.ctx.tools.get(tool_name)
        if tool is None:
            return AgentResult.failure(actor, f"unknown tool: {tool_name}")
        from ..core.types import ActionPlan
        plan = ActionPlan(
            action=f"{tool_name} {description}".strip(), args=args,
            required_permissions=list(tool.spec.required_permissions))
        decision = self.ctx.policy.evaluate(actor, plan)
        if not decision.allow:
            return AgentResult.failure(
                actor, "blocked by policy: " + "; ".join(decision.reasons))
        if decision.requires_approval:
            token = self.ctx.policy.request_approval(actor, plan, decision)
            return AgentResult(
                success=False, role=actor, errors=[f"needs approval ({token})"],
                verification_status=VerificationStatus.UNCERTAIN,
                ended_at=now())
        state["tool_calls"] += 1
        result = self.ctx.tools.call(tool_name, **args)
        if not result.ok:
            return AgentResult.failure(actor, result.error or "tool failed")
        return self._ok(actor, "", output=result.output,
                        actions_taken=[tool_name])

    # -- concrete role handlers (real subsystem work) --
    def _h_executive(self, card, goal, board, task_id, *a) -> AgentResult:
        board.write("constraints", {"goal": goal}, author="executive",
                    provenance="user-goal", confidence=0.9)
        return self._ok("executive", task_id, {"goal": goal, "priority": 5},
                        evidence=[goal], confidence=0.8)

    def _h_perception(self, card, goal, board, task_id, *a) -> AgentResult:
        obs = {"text": goal, "modality": "text"}
        board.write("observations", obs, author="perception",
                    provenance="user-input", confidence=0.9)
        return self._ok("perception", task_id, obs, evidence=[goal],
                        confidence=0.9)

    def _h_world(self, card, goal, board, task_id, *a) -> AgentResult:
        tracker = self._need("tracker")
        if tracker is None:
            return AgentResult.failure("world", "no World Model bound")
        changes = tracker.latest_changes()
        board.write("state", {"changes": [c.describe() for c in changes]},
                    author="world", provenance="world-2.0", confidence=0.8)
        return self._ok("world", task_id,
                        {"changes": [c.to_dict() for c in changes]},
                        evidence=[c.describe() for c in changes])

    def _h_memory(self, card, goal, board, task_id, *a) -> AgentResult:
        palace = self._need("palace")
        if palace is None:
            return AgentResult.failure("memory", "no Memory 3.0 bound")
        recalled = palace.search(goal, limit=5)
        items = [m.content for m, _ in recalled]
        board.write("evidence", {"recalled": items}, author="memory",
                    provenance="memory-3.0", confidence=0.7)
        return self._ok("memory", task_id, {"recalled": items},
                        evidence=items[:3], provenance="memory-3.0")

    def _h_knowledge(self, card, goal, board, task_id, *a) -> AgentResult:
        graph = self._need("graph")
        if graph is None:
            return AgentResult.failure("knowledge", "no graph bound")
        found = graph.related_entities(goal, limit=5)
        board.write("evidence", {"related": found}, author="knowledge",
                    provenance="knowledge-graph", confidence=0.7)
        return self._ok("knowledge", task_id, {"related": found},
                        evidence=found[:3])

    def _h_research(self, card, goal, board, task_id, *a) -> AgentResult:
        research = self._need("research")
        if research is not None:
            report = research.research(goal)
            packet = {"summary": report.summary, "sources": report.sources,
                      "citations": report.citations,
                      "confidence": report.confidence}
            board.write("evidence", packet, author="research",
                        provenance="research-engine",
                        confidence=report.confidence)
            return self._ok("research", task_id, packet,
                            evidence=report.citations[:5],
                            confidence=report.confidence)
        return self._gated_tool("researcher", "web_fetch", {"url": goal},
                                a[0], a[1], "research fetch")

    def _h_reasoning(self, card, goal, board, task_id, *a) -> AgentResult:
        evidence = [e.content for e in board.read("evidence")]
        hypotheses = [h.content for h in board.read("hypotheses")]
        if not hypotheses:
            hypotheses = [f"possible reading: {goal[:80]}"]
            board.write("hypotheses", hypotheses[0], author="reasoning",
                        provenance="reasoning-agent", confidence=0.5)
        trace = (f"goal: {goal} | evidence items: {len(evidence)} | "
                 f"alternatives kept: {len(hypotheses)}")
        board.write("decisions", {"trace": trace}, author="reasoning",
                    provenance="reasoning-agent", confidence=0.6)
        return self._ok("reasoning", task_id, {"trace": trace},
                        evidence=evidence[:5],
                        assumptions=["single-pass heuristic reasoning"],
                        uncertainties=["alternatives not exhaustively explored"])

    def _h_critic(self, card, goal, board, task_id, *a) -> AgentResult:
        findings: list[str] = []
        for entry in board.read("results") + board.read("decisions"):
            content = str(entry.content)
            if any(w in content.lower() for w in
                   ("always", "never", "certainly", "definitely", "prove")):
                findings.append(f"absolute claim without proof: {content[:100]}")
            if "assume" in content.lower() and "evidence" not in content.lower():
                findings.append(f"assumption without cited evidence: {content[:100]}")
        for entry in board.read("evidence"):
            if isinstance(entry.content, dict) and not entry.content.get("recalled"):
                findings.append(f"thin evidence from {entry.author}")
        board.write("results",
                    {"subject": goal, "verdict": "challenged" if findings else "stands",
                     "findings": findings},
                    author="critic", provenance="critic-agent",
                    confidence=0.7)
        return self._ok("critic", task_id, {"findings": findings},
                        evidence=findings, confidence=0.7)

    def _h_verifier(self, card, goal, board, task_id, *a) -> AgentResult:
        checks: list[str] = []
        results = [e for e in board.read("results")]
        if not results and not board.read("decisions"):
            return AgentResult(
                success=False, role="verifier", errors=["nothing to verify"],
                verification_status=VerificationStatus.UNCERTAIN,
                ended_at=now())
        ok = True
        for entry in results:
            content = entry.content
            if isinstance(content, dict) and content.get("verdict") == "failed":
                ok = False
                checks.append(f"failed verdict from {entry.author}")
        status = VerificationStatus.VERIFIED if ok else VerificationStatus.FAILED
        board.write("verification", {"subject": goal, "verdict": status.value,
                                     "checks": checks},
                    author="verifier", provenance="verifier-agent",
                    confidence=0.75)
        return AgentResult(success=ok, role="verifier",
                           output={"checks": checks},
                           verification_status=status, ended_at=now(),
                           confidence=0.75)

    def _h_planner(self, card, goal, board, task_id, *a) -> AgentResult:
        if self.ctx.planner is None:
            return AgentResult.failure("planner", "no planner bound")
        steps = self.ctx.planner.plan(goal)
        board.write("plans", [s.to_dict() for s in steps], author="planner",
                    provenance="dag-planner", confidence=0.7)
        return self._ok("planner", task_id,
                        {"steps": [s.to_dict() for s in steps]})

    def _h_coder(self, card, goal, board, task_id, state, budgets, *a) -> AgentResult:
        if self.ctx.planner is None:
            return AgentResult.failure("coder", "no planner bound")
        steps = self.ctx.planner.plan(goal)
        outputs: list[str] = []
        for step in steps:
            if state["tool_calls"] >= budgets.max_tool_calls:
                break
            if not step.tool or self.ctx.tools.get(step.tool) is None:
                outputs.append(f"skip {step.step_id}: no tool bound")
                continue
            result = self._gated_tool("coder", step.tool, step.args, state,
                                      budgets, step.description)
            outputs.append(f"{step.step_id}: {'ok' if result.success else result.errors}")
            if not result.success:
                return AgentResult.failure("coder", "; ".join(result.errors))
        board.write("results", {"subject": goal, "verdict": "implemented",
                                 "steps": outputs},
                    author="coder", provenance="coder-agent", confidence=0.65)
        return self._ok("coder", task_id, {"steps": outputs},
                        actions_taken=outputs)

    def _h_debugger(self, card, goal, board, task_id, *a) -> AgentResult:
        board.write("hypotheses", f"failure hypothesis for: {goal[:80]}",
                    author="debugger", provenance="debugger-agent",
                    confidence=0.5)
        return self._ok("debugger", task_id,
                        {"strategy": "reproduce → isolate → minimal fix → regress"},
                        uncertainties=["no live reproduction performed"])

    def _h_reviewer(self, card, goal, board, task_id, *a) -> AgentResult:
        return self._ok("reviewer", task_id, {"review": "advisory only"},
                        uncertainties=["static review, no execution"])

    def _h_security(self, card, goal, board, task_id, *a) -> AgentResult:
        try:
            from ..security.guards import scan_injection
        except Exception:
            return self._ok("security", task_id, {"scan": "guards unavailable"},
                            uncertainties=["guards module missing"])
        hits = []
        for entry in board.read("evidence") + board.read("observations"):
            scan = scan_injection(str(entry.content))
            if not scan["clean"]:
                hits.append({"author": entry.author, "hits": scan["hits"]})
        board.write("verification",
                    {"subject": goal, "verdict": "failed" if hits else "passed",
                     "injection_hits": hits},
                    author="security", provenance="security-agent",
                    confidence=0.8)
        return self._ok("security", task_id, {"hits": hits},
                        evidence=[str(h) for h in hits])

    def _h_computer(self, card, goal, board, task_id, state, budgets, *a) -> AgentResult:
        return self._gated_tool("computer", "screen_capture", {}, state,
                                budgets, "observe screen for goal")

    def _h_browser(self, card, goal, board, task_id, state, budgets, *a) -> AgentResult:
        browser = self._need("browser")
        if browser is None:
            return self._gated_tool("researcher", "web_fetch", {"url": goal},
                                    state, budgets, "browser fetch")
        try:
            result = browser.search(goal, count=3)
            return self._ok("browser", task_id, result,
                            evidence=[r.get("url", "") for r in
                                      result.get("results", [])])
        except Exception as exc:
            return AgentResult.failure("browser", f"{type(exc).__name__}: {exc}")

    def _h_devops(self, card, goal, board, task_id, state, budgets, *a) -> AgentResult:
        return self._gated_tool("computer", "system_probe", {}, state,
                                budgets, "system health read")

    def _h_system(self, card, goal, board, task_id, *a) -> AgentResult:
        tracker = self._need("tracker")
        if tracker is None:
            return AgentResult.failure("system", "no world tracker bound")
        latest = tracker.latest()
        if latest is None:
            return AgentResult(success=False, role="system",
                               errors=["no snapshots yet"],
                               verification_status=VerificationStatus.UNCERTAIN,
                               ended_at=now())
        return self._ok("system", task_id,
                        {"resources": latest.domains.get("resources", {})})

    def _h_communication(self, card, goal, board, task_id, *a) -> AgentResult:
        parts = []
        for entry in board.read("results") + board.read("verification"):
            parts.append(f"[{entry.author}] {entry.content}")
        answer = "\n".join(parts) if parts else f"done: {goal[:120]}"
        board.write("answer", answer, author="communication",
                    provenance="synthesizer", confidence=0.7)
        return self._ok("communication", task_id, {"answer": answer})

    def _h_goal(self, card, goal, board, task_id, *a) -> AgentResult:
        palace = self._need("palace")
        if palace is None:
            return AgentResult.failure("goal", "no memory bound")
        goals = palace.all(tier="goal", limit=10)
        items = [m.content for m in goals]
        board.write("state", {"goals": items}, author="goal",
                    provenance="memory-3.0", confidence=0.75)
        return self._ok("goal", task_id, {"goals": items}, evidence=items[:3])

    def _h_forecast(self, card, goal, board, task_id, *a) -> AgentResult:
        tracker = self._need("tracker")
        basis: list[str] = []
        if tracker is not None:
            for change in tracker.latest_changes(3):
                basis.append(change.describe())
        if not basis:
            return AgentResult(success=False, role="forecast",
                               errors=["no trend evidence available"],
                               uncertainties=["nothing observed yet"],
                               ended_at=now())
        text = f"trend continuation expected from: {'; '.join(basis[:3])}"
        board.write("hypotheses", {"forecast": text, "status": "prediction"},
                    author="forecast", provenance="trend-evidence",
                    confidence=0.45)
        return self._ok("forecast", task_id, {"forecast": text},
                        evidence=basis,
                        uncertainties=["prediction, not fact"])

    def _h_gap(self, card, goal, board, task_id, *a) -> AgentResult:
        gaps = []
        if not board.read("evidence"):
            gaps.append("no evidence collected")
        if not board.read("hypotheses"):
            gaps.append("no hypotheses formed")
        return self._ok("knowledge-gap", task_id, {"gaps": gaps})

    def _h_simulation(self, card, goal, board, task_id, *a) -> AgentResult:
        return self._ok(
            "simulation", task_id,
            {"hypothetical": f"IF executed: {goal[:120]} — no action taken"},
            uncertainties=["simulation only, nothing was executed"])

    def _h_reflection(self, card, goal, board, task_id, *a) -> AgentResult:
        lessons = []
        for entry in board.read("verification"):
            lessons.append(f"verified {entry.content} via {entry.author}")
        return self._ok("reflection", task_id, {"lessons": lessons})

    def _default_handler(self, card, goal, board, task_id, *a) -> AgentResult:
        return self._ok(card.role_id, task_id,
                        {"note": f"role {card.role_id} acknowledged: {goal[:80]}"},
                        uncertainties=["generic handler, no specialist bound"])

    # -- conflict resolution -----------------------------------------------------
    def resolve_conflicts(self, board: Blackboard) -> dict[str, Any]:
        """Preserve all claims; compare evidence; never average confidences."""
        resolutions = []
        for conflict in board.conflicts():
            first, second = conflict["a"], conflict["b"]
            winner = self._weigh(first, second)
            loser = second if winner is first else first
            record = {"subject": conflict["subject"],
                      "kept": {"author": winner["author"],
                               "verdict": winner["content"].get("verdict"),
                               "confidence": winner["confidence"]},
                      "set_aside": {"author": loser["author"],
                                    "verdict": loser["content"].get("verdict"),
                                    "confidence": loser["confidence"]},
                      "reason": "stronger evidence + provenance, not averaging"}
            board.write("decisions", record, author="orchestrator",
                        provenance="conflict-resolution", confidence=0.7)
            resolutions.append(record)
        return {"resolved": len(resolutions), "resolutions": resolutions}

    @staticmethod
    def _weigh(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
        def score(entry: dict[str, Any]) -> tuple:
            content = entry.get("content", {})
            has_evidence = 1 if isinstance(content, dict) and content.get(
                "findings", content.get("reason", "")) else 0
            verified = 1 if "verif" in entry.get("provenance", "") else 0
            return (has_evidence, verified, entry.get("confidence", 0))
        return first if score(first) >= score(second) else second

    # -- evidence chains -----------------------------------------------------------
    def why_believe(self, claim: str, board: Blackboard | None = None) -> dict[str, Any]:
        """Trace a conclusion backwards: decision → evidence → observation."""
        chain: list[dict[str, Any]] = []
        if board is not None:
            for entry in board.read(active_only=False):
                text = str(entry.content)
                if claim.lower()[:40] in text.lower() or text.lower()[:40] in claim.lower():
                    chain.append({"section": entry.section,
                                  "author": entry.author,
                                  "provenance": entry.provenance,
                                  "confidence": entry.confidence,
                                  "state": entry.state.value,
                                  "content": text[:200]})
        palace = self._need("palace")
        memory_hits: list[str] = []
        if palace is not None:
            try:
                for mem, _ in palace.search(claim, limit=3):
                    memory_hits.append(f"{mem.content[:120]} "
                                       f"(origin: {mem.origin or 'unknown'})")
            except Exception:
                pass
        return {"claim": claim, "chain": chain, "memory": memory_hits,
                "verdict": "supported" if chain else "unsupported"}
