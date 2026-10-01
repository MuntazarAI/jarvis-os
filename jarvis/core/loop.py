"""Master Cognitive Loop: World → Perception → … → Event Store → Next Cycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agents.agents import Supervisor
from ..cognition.cognition import AttentionController, ExecutiveFunction, Perception, Reflector, Understander
from ..cognition.mentalist import MentalistMode
from ..core.config import JarvisConfig
from ..core.types import ActionPlan, CognitiveReport, Confidence, Observation, RiskLevel, TaskState, now
from ..events.store import Event, EventBus, EventStore
from ..inference.analysis import Claim
from ..inference.evidence import EvidenceEngine
from ..inference.hypothesis import HypothesisEngine, HypothesisLab
from ..inference.reasoning import AbductiveReasoner, DeductiveReasoner, InductiveReasoner, MetaReasoner, RedTeamReasoner
from ..memory.consolidation import MemoryConsolidator
from ..memory.graph import KnowledgeGraph, extract_entities
from ..memory.palace import MemoryPalace
from ..models.models import ModelRouter, SelfModel, default_registry as default_models
from ..policy.policy import PolicyEngine
from ..tasks.engine import TaskEngine, TriggerEngine
from ..tools.tools import ToolRegistry, default_registry as default_tools
from ..world.model import WorldModel


@dataclass
class CycleResult:
    cycle: int
    input_text: str
    response: str
    intent: str
    confidence: Confidence = Confidence.UNKNOWN
    actions_taken: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    risk_max: float = 0.0
    blocked: bool = False
    duration: float = 0.0
    report: CognitiveReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle, "input": self.input_text, "response": self.response,
            "intent": self.intent, "confidence": self.confidence.value,
            "actions_taken": self.actions_taken, "tools_used": self.tools_used,
            "hypotheses": self.hypotheses, "unknowns": self.unknowns,
            "risk_max": self.risk_max, "blocked": self.blocked,
            "duration": round(self.duration, 3),
        }


class Jarvis:
    """The assembled system. Owns every subsystem and runs the loop."""

    def __init__(self, config: JarvisConfig | None = None,
                 home: str | None = None) -> None:
        self.config = config or JarvisConfig()
        if home:
            from pathlib import Path
            self.config.paths.home = Path(home)
        self.config.ensure_dirs()
        # persistence
        db_path = str(self.config.paths.resolve("home") / self.config.paths.db)
        self.events = EventStore()
        self.bus = EventBus(self.events)
        self.palace = MemoryPalace(db_path)
        self.graph = KnowledgeGraph(db_path)
        # cognition
        self.perception = Perception()
        self.understander = Understander()
        self.attention = AttentionController(budget=self.config.cognitive.attention_budget)
        self.executive = ExecutiveFunction()
        self.reflector = Reflector()
        self.meta = MetaReasoner()
        self.mentalist = MentalistMode()
        # inference (loop-local engines; mentalist keeps its own)
        self.evidence = EvidenceEngine()
        self.hypotheses = HypothesisEngine(limit=self.config.cognitive.hypothesis_limit)
        # world / models / policy / tools / agents / tasks
        self.world = WorldModel()
        self.models = default_models(self.config)
        self.router = ModelRouter(self.models, self.config)
        self.policy = PolicyEngine(self.config)
        self.tools: ToolRegistry = default_tools()
        try:
            from ..computer.computer import ComputerController, computer_tools
            self.computer = ComputerController()
            for tool in computer_tools(self.computer):
                try:
                    self.tools.register(tool)
                except ValueError:
                    pass
        except Exception:
            self.computer = None
        self.supervisor = Supervisor(on_step=self._execute_step)
        self.tasks = TaskEngine()
        self.triggers = TriggerEngine()
        self.self_model = SelfModel(permissions=["fs.read", "exec.eval"])
        for perm in ("fs.read", "exec.eval", "desktop.screenshot",
                     "desktop.windows", "clipboard.read"):
            self.policy.grant("jarvis", perm)
        for perm in ("fs.read", "fs.write", "exec", "exec.eval", "vcs.read",
                     "net.fetch", "plan"):
            self.policy.grant("coder", perm)
            self.policy.grant("computer", perm)
        for perm in ("desktop.screenshot", "desktop.windows", "clipboard.read"):
            self.policy.grant("computer", perm)
        # clipboard write + input stay approval-gated: no standing grants.
        # bookkeeping
        self.cycle = 0
        self._consolidate_every = self.config.memory.consolidate_every_cycles
        self._wire_bus()

    # -- bus ---------------------------------------------------------------
    def _wire_bus(self) -> None:
        self.bus.subscribe("cycle.*", lambda e: None, name="noop")
        self.bus.subscribe("tool.*", self._on_tool_event, name="tool-log")
        self.bus.subscribe("task.*", self._on_task_event, name="task-log")

    def _on_tool_event(self, event: Event) -> None:
        self.world.record_event(f"tool {event.type}: {event.payload.get('tool', '')}",
                                source="tool", confidence=0.9)

    def _on_task_event(self, event: Event) -> None:
        self.world.record_event(f"task {event.type}", source="task", confidence=0.9)

    # -- tool execution with policy gate --------------------------------------
    def _execute_step(self, step: Any, agent: Any) -> dict[str, Any]:
        """Runs one planned step through policy → tool → reflection."""
        tool_name = getattr(step, "tool", "")
        if not tool_name or not self.tools.get(tool_name):
            return {"ok": True, "note": f"step '{step.step_id}' needs no tool"}
        # Permissions come from the TOOL spec (what the action needs),
        # checked against the AGENT's grants (what the actor holds).
        # Using the agent's own permissions here would make the check vacuous.
        tool = self.tools.get(tool_name)
        needed = list(tool.spec.required_permissions) if tool else []
        plan = ActionPlan(action=f"{tool_name} {step.description}".strip(),
                          args=getattr(step, "args", {}),
                          required_permissions=needed,
                          risk=tool.spec.risk if tool else RiskLevel.LOW,
                          expected_duration=5.0,
                          verification_conditions=[getattr(step, "verification", "")])
        decision = self.policy.evaluate(agent.name, plan)
        self.bus.publish(Event(type="tool.gated",
                               payload={"tool": tool_name, "risk": decision.risk,
                                        "allow": decision.allow}))
        if not decision.allow:
            return {"ok": False, "error": f"blocked by policy: {decision.reasons}"}
        if decision.requires_approval:
            token = self.policy.request_approval(agent.name, plan, decision)
            return {"ok": False, "error": f"needs approval (token {token})"}
        result = self.tools.call(tool_name, **plan.args)
        self.bus.publish(Event(type="tool.called",
                               payload={"tool": tool_name, "ok": result.ok}))
        issues = self.reflector.self_check(str(result.output))
        return {"ok": result.ok, "output": result.output, "error": result.error,
                "issues": issues}

    # -- the loop ---------------------------------------------------------------
    def cycle_once(self, text: str, source: str = "user") -> CycleResult:
        started = now()
        self.cycle += 1
        corr = f"cycle-{self.cycle}"
        self.bus.publish(Event(type="cycle.started", payload={"input": text[:200]},
                               correlation_id=corr))

        # 1. perception
        obs = self.perception.perceive_text(text, source=source)
        self.world.observe(obs)

        # 2. attention (fresh budget every cycle; last cycle's use is logged)
        self.attention.reset()
        noticed = self.attention.attend(
            [{"id": obs.observation_id, "text": text, "priority": 0.8}])
        if not noticed:
            return self._finish(text, "Noted, but I am at attention capacity. "
                                     "Please repeat if this is urgent.",
                                intent="deferred", started=started, corr=corr)

        # 3. understanding
        understanding = self.understander.understand(
            text, {"mode": self.config.policy.proactivity})
        for name in extract_entities(text)[:8]:
            self.graph.upsert_node(name, attributes={"seen_in_cycle": self.cycle})

        # 4. memory retrieval — facts and episodes first; raw
        # conversation turns only as a fallback so chatter never
        # outranks knowledge.
        recalled = self.palace.search(text, limit=self.config.cognitive.memory_budget)
        knowledge = [m.content for m, _ in recalled if m.tier != "conversation"][:5]
        mem_context = knowledge or [m.content for m, _ in recalled[:3]]

        # 5. reasoning → hypotheses
        self.hypotheses.propose(f"user wants: {understanding.intent} — {text[:80]}",
                                prior=understanding.intent_confidence)
        alternatives = [f"alternative reading {i}: {text[:40]}"
                        for i in range(1, 3)]
        for alt in alternatives:
            self.hypotheses.propose(alt, prior=0.25)

        # 6. risk + policy pre-check for tool-like intents
        risk_max = 0.0
        blocked = False
        response, actions, tools_used = self._respond(
            text, understanding.intent, mem_context)
        if understanding.intent == "command" or understanding.task_hints:
            assessment = self.policy.risk.assess(text)
            risk_max = assessment.risk
            if not assessment.allow:
                blocked = True
                response = ("I cannot do that: "
                            + "; ".join(assessment.reasons))
            elif assessment.requires_approval:
                response = ("That needs your approval first "
                            f"(risk {assessment.risk:.2f}): "
                            + "; ".join(assessment.reasons))

        # 7. act (simple commands run through one supervised task).
        # Skip when a daily-driver workflow already answered: _respond
        # marks those actions daily_*/error_explained.
        handled = any(a in ("daily_status", "daily_continue",
                               "daily_changes", "daily_tests", "daily_repo",
                               "error_explained") for a in actions)
        if (understanding.intent == "command" and not blocked
                and not assessment.requires_approval and not handled
                and len(self.tools.history) < self.config.cognitive.tool_budget):
            actions, tools_used = self._act(text, actions, tools_used)
            response += self._summarize_actions(actions)

        # 8. verify + reflect
        issues = self.reflector.self_check(response)
        if issues and "empty output" in issues:
            response = "I processed that but have nothing to report yet."

        # 9. learn: store episode + conversation.
        # Episodes record what HAPPENED (input + outcome), not the full
        # response blob — verbose echoes pollute future recall summaries.
        self.palace.store_conversation("user", text, session_id=corr, room="Home")
        self.palace.store_conversation("jarvis", response, session_id=corr, room="Home")
        outcome = "; ".join(actions[:2]) if actions else response[:120]
        self.palace.store_episode(
            f"{understanding.intent}: {text[:120]} → {outcome[:160]}",
            room="Experiences", importance=0.4,
            related_entities=extract_entities(text)[:6],
            metadata={"correlation": corr, "confidence": understanding.intent_confidence},
        )

        # 10. world + event store + consolidation schedule
        self.world.record_event(f"cycle {self.cycle} completed", source="jarvis",
                                confidence=0.9)
        self.bus.publish(Event(type="cycle.completed",
                               payload={"intent": understanding.intent},
                               correlation_id=corr))
        if self.cycle % self._consolidate_every == 0:
            MemoryConsolidator(self.palace, self.config).run()

        unknowns = [u for u in
                    (understanding.task_hints or []) if u not in ("research",)]
        cycle_hypotheses = [h.claim for h in self.hypotheses._record().ranked()[:3]]
        # Close this cycle's hypotheses so the next cycle starts clean.
        # Full history is preserved in engine.history.
        for hyp in list(self.hypotheses.active.values()):
            self.hypotheses.resolve(hyp.hypothesis_id, status="closed-cycle")
        result = CycleResult(
            cycle=self.cycle, input_text=text, response=response,
            intent=understanding.intent,
            confidence=Confidence.from_score(understanding.intent_confidence),
            actions_taken=actions, tools_used=tools_used,
            hypotheses=cycle_hypotheses,
            unknowns=unknowns, risk_max=risk_max, blocked=blocked,
            duration=now() - started,
            report=self.mentalist.report(unknowns=unknowns,
                                         next_test="none pending"),
        )
        return result

    def _respond(self, text: str, intent: str,
                 mem_context: list[str]) -> tuple[str, list[str], list[str]]:
        # Daily-driver requests win over generic answers whatever the intent.
        daily = self._daily(text)
        if daily is not None:
            return daily
        if intent == "greeting":
            return "Hello. How can I help?", [], []
        if intent == "farewell":
            return "Goodbye.", [], []
        if intent == "confirmation":
            return "Acknowledged.", [], []
        if intent == "question":
            if mem_context:
                return (f"Based on what I remember: {mem_context[0][:300]}",
                        ["memory_recall"], [])
            answer = self._ask_model(text)
            if answer is not None:
                return (answer, ["llm_answer"], ["llm"])
            return ("I don't have a verified answer yet. "
                    "Could you tell me more so I can look into it?",
                    ["gap_identified"], [])
        if intent == "command":
            return "Working on it.", ["planned"], []
        remembered = f" I recall: {mem_context[0][:200]}." if mem_context else ""
        return (f"Noted.{remembered} What would you like me to do with that?",
                ["stored"], [])

    def _act(self, text: str, actions: list[str],
             tools_used: list[str]) -> tuple[list[str], list[str]]:
        low = text.lower()
        if low.startswith("calculate ") or low.startswith("compute "):
            expr = text.split(" ", 1)[1]
            result = self.tools.call("python_run", code=expr)
            tools_used.append("python_run")
            actions.append(f"calculated: {result.output or result.error}")
        elif "system" in low and ("status" in low or "health" in low or "check" in low):
            result = self.tools.call("system_probe")
            tools_used.append("system_probe")
            if result.ok:
                out = result.output
                actions.append(f"system: cpu={out.get('cpu_count')} "
                               f"platform={out.get('platform', '')[:40]}")
            else:
                actions.append(f"probe failed: {result.error}")
        elif low.startswith("remember "):
            fact = text[len("remember "):].strip()
            self.palace.store_fact(fact, room="Knowledge Library",
                                   source="user", importance=0.8)
            actions.append(f"stored fact: {fact[:80]}")
        elif low.startswith("list files") or low.startswith("list directory"):
            parts = text.split(" ", 2)
            path = parts[2] if len(parts) > 2 else "."
            result = self.tools.call("filesystem_read", path=path)
            tools_used.append("filesystem_read")
            if result.ok and isinstance(result.output, dict):
                names = [e["name"] for e in result.output.get("entries", [])[:10]]
                actions.append(f"files in {path}: {', '.join(names)}")
            else:
                actions.append(f"list failed: {result.error}")
        else:
            task = self.supervisor.submit(text)
            final = self.supervisor.run_task(task.task_id)
            actions.append(f"supervised task {final.state.value}")
        return actions, tools_used

    def _daily(self, text: str) -> tuple[str, list[str], list[str]] | None:
        """Daily-driver workflows. Intent-independent; None when no match."""
        low = text.lower()
        if "what am i working on" in low or "what was i doing" in low:
            from ..workflows.daily import what_am_i_working_on
            report = what_am_i_working_on(self)
            out = report["summary"][:400]
            if report["open_tasks"]:
                out += " Open: " + "; ".join(g for _, g in report["open_tasks"][:3])
            return out, ["daily_status"], []
        if low.startswith("continue") and ("project" in low or "work" in low):
            from ..workflows.daily import continue_project
            name = low.split("continue", 1)[1]
            for filler in ("my", "the", "project", "work", "on", "with"):
                name = name.replace(f" {filler} ", " ")
            report = continue_project(self, name.strip())
            bits = (report["recent_work"][:2] + report["decisions"][:2]
                    + [g for _, g in report["open_tasks"][:2]])
            return ("Continuing: " + " | ".join(bits[:4]) if bits
                    else "Nothing recorded on that yet.", ["daily_continue"], [])
        if "what changed" in low and ("yesterday" in low or "since" in low):
            from ..workflows.daily import what_changed_since
            report = what_changed_since(self, hours=30.0)
            items = report["memory_events"][:3] + report["world_events"][-2:]
            return ("Changes: " + " | ".join(items[:4]) if items
                    else "No changes recorded.", ["daily_changes"], [])
        if any(p in low for p in ("analyze this repo", "what is in this repo",
                                     "summarize this repo", "repo status")):
            from ..developer.dev import GitAssistant, RepoInspector
            repo = RepoInspector(".").scan()
            git = GitAssistant(".").status()
            top = sorted(repo.languages.items(), key=lambda kv: -kv[1])[:3]
            branch = git.get("branch", "?") if git.get("ok") else "not a repo"
            return (f"Repo: {repo.files} files ({', '.join(f'{k}:{v}' for k, v in top)}), "
                    f"{repo.tests} tests, {repo.total_lines} lines, branch {branch}.",
                    ["daily_repo"], [])
        if "run" in low and "test" in low:
            from ..workflows.daily import run_tests
            report = run_tests(self, ".")
            if report.get("needs_approval"):
                return (f"Tests need approval (token {report['needs_approval']}).",
                        ["daily_tests"], ["terminal_run"])
            if report.get("ok"):
                tail = " ".join(report["tail"])
                return ("Tests PASS." if report["passed"]
                        else f"Tests need attention: {tail[:300]}",
                        ["daily_tests"], ["terminal_run"])
            return (f"Tests blocked: {report.get('error', '')[:200]}",
                    ["daily_tests"], [])
        if "explain" in low and "error" in low:
            from ..workflows.daily import explain_error
            report = explain_error(self, text)
            parts = [f"likely cause: {report['likely_cause']}",
                     f"suggested fix: {report['suggested_fix']}"]
            if report["explanation"]:
                parts.append(report["explanation"][:400])
            return (" ".join(parts), ["error_explained"], ["llm"])
        return None

    def _ask_model(self, text: str) -> str | None:
        """Ask the routed generative model. Returns None when unavailable."""
        try:
            result = self.router.complete(
                task=text, prompt=text,
                system=("You are JARVIS, a concise personal AI. Answer briefly "
                        "and factually. If unsure, say so."))
        except Exception:
            return None
        if not result.get("ok"):
            return None
        answer = str(result.get("text", "")).strip()
        return answer or None

    @staticmethod
    def _summarize_actions(actions: list[str]) -> str:
        if not actions:
            return ""
        return " " + " ".join(a for a in actions[-3:])

    def _finish(self, text: str, response: str, intent: str,
                started: float, corr: str) -> CycleResult:
        self.bus.publish(Event(type="cycle.completed",
                               payload={"intent": intent}, correlation_id=corr))
        return CycleResult(cycle=self.cycle, input_text=text, response=response,
                           intent=intent, duration=now() - started)

    # -- proactive ---------------------------------------------------------------
    def poll_triggers(self, signals: dict[str, Any] | None = None) -> list[str]:
        signals = signals or {}
        signals.setdefault("now", now())
        fired = self.triggers.poll(signals)
        notes = []
        for trig in fired:
            notes.append(f"trigger {trig.kind}: {trig.action}")
            self.palace.store_episode(f"trigger fired: {trig.action}",
                                      room="Experiences", importance=0.5)
        return notes

    def status(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "memory": self.palace.stats(),
            "graph": self.graph.stats(),
            "events": self.events.count(),
            "agents": self.supervisor.status(),
            "tasks": self.tasks.stats(),
            "tools": self.tools.stats(),
            "models": self.models.stats(),
            "policy_conflicts": self.policy.conflicts(),
            "audit_entries": len(self.policy.audit),
        }

    def close(self) -> None:
        self.events.close()
        self.palace.close()
        self.graph.close()
