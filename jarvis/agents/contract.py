"""Agent Intelligence 2.0 — contracts, skills, role cards.

Roles are logical capabilities, not processes: 30 role cards bind to the 8
existing executor agents (supervisor/planner/researcher/coder/analyst/
computer/guardian/librarian) plus subsystem callables. No new model
instances are created here; the ModelRouter decides invocation depth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.types import new_id, now


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass
class Skill:
    """A named capability mapping to concrete tools + required permissions."""

    name: str
    description: str = ""
    tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "tools": self.tools, "permissions": self.permissions,
                "risk": self.risk}


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        for skill in _DEFAULT_SKILLS:
            self.register(skill)

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def for_tool(self, tool: str) -> list[Skill]:
        return [s for s in self._skills.values() if tool in s.tools]


_DEFAULT_SKILLS = [
    Skill("research.web", "web search + fetch + extract",
          ["web_fetch"], ["net.fetch"], "low"),
    Skill("code.search", "repository + symbol search",
          ["filesystem_read"], ["fs.read"], "low"),
    Skill("code.patch", "write/modify files",
          ["filesystem_write"], ["fs.write"], "medium"),
    Skill("code.test", "run tests + interpret results",
          ["terminal_run", "python_run"], ["exec", "exec.eval"], "medium"),
    Skill("system.inspect", "read-only system state",
          ["system_probe"], [], "low"),
    Skill("docker.inspect", "container status via CLI",
          ["terminal_run"], ["exec"], "low"),
    Skill("browser.navigate", "fetch + extract approved pages",
          ["web_fetch"], ["net.fetch"], "low"),
    Skill("computer.observe", "screenshot + window list + clipboard read",
          ["screen_capture", "window_list", "clipboard_read"],
          ["desktop.screenshot", "desktop.windows", "clipboard.read"], "low"),
    Skill("computer.click", "mouse/keyboard actuation (approval-gated)",
          ["mouse_click", "type_text", "press_keys", "mouse_move"],
          ["desktop.input"], "high"),
    Skill("vision.describe", "screen/camera description",
          ["screen_capture"], ["desktop.screenshot"], "low"),
    Skill("memory.retrieve", "recall from Memory 3.0", [], [], "low"),
    Skill("memory.write", "store observations/facts (explicit intent only)",
          [], [], "low"),
    Skill("graph.query", "knowledge-graph traversal", [], [], "low"),
    Skill("world.query", "World Model 2.0 snapshots + temporal queries",
          [], [], "low"),
    Skill("security.scan", "injection/SSRF/secret scan",
          ["web_fetch"], ["net.fetch"], "low"),
    Skill("model.route", "capability-based model selection", [], [], "low"),
]


@dataclass
class AgentCard:
    """Contract for one logical role: what it does, needs, and returns."""

    role_id: str
    role: str
    capabilities: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    model_requirements: str = "fast"
    resource_budget: dict[str, Any] = field(
        default_factory=lambda: {"max_tool_calls": 5, "max_seconds": 60})
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    executor: str = ""  # existing agent name that runs this role
    may_act: bool = True  # False = reasoning-only, never touches tools

    def to_dict(self) -> dict[str, Any]:
        return {"role_id": self.role_id, "role": self.role,
                "capabilities": self.capabilities,
                "responsibilities": self.responsibilities,
                "skills": self.skills, "permissions": self.permissions,
                "model_requirements": self.model_requirements,
                "resource_budget": self.resource_budget,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "executor": self.executor, "may_act": self.may_act}


@dataclass
class AgentResult:
    """Structured result every role must return. No free-form handoffs."""

    success: bool
    output: Any = None
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5
    provenance: str = ""
    assumptions: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    actions_taken: list[str] = field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    errors: list[str] = field(default_factory=list)
    agent_id: str = ""
    role: str = ""
    parent_task_id: str = ""
    started_at: float = field(default_factory=now)
    ended_at: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items()}
        data["verification_status"] = self.verification_status.value
        return data

    @classmethod
    def failure(cls, role: str, error: str, **kw: Any) -> "AgentResult":
        return cls(success=False, role=role, errors=[error],
                   ended_at=now(), **kw)


def _card(role_id: str, role: str, executor: str, model: str,
          capabilities: list[str], responsibilities: list[str],
          skills: list[str] | None = None,
          permissions: list[str] | None = None,
          may_act: bool = True, **budget: Any) -> AgentCard:
    return AgentCard(
        role_id=role_id, role=role, capabilities=capabilities,
        responsibilities=responsibilities, skills=skills or [],
        permissions=permissions or [], model_requirements=model,
        resource_budget={"max_tool_calls": budget.get("tools", 5),
                         "max_seconds": budget.get("seconds", 60)},
        input_schema={"task": "str", "context": "dict"},
        output_schema={"success": "bool", "output": "any",
                       "evidence": "list[str]", "confidence": "float"},
        executor=executor, may_act=may_act)


def role_cards() -> list[AgentCard]:
    """The 30-role organization bound to existing executors + subsystems."""
    R = _card
    return [
        R("orchestrator", "Orchestrator", "supervisor", "reasoning",
          ["decompose goals", "build DAGs", "merge results", "resolve conflicts"],
          ["never performs privileged actions unless explicitly permitted"],
          [], ["*"], may_act=False, tools=0, seconds=120),
        R("executive", "Executive", "supervisor", "reasoning",
          ["goal understanding", "priority", "constraints", "planning depth"],
          ["connect work to Memory 3.0 goals", "track deadlines"],
          [], [], may_act=False),
        R("perception", "Perception Agent", "analyst", "fast",
          ["text/vision/screen/audio/device signals → structured observations"],
          ["normalize inputs", "never invent unseen detail"],
          ["computer.observe", "vision.describe", "memory.retrieve"], []),
        R("world", "World Agent", "analyst", "fast",
          ["World Model 2.0 snapshots", "diffs", "temporal queries"],
          ["report environmental changes with provenance"],
          ["world.query", "memory.retrieve"], []),
        R("memory", "Memory Agent", "librarian", "fast",
          ["retrieve", "write observations", "consolidate", "correct/reinforce"],
          ["provenance checks", "conflict detection", "no memory poisoning"],
          ["memory.retrieve", "memory.write"], []),
        R("knowledge", "Knowledge Agent", "librarian", "fast",
          ["graph queries", "relationships", "historical reconstruction"],
          ["fact vs hypothesis separation", "missing-relationship reports"],
          ["graph.query", "memory.retrieve"], []),
        R("research", "Research Agent", "researcher", "fast",
          ["structured research", "evidence gathering", "citations"],
          ["source provenance", "uncertainty reporting"],
          ["research.web"], ["net.fetch"]),
        R("reasoning", "Reasoning Agent", "analyst", "reasoning",
          ["multi-step reasoning", "hypotheses", "alternatives", "traces"],
          ["evidence/assumption separation", "audit-ready traces"],
          [], [], may_act=False),
        R("critic", "Critic Agent", "analyst", "reasoning",
          ["attack plans/answers", "find contradictions", "falsify"],
          ["never silently modify another agent's result"],
          [], [], may_act=False),
        R("verifier", "Verifier Agent", "analyst", "fast",
          ["validate outputs", "run tests", "check calculations/files/state"],
          ["mark verified / failed / uncertain"],
          ["code.test", "system.inspect"], ["exec", "exec.eval", "fs.read"]),
        R("planner", "Planner Agent", "planner", "reasoning",
          ["DAGs", "dependencies", "checkpoints", "retries", "rollback plans"],
          ["bounded plans only"],
          [], ["plan"], may_act=False),
        R("coder", "Coder Agent", "coder", "coding",
          ["repo understanding", "patches", "tests"],
          ["exact file lists", "no commit/push without policy authorization"],
          ["code.search", "code.patch", "code.test"],
          ["fs.read", "fs.write", "exec", "exec.eval", "vcs.read"]),
        R("debugger", "Debugger Agent", "coder", "coding",
          ["reproduce", "isolate root cause", "minimal fixes", "regression tests"],
          ["evidence-first diagnosis"],
          ["code.search", "code.patch", "code.test"],
          ["fs.read", "fs.write", "exec", "exec.eval"]),
        R("reviewer", "Reviewer Agent", "analyst", "reasoning",
          ["correctness", "maintainability", "security", "coverage", "perf"],
          ["advisory only — never blocks by itself"],
          ["code.search"], ["fs.read"], may_act=False),
        R("security", "Security Agent", "guardian", "fast",
          ["tool-request review", "injection/SSRF/secret detection"],
          ["integrate with PolicyEngine, never bypass it"],
          ["security.scan"], []),
        R("privacy", "Privacy Agent", "guardian", "fast",
          ["PII/secret classification", "outbound + log review", "minimization"],
          ["block unnecessary exposure"],
          [], [], may_act=False),
        R("computer", "Computer Agent", "computer", "fast",
          ["observe screen", "approved actions", "state verification"],
          ["checkpointed execution", "stop on policy failure"],
          ["computer.observe", "computer.click"],
          ["exec", "desktop.screenshot", "desktop.windows", "clipboard.read"]),
        R("browser", "Browser Agent", "researcher", "fast",
          ["approved navigation", "extraction", "provenance"],
          ["injection-aware extraction", "verify important results"],
          ["browser.navigate"], ["net.fetch"]),
        R("devops", "DevOps Agent", "computer", "fast",
          ["services", "docker", "processes", "logs", "diagnostics"],
          ["resource-aware, read-first"],
          ["docker.inspect", "system.inspect"], ["exec"]),
        R("system", "System Agent", "computer", "fast",
          ["CPU/RAM/disk/network monitoring", "pressure prediction"],
          ["never destructive without approval"],
          ["system.inspect"], []),
        R("model", "Model Agent", "analyst", "fast",
          ["model selection", "latency/resource tracking", "fallback"],
          ["route by capability, not habit"],
          ["model.route"], [], may_act=False),
        R("voice", "Voice Agent", "analyst", "fast",
          ["STT/VAD/wake-word/TTS/barge-in/turns"],
          ["never transmit audio externally without consent"],
          [], []),
        R("vision", "Vision Agent", "analyst", "vision",
          ["screen/camera understanding", "entity extraction", "diffs"],
          ["uncertainty reporting"],
          ["vision.describe"], ["desktop.screenshot"]),
        R("automation", "Automation Agent", "supervisor", "fast",
          ["schedules", "recurring workflows", "retries/checkpoints"],
          ["monitor completion honestly"],
          [], []),
        R("communication", "Communication Agent", "analyst", "fast",
          ["summaries", "format adaptation", "context"],
          ["no external sends without permission"],
          ["memory.retrieve"], [], may_act=False),
        R("goal", "Goal Agent", "librarian", "fast",
          ["goal tracking", "decomposition", "stall detection"],
          ["link goals to projects/tasks/memories"],
          ["memory.retrieve", "graph.query"], []),
        R("reflection", "Reflection Agent", "analyst", "reasoning",
          ["post-task review", "lessons", "improvement proposals"],
          ["only validated lessons enter memory"],
          ["memory.retrieve"], [], may_act=False),
        R("simulation", "Simulation Agent", "analyst", "reasoning",
          ["what-if analysis", "plan comparison without execution"],
          ["always label output hypothetical"],
          [], [], may_act=False),
        R("forecast", "Forecast Agent", "analyst", "reasoning",
          ["trend-based predictions", "lifecycle tracking"],
          ["never present predictions as facts"],
          ["world.query", "memory.retrieve"], [], may_act=False),
        R("knowledge-gap", "Knowledge-Gap Agent", "librarian", "fast",
          ["missing info", "ambiguity", "unsupported claims"],
          ["request research/observation with justification"],
          ["memory.retrieve", "graph.query"], [], may_act=False),
    ]
