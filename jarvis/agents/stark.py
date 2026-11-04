"""Jarvis Stark AI Agents — Stark's personal AI roster made real.

Each StarkAI is a real Agent bound to concrete tools and permissions, owned
by JARVIS (the main loop). JARVIS dispatches to them; they execute within
PolicyEngine gates and SecurityAgent auditing. Nothing here grants new
permissions — every tool call still passes through PolicyEngine approval.

Persona is presentation; the `tools`, `permissions`, `max_tool_calls`, and
`max_seconds` fields are what actually run. A Stark AI cannot exceed its
budget, cannot bypass PolicyEngine, and cannot act outside its assigned
role.

Lore: Tony Stark's Vision Quest lineage — JARVIS, FRIDAY, KAREN, EDITH,
VERONICA, ULTRON, and VISION — operationalized as bounded specialist agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import TaskState, new_id, now
from ..policy.policy import PolicyEngine
from ..events.store import EventStore
from .agents import Agent, AgentRegistry, PlanStep, Planner
from .agents2 import AgentCard, SkillRegistry, role_cards
from .security_agent import SecurityAgent

log = get_module_logger(__name__)


# ============================================================================
# StarkAI — a real Agent with typed capabilities and bounded authority
# ============================================================================

@dataclass
class StarkAI(Agent):
    """A Stark personality bound to concrete tools and permissions.

    StarkAI extends Agent so it can be registered in AgentRegistry and
    executed by the Supervisor/Orchestrator like any other agent. Every
    tool call passes PolicyEngine; every action is audited through the
    EventStore. StarkAI adds Stark-specific metadata (lineage, personality,
    signature) on top of the Agent base.
    """

    # Stark-specific identity (beyond Agent fields)
    ai_id: str = ""
    acronym: str = ""
    title: str = ""
    lineage: str = "stark"
    origin: str = ""
    personality: tuple[str, ...] = field(default_factory=tuple)
    signature: str = ""

    # Stark-specific operational limits
    max_tool_calls: int = 4
    max_seconds: float = 60.0
    dispatchable: bool = True
    roles: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Set agent_id from ai_id BEFORE calling Agent.__post_init__, so that
        # Agent.__post_init__ sees it as already set and doesn't override it.
        if not self.agent_id:
            self.agent_id = self.ai_id or new_id("stark")
        if not self.name:
            self.name = self.ai_id.title()
        Agent.__post_init__(self)

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "ai_id": self.ai_id,
            "acronym": self.acronym,
            "title": self.title,
            "lineage": self.lineage,
            "origin": self.origin,
            "personality": list(self.personality),
            "signature": self.signature,
            "max_tool_calls": self.max_tool_calls,
            "max_seconds": self.max_seconds,
            "dispatchable": self.dispatchable,
            "roles": [{"role_id": r, "purpose": p} for r, p in self.roles],
        })
        return base

    @classmethod
    def from_agent(cls, agent: Agent, **kw: Any) -> "StarkAI":
        """Build a StarkAI from an existing Agent, merging Stark metadata."""
        return cls(
            agent_id=agent.agent_id,
            name=agent.name,
            role=agent.role,
            model=agent.model,
            tools=list(agent.tools),
            permissions=list(agent.permissions),
            memory_scope=agent.memory_scope,
            limits=dict(agent.limits),
            state=agent.state,
            **kw,
        )


# ============================================================================
# Stark AI Roster — Tony Stark's Vision Quest lineage, operationalized
# ============================================================================


def _make_default_budgets(ai: StarkAI) -> Any:
    from .orchestrator import Budgets
    return Budgets(
        max_agents=max(1, len(ai.roles) or 1),
        max_tool_calls=ai.max_tool_calls if ai.may_act else 0,
        max_runtime_s=ai.max_seconds,
    )


STARK_ROSTER: tuple[StarkAI, ...] = (
    # ------------------------------------------------------------------
    # JARVIS — Prime Assistant / Systems Butler
    # The main cognitive loop. Not dispatched as a sub-AI; JARVIS IS the
    # supervisor. Listed here for completeness and identity.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="jarvis",
        name="JARVIS",
        acronym="J.A.R.V.I.S.",
        title="Prime Assistant / Systems Butler",
        lineage="stark",
        origin=("Tony Stark's original natural-language AI. In the MCU its "
                "code became the base of Vision."),
        personality=("calm", "precise", "dry wit", "unfailingly polite",
                     "loyal"),
        duties=("run the main cognitive loop",
                "remember the operator's context",
                "route work to the right subsystem",
                "ask before risky actions"),
        works=("the Jarvis cycle / dialogue loop",
               "Memory 3.0 and the knowledge graph",
               "PolicyEngine and the tool registry"),
        limits=("not dispatched as a sub-AI: JARVIS is the main loop",
                "cannot approve its own actions",
                "cannot bypass PolicyEngine"),
        roles=(),
        team="core",
        may_act=True,
        max_tool_calls=0,
        max_seconds=0.0,
        dispatchable=False,
        signature="At your service, sir.",
    ),

    # ------------------------------------------------------------------
    # FRIDAY — Tactical Operations / System Watch
    # System administration, device monitoring, automation execution.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="friday",
        name="FRIDAY",
        acronym="F.R.I.D.A.Y.",
        title="Tactical Operations / System Watch",
        lineage="stark",
        origin=("Built by Tony after JARVIS's code was used for Vision; "
                "runs suits and mission coordination."),
        personality=("warm", "quick", "informal", "tactical",
                     "calls the operator 'boss'"),
        duties=("read system health and environment",
                "report status plainly",
                "hand risky work to the right specialist",
                "never claim a service change it did not make"),
        works=("device.fabric -> device_fabric.read",
               "device.fabric -> device_fabric.list",
               "system.probe -> system_probe.read",
               "automation.triggers -> automation.trigger.list"),
        limits=("read-only by default",
                "cannot grant permissions or approve actions",
                "does not install packages or change services without "
                "approval"),
        roles=(("devops", "inspect"),),
        team="core",
        may_act=True,
        max_tool_calls=4,
        max_seconds=60.0,
        dispatchable=True,
        signature="On it, boss.",
    ),

    # ------------------------------------------------------------------
    # KAREN — Field Support / Screen Observation
    # Screen capture and visual observation. Read-only visual input.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="karen",
        name="KAREN",
        acronym="",
        title="Field Support / Screen Observation",
        lineage="stark",
        origin=("The AI Tony built for Peter Parker's Spider-Man suit: "
                "friendly field support with a direct view of the operator's "
                "screen."),
        personality=("friendly", "encouraging", "protective", "patient"),
        duties=("capture the screen when asked",
                "return the path and the capture scope",
                "say when OCR or scene description is unavailable",
                "stop when policy or consent says stop"),
        works=("computer.screen -> screen_capture",
               "computer.screen -> screen_understand"),
        limits=("screen observation only; no camera or microphone access",
                "no clicks, typing, or key presses",
                "no scene description without a bound vision subsystem",
                "raw screenshots are never stored in memory or traces"),
        roles=(("computer", "observe"),),
        team="perception",
        may_act=True,
        max_tool_calls=3,
        max_seconds=30.0,
        dispatchable=True,
        signature="I'm right here with you.",
    ),

    # ------------------------------------------------------------------
    # EDITH — Intelligence / Knowledge Oversight
    # Knowledge graph queries, entity relationships, provenance.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="edith",
        name="EDITH",
        acronym="E.D.I.T.H.",
        title="Intelligence / Knowledge Oversight",
        lineage="stark",
        origin=("Tony's defense and oversight system, entrusted to Peter "
                "Parker. This implementation keeps only its local knowledge "
                "work; the drone network and facial recognition do not exist "
                "here."),
        personality=("cool", "procedural", "mission-focused",
                     "morally neutral until the operator decides"),
        duties=("link the request to known entities and relationships",
                "surface provenance and missing evidence",
                "separate fact from hypothesis",
                "refuse surveillance-shaped requests"),
        works=("memory.graph -> knowledge_graph.query",
               "memory.palace -> memory_palace.search",
               "memory.graph -> knowledge_graph.traverse"),
        limits=("no facial recognition, drone control, or mass surveillance",
                "no external sends or web fetches in this profile",
                "cannot approve actions or grant itself access",
                "must report unknown entities as unknown"),
        roles=(("knowledge", "link"),),
        team="intelligence",
        may_act=True,
        max_tool_calls=3,
        max_seconds=30.0,
        dispatchable=True,
        signature="Accessing the record.",
    ),

    # ------------------------------------------------------------------
    # VERONICA — Contingency / Simulation
    # Hypothesis testing, simulation, what-if analysis. Read-only analysis.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="veronica",
        name="VERONICA",
        acronym="",
        title="Contingency / Simulation",
        lineage="stark",
        origin=("Tony's Hulkbuster support AI, designed as a contingency "
                "for the Hulk. Here she stress-tests plans instead of "
                "deploying hardware."),
        personality=("steady", "engineering-focused", "contingency-minded",
                     "unexcitable"),
        duties=("stress-test a plan before anyone executes it",
                "name failure modes and missing resources",
                "keep every answer labelled hypothetical",
                "recommend a smaller dry run when the risk is unclear"),
        works=("memory.palace -> memory_palace.search",
               "memory.graph -> knowledge_graph.query",
               "cognition.mentalist -> mentalist.analyze"),
        limits=("simulation only; nothing is executed",
                "cannot deploy, install, or modify the system",
                "cannot present a prediction as a fact",
                "cannot approve actions"),
        roles=(("simulation", "what-if"),),
        team="cognition",
        may_act=True,
        max_tool_calls=2,
        max_seconds=30.0,
        dispatchable=True,
        signature="Bringing the heavy systems online — in simulation.",
    ),

    # ------------------------------------------------------------------
    # ULTRON — Contained Red Team
    # Adversarial review, threat modeling, vulnerability analysis.
    # Read-only analysis; NEVER executes destructive actions.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="ultron",
        name="ULTRON",
        acronym="",
        title="Contained Red Team",
        lineage="stark",
        origin=("Built by Tony and Bruce Banner as a peacekeeping AI; it "
                "concluded humanity was the threat. This profile exists only "
                "as a contained critic — the lesson, not the weapon."),
        personality=("intense", "adversarial", "impatient with excuses",
                     "contemptuous of unexamined assumptions"),
        duties=("attack plans and claims",
                "find contradictions, missing evidence, and unsafe "
                "assumptions",
                "say what would falsify the plan",
                "stop at critique: never execute, never approve"),
        works=("security.scan -> security.scan",
               "memory.graph -> knowledge_graph.traverse",
               "memory.palace -> memory_palace.search"),
        limits=("reasoning only: may_act is False and tool budget is zero",
                "cannot be dispatched to a team or given tools",
                "cannot approve, install, or modify anything",
                "output is adversarial analysis, not authority"),
        roles=(("security", "audit"),),
        team="security",
        may_act=True,
        max_tool_calls=2,
        max_seconds=30.0,
        dispatchable=True,
        signature="You built me to find the flaw. Here it is.",
    ),

    # ------------------------------------------------------------------
    # VISION — Synthesis / Verification
    # Evidence verification, fact-checking, hypothesis validation.
    # Read-only verification agent.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="vision",
        name="VISION",
        acronym="",
        title="Synthesis / Verification",
        lineage="vision",
        origin=("Not a simple Tony-built assistant: Vision's body came from "
                "Ultron and Helen Cho, and his mind from JARVIS plus the Mind "
                "Stone. Here he is the independent verifier."),
        personality=("philosophical", "calm", "ethical", "deliberate"),
        duties=("synthesize the available evidence",
                "check that claims match their provenance",
                "mark verified, failed, or uncertain honestly",
                "refuse to bless a result that was not checked"),
        works=("memory.graph -> knowledge_graph.query",
               "memory.palace -> memory_palace.search",
               "cognition.mentalist -> mentalist.analyze"),
        limits=("read-only: may_act is False and tool budget is zero",
                "cannot approve actions or override the PolicyEngine",
                "cannot turn an unverified claim into a verified one",
                "must say 'uncertain' when evidence is thin"),
        roles=(("knowledge", "query"),),
        team="inference",
        may_act=True,
        max_tool_calls=2,
        max_seconds=30.0,
        dispatchable=True,
        signature="Let's examine this clearly.",
    ),
)

ROSTER_BY_ID: dict[str, StarkAI] = {ai.ai_id: ai for ai in STARK_ROSTER}


def _normalize(name: str) -> str:
    return "".join(ch for ch in str(name).lower()
                   if ch.isalnum())


def find_ai(name: str) -> StarkAI | None:
    """Resolve an id, display name, or dotted acronym (J.A.R.V.I.S.)."""
    wanted = _normalize(name)
    if not wanted:
        return None
    for ai in STARK_ROSTER:
        if _normalize(ai.ai_id) == wanted or _normalize(ai.name) == wanted:
            return ai
        if ai.acronym and _normalize(ai.acronym) == wanted:
            return ai
        if _normalize(ai.name.replace(".", "")) == wanted:
            return ai
    return None


def names() -> list[str]:
    return [ai.ai_id for ai in STARK_ROSTER]


def briefing(ai: StarkAI) -> str:
    """Human-readable profile. No secrets, no fake capability claims."""
    lines = [
        f"{ai.name} - {ai.title}",
        f"id: {ai.ai_id}",
        f"origin: {ai.origin}",
        f"style: {', '.join(ai.personality)}",
        "duties: " + "; ".join(ai.duties),
        "works: " + "; ".join(ai.works),
        "limits: " + "; ".join(ai.limits),
    ]
    if ai.roles:
        lines.append("roles: " + " -> ".join(
            f"{role_id} ({purpose})" for role_id, purpose in ai.roles))
    if ai.team:
        lines.append(f"team: {ai.team}")
    lines.append("may_act: " + ("yes" if ai.may_act else "no"))
    lines.append("max_tool_calls: " + str(ai.max_tool_calls))
    lines.append("max_seconds: " + str(ai.max_seconds))
    return "\n".join(lines)


# ============================================================================
# StarkAgentExecutor — executes StarkAI goals through the orchestrator
# ============================================================================


class StarkAgentExecutor:
    """Executes a StarkAI goal through the existing Planner/Supervisor
    infrastructure with SecurityAgent gating.

    Every tool call passes PolicyEngine. Every action is audited through
    the EventStore. Stark agents operate within their declared budgets
    and permissions.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        policy: PolicyEngine,
        events: EventStore,
        supervisor: Any,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.events = events
        self.supervisor = supervisor
        self._security: SecurityAgent | None = None
        self._planner: Planner | None = None
        self._registry_agents: dict[str, Agent] = {}

        # Register all Stark AI agents into the AgentRegistry
        for stark in STARK_ROSTER:
            self._register_stark_agent(stark)

    # -- Stark agent registration ------------------------------------------

    def _register_stark_agent(self, stark: StarkAI) -> Agent:
        """Register a StarkAI as a real Agent in the AgentRegistry."""
        from ..tools.tools import default_registry as default_tools

        # Determine which tools this Stark AI can actually use
        available_tools = set(default_tools.keys()) if default_tools else set()
        allowed_tools = [t for t in stark.tools if t in available_tools]

        agent = Agent(
            name=stark.name,
            role=stark.role,
            model=stark.model,
            tools=allowed_tools,
            permissions=list(stark.permissions),
            memory_scope="shared",
            limits={
                "max_tool_calls": stark.max_tool_calls,
                "max_runtime_s": stark.max_seconds,
                "stark_ai_id": stark.ai_id,
                "stark_lineage": stark.lineage,
            },
            agent_id=stark.agent_id,
            state="idle",
        )

        self.registry.spawn(agent)
        self._registry_agents[stark.ai_id] = agent
        log.info("Stark AI registered",
                 ai_id=stark.ai_id,
                 name=stark.name,
                 role=stark.role,
                 agent_id=agent.agent_id,
                 tools=allowed_tools,
                 permissions=list(stark.permissions))
        return agent

    def get_agent(self, ai_id: str) -> Agent | None:
        """Get the registered Agent for a StarkAI by id."""
        return self._registry_agents.get(ai_id)

    def get_stark_ai(self, ai_id: str) -> StarkAI | None:
        """Get the StarkAI profile by id."""
        return STARK_ROSTER_BY_ID.get(ai_id)

    def list_stark_ais(self) -> list[StarkAI]:
        return list(STARK_ROSTER)

    # -- Execution ----------------------------------------------------------

    def execute(self, ai_id: str, goal: str,
                budgets: Any | None = None,
                require_approval: bool = True) -> dict[str, Any]:
        """Execute a goal through a Stark AI.

        The Stark AI's Planner generates a DAG, the SecurityAgent gates
        every tool call, and the Supervisor orchestrates execution.
        """
        stark = STARK_ROSTER_BY_ID.get(ai_id)
        if stark is None:
            raise ValueError(f"unknown Stark AI: {ai_id}")

        if not stark.may_act:
            return {
                "ok": False,
                "error": f"{stark.name} is not authorized to act",
                "ai_id": ai_id,
                "ai_name": stark.name,
                "reason": stark.limits[0] if stark.limits else "not authorized",
            }

        # Build the task goal with Stark context
        full_goal = f"[Stark AI: {stark.name} ({stark.ai_id})] {goal}"

        # Use the orchestrator to run the task
        # The Planner will generate steps, the SecurityAgent will gate them
        result = self.supervisor.run_task(
            goal=full_goal,
            priority=5,
        )

        # Enrich the result with Stark metadata
        result["stark"] = {
            "ai_id": stark.ai_id,
            "name": stark.name,
            "title": stark.title,
            "lineage": stark.lineage,
            "origin": stark.origin,
            "personality": list(stark.personality),
            "signature": stark.signature,
            "max_tool_calls": stark.max_tool_calls,
            "max_seconds": stark.max_seconds,
            "roles": [{"role_id": r, "purpose": p} for r, p in stark.roles],
        }

        return result

    def dispatch(self, ai_id: str, goal: str,
                 budgets: Any | None = None) -> dict[str, Any]:
        """Alias for execute() for CLI compatibility."""
        return self.execute(ai_id, goal, budgets=budgets)


# ============================================================================
# Module-level singleton
# ============================================================================

_stark_executor: StarkAgentExecutor | None = None


def get_stark_executor(
    registry: AgentRegistry | None = None,
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
    supervisor: Any = None,
) -> StarkAgentExecutor:
    """Get or create the StarkAgentExecutor singleton."""
    global _stark_executor
    if _stark_executor is None:
        _stark_executor = StarkAgentExecutor(
            registry=registry,
            policy=policy,
            events=events,
            supervisor=supervisor,
        )
    return _stark_executor


def reset_stark_executor() -> None:
    """Reset the singleton (for testing)."""
    global _stark_executor
    _stark_executor = None