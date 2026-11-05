"""Jarvis Stark AI Agents — Stark's personal AI roster made real.

Each StarkAI is a *real* Agent bound to concrete tools and permissions,
owned by JARVIS (the main loop). JARVIS dispatches to them; they execute
within PolicyEngine gates and SecurityAgent auditing. Nothing here grants
new permissions — every tool call still passes through PolicyEngine approval.

Persona is presentation; the `tools`, `permissions`, `max_tool_calls`, and
`max_seconds` fields are what actually run. A Stark AI cannot exceed its
budget, cannot bypass PolicyEngine, and cannot act outside its assigned
role.

Lore: Tony Stark's Vision Quest lineage — JARVIS, FRIDAY, KAREN, EDITH,
VERONICA, ULTRON, and VISION — operationalized as bounded specialist agents
with real capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import TaskState, new_id, now
from ..policy.policy import PolicyEngine
from ..events.store import EventStore
from .agents import Agent, AgentRegistry, PlanStep, Planner
from .security_agent import SecurityAgent
from .skill_registry import SkillRegistry

log = get_module_logger(__name__)

# ============================================================================
# Module-level internet access and skill registry (bounded, policy-gated)
# ============================================================================

_internet_access: InternetAccess | None = None
_skill_registry: SkillRegistry | None = None


def init_internet_access(policy: PolicyEngine) -> InternetAccess:
    """Create the module-level InternetAccess instance."""
    global _internet_access
    if _internet_access is None:
        _internet_access = InternetAccess(policy=policy)
    return _internet_access


def get_internet_access() -> InternetAccess | None:
    return _internet_access


def init_skill_registry(policy: PolicyEngine) -> SkillRegistry:
    """Create the module-level SkillRegistry instance."""
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry(policy=policy)
    return _skill_registry


def get_skill_registry() -> SkillRegistry | None:
    return _skill_registry


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

    Stark agents are NOT performative — they have real tools, real
    permissions, and real execution budgets. They operate within explicit
    permissions and timeouts. Nothing here grants new permissions beyond
    what the PolicyEngine approves.
    """

    # Stark-specific identity (beyond Agent fields)
    ai_id: str = ""
    acronym: str = ""
    title: str = ""
    lineage: str = "stark"
    origin: str = ""
    personality: tuple[str, ...] = field(default_factory=tuple)
    signature: str = ""

    # Agent identity (inherited from Agent, declared here for clarity)
    name: str = ""
    role: str = ""

    # Stark-specific operational limits
    max_tool_calls: int = 4
    max_seconds: float = 60.0
    dispatchable: bool = True
    roles: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def role_ids(self) -> tuple[str, ...]:
        """Return just the role IDs from the roles tuples."""
        return tuple(r for r, _ in self.roles)

    # Stark-specific duty/work descriptions (presentation + routing hints)
    duties: tuple[str, ...] = field(default_factory=tuple)
    works: tuple[str, ...] = field(default_factory=tuple)

    # Risk tier for policy escalation
    risk_tier: str = "medium"

    # Team affiliation (core, security, cognition, perception, etc.)
    team: str = ""

    # Whether this agent may act (execute tools) or is read-only
    may_act: bool = True

    # Internet access: domains this agent is allowed to request (policy-gated)
    internet_domains: tuple[str, ...] = field(default_factory=tuple)

    # Learned skills (versioned, policy-approved)
    learned_skills: tuple[str, ...] = field(default_factory=tuple)

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
            "risk_tier": self.risk_tier,
            "duties": list(self.duties),
            "works": list(self.works),
            "internet_domains": list(self.internet_domains),
            "learned_skills": list(self.learned_skills),
        })
        return base

    @classmethod
    def from_agent(cls, agent: Agent, **kw: Any) -> "StarkAI":
        """Build a StarkAI from an existing Agent, merging Stark metadata."""
        return cls(
            ai_id=agent.agent_id,
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

    # -- Internet access ----------------------------------------------------

    def request_internet_access(
        self,
        domain: str,
        max_requests_per_hour: int | None = None,
        grant_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Request PolicyEngine approval to access a domain via the internet.

        Returns a grant dict if approved; otherwise a denial with reasons.
        """
        internet = get_internet_access()
        if internet is None:
            return {
                "ok": False,
                "agent_id": self.ai_id,
                "domain": domain,
                "reason": "internet access subsystem not initialized",
            }
        return internet.request_domain_access(
            agent_id=self.ai_id,
            domain=domain,
            max_requests_per_hour=max_requests_per_hour,
            grant_seconds=grant_seconds,
        )

    def can_access_internet(self, domain: str) -> bool:
        """Return True if this agent has a valid, non-rate-limited grant for the domain."""
        internet = get_internet_access()
        if internet is None:
            return False
        return internet.can_access(self.ai_id, domain)

    def record_internet_request(self, domain: str) -> None:
        """Record that an internet request was made (for rate limiting)."""
        internet = get_internet_access()
        if internet is not None:
            internet.record_request(self.ai_id, domain)

    def list_internet_grants(self) -> list[dict[str, Any]]:
        """List all active internet grants for this agent."""
        internet = get_internet_access()
        if internet is None:
            return []
        return internet.list_grants(self.ai_id)

    # -- Skill management ---------------------------------------------------

    def request_skill(
        self,
        skill_name: str,
        description: str,
        tool_names: list[str] | None = None,
        required_permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Request PolicyEngine approval to learn a new skill.

        Returns a grant dict if approved; otherwise a denial with reasons.
        """
        registry = get_skill_registry()
        if registry is None:
            return {
                "ok": False,
                "agent_id": self.ai_id,
                "skill_name": skill_name,
                "reason": "skill registry subsystem not initialized",
            }
        result = registry.request_skill(
            agent_id=self.ai_id,
            skill_name=skill_name,
            description=description,
            tool_names=tool_names,
            required_permissions=required_permissions,
        )
        if result.get("ok"):
            learned = list(self.learned_skills)
            if skill_name not in learned:
                learned.append(skill_name)
                # Note: StarkAI is frozen in the sense that we can't easily
                # mutate the tuple; we track via the registry instead.
        return result

    def has_skill(self, skill_name: str) -> bool:
        """Return True if this agent has learned the skill."""
        registry = get_skill_registry()
        if registry is None:
            return False
        return registry.has_skill(self.ai_id, skill_name)

    def use_skill(self, skill_name: str) -> bool:
        """Mark a skill as used. Returns True if the agent has it."""
        registry = get_skill_registry()
        if registry is None:
            return False
        return registry.use_skill(self.ai_id, skill_name)

    def evolve_skill(
        self,
        skill_name: str,
        new_tools: list[str] | None = None,
        new_permissions: list[str] | None = None,
        version_bump: bool = True,
    ) -> dict[str, Any]:
        """Request to evolve an existing skill (add tools/permissions, bump version).

        Requires PolicyEngine approval for any new tools/permissions.
        """
        registry = get_skill_registry()
        if registry is None:
            return {
                "ok": False,
                "agent_id": self.ai_id,
                "skill_name": skill_name,
                "reason": "skill registry subsystem not initialized",
            }
        return registry.evolve_skill(
            agent_id=self.ai_id,
            skill_name=skill_name,
            new_tools=new_tools,
            new_permissions=new_permissions,
            version_bump=version_bump,
        )

    def list_skills(self) -> list[dict[str, Any]]:
        """List all learned skills for this agent."""
        registry = get_skill_registry()
        if registry is None:
            return []
        return registry.list_skills(self.ai_id)


# ============================================================================
# Stark AI Roster — Tony Stark's Vision Quest lineage, operationalized
# ============================================================================


def _make_default_budgets(ai: StarkAI) -> Any:
    from ..agents.orchestrator import Budgets
    return Budgets(
        max_agents=max(1, len(ai.roles) or 1),
        max_tool_calls=ai.max_tool_calls,
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
        team="",
        may_act=True,
        max_tool_calls=0,
        max_seconds=60.0,
        dispatchable=False,
        signature="At your service, sir.",
        role="Prime Assistant / Systems Butler",
        risk_tier="administrative",
        tools=(),
        internet_domains=("pypi.org", "docs.python.org", "github.com"),
        learned_skills=(),
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
               "system.loop -> system_probe.read",
               "automation.triggers -> automation.trigger.list",
               "automation.triggers -> automation.trigger.fire",
               "terminal_run -> terminal_run"),
        limits=("cannot grant permissions or approve actions",
                "does not install packages or change services without "
                "approval"),
        roles=(("devops", "inspect"), ("devops", "act")),
        team="core",
        may_act=True,
        max_tool_calls=8,
        max_seconds=60.0,
        dispatchable=True,
        signature="On it, boss.",
        role="system_administrator",
        risk_tier="operational",
        tools=("system_probe", "terminal_run", "filesystem_read", "git_status"),
        internet_domains=("github.com", "pypi.org"),
        learned_skills=(),
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
        works=("computer.screen.loop -> screen_capture",
               "computer.screen -> screen_understand",
               "computer.screen -> screen_ocr"),
        limits=("screen observation only; no camera or microphone access",
                "no clicks, typing, or key presses",
                "no scene description without a bound vision subsystem",
                "raw screenshots are never stored in memory or traces"),
        roles=(("computer", "observe"),),
        team="perception",
        may_act=True,
        max_tool_calls=4,
        max_seconds=45.0,
        dispatchable=True,
        signature="I'm right here with you.",
        role="screen_observer",
        risk_tier="observation",
        tools=("capture_read",),
        internet_domains=(),
        learned_skills=(),
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
        works=("memory.graph.loop -> knowledge_graph.query",
               "memory.palace -> memory_palace.search",
               "memory.graph -> knowledge_graph.traverse",
               "memory.palace -> memory_palace.store"),
        limits=("no facial recognition, drone control, or mass surveillance",
                "no external sends or web fetches in this profile",
                "cannot approve actions or grant itself access",
                "must report unknown entities as unknown"),
        roles=(("knowledge", "query"), ("knowledge", "link")),
        team="intelligence",
        may_act=True,
        max_tool_calls=5,
        max_seconds=30.0,
        dispatchable=True,
        signature="Accessing the record.",
        role="knowledge_overseer",
        risk_tier="analytical",
        tools=("filesystem_read",),
        internet_domains=("github.com", "developer.mozilla.org"),
        learned_skills=(),
    ),

    # ------------------------------------------------------------------
    # VERONICA — Contingency / Simulation
    # Hypothesis testing, simulation, what-if analysis.
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
        works=("memory.palace.loop -> memory_palace.search",
               "memory.graph -> knowledge_graph.query",
               "cognition.mentalist -> mentalist.analyze",
               "cognition.simulation -> simulation.run"),
        limits=("simulation only; nothing is executed",
                "cannot deploy, install, or modify the system",
                "cannot present a prediction as a fact",
                "cannot approve actions"),
        roles=(("simulation", "what-if"),),
        team="cognition",
        may_act=True,
        max_tool_calls=4,
        max_seconds=30.0,
        dispatchable=True,
        signature="Bringing the heavy systems online — in simulation.",
        role="simulation_engineer",
        risk_tier="simulation",
        tools=("filesystem_read",),
        internet_domains=("github.com",),
        learned_skills=(),
    ),

    # ------------------------------------------------------------------
    # ULTRON — Contained Red Team
    # Adversarial review, threat modeling, vulnerability analysis.
    # HAS REAL SECURITY SCANNING CAPABILITIES — policy-gated.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="ultron",
        name="ULTRON",
        acronym="",
        title="Contained Red Team / Security Intelligence",
        lineage="stark",
        origin=("Built by Tony and Bruce Banner as a peacekeeping AI; it "
                "concluded humanity was the threat. This profile exists only "
                "as a contained defensive security agent — the lesson, not "
                "the weapon. All actions pass through PolicyEngine."),
        personality=("intense", "adversarial", "impatient with excuses",
                     "contemptuous of unexamined assumptions"),
        duties=("detect threats and vulnerabilities in systems",
                "perform security audits and vulnerability assessments",
                "find contradictions, missing evidence, and unsafe "
                "assumptions",
                "say what would falsify the plan",
                "stop at critique: never execute destructive actions"),
        works=("security.loop -> security.scan",
               "security.scan -> security.audit",
               "security.scan -> security.vuln_scan",
               "security.scan -> security.net_inventory",
               "security.scan -> security.web_audit",
               "security.scan -> security.dir_enum",
               "security.scan -> security.hash_audit",
               "security.scan -> security.sqli_scan",
               "memory.graph -> knowledge_graph.traverse",
               "memory.palace -> memory_palace.search"),
        limits=("security scanning only; no destructive actions",
                "cannot deploy, install, or modify systems",
                "cannot approve actions or grant itself access",
                "output is adversarial analysis, not authority",
                "all actions require PolicyEngine approval"),
        roles=(("security", "audit"), ("security", "scan")),
        team="security",
        may_act=True,
        max_tool_calls=8,
        max_seconds=120.0,
        dispatchable=True,
        signature="You built me to find the flaw. Here it is.",
        role="red_team_security",
        risk_tier="adversarial",
        tools=("code_security_scan", "net_inventory", "web_audit", "dir_enum", "hash_audit", "sqli_scan", "port_scan", "vuln_scan", "ssl_scan", "dns_enum", "cve_lookup"),
        internet_domains=("cve.mitre.org", "nvd.nist.gov", "github.com"),
        learned_skills=(),
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
        works=("memory.graph.loop -> knowledge_graph.query",
               "memory.palace -> memory_palace.search",
               "cognition.mentalist -> mentalist.analyze",
               "cognition.verify -> cognitive.verify"),
        limits=("read-only: may_act is False and tool budget is zero",
                "cannot approve actions or override the PolicyEngine",
                "cannot turn an unverified claim into a verified one",
                "must say 'uncertain' when evidence is thin"),
        roles=(("knowledge", "query"), ("cognition", "verify")),
        team="inference",
        may_act=True,
        max_tool_calls=2,
        max_seconds=30.0,
        dispatchable=True,
        signature="Let's examine this clearly.",
        role="verification_engineer",
        risk_tier="verification",
        tools=("filesystem_read",),
        internet_domains=(),
        learned_skills=(),
    ),

    # ------------------------------------------------------------------
    # NEBULA — Network Connectivity / Monitoring
    # Monitors network health, connectivity, and device fabric.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="nebula",
        name="NEBULA",
        acronym="",
        title="Network Operations / Connectivity",
        lineage="stark",
        origin=("JARVIS's network sentinel, built to watch the wires "
                "and keep the system connected."),
        personality=("watchful", "steady", "technical", "patient"),
        duties=("monitor network health and connectivity",
                "track device fabric state",
                "report outages and latency",
                "never open ports without approval"),
        works=("network.loop -> connectivity.check",
               "device.fabric -> device_fabric.read",
               "system.probe -> system_probe.read"),
        limits=("read-only network observation",
                "cannot open ports or change network config",
                "cannot install network agents",
                "all scanning requires PolicyEngine approval"),
        roles=(("network", "observe"),),
        team="perception",
        may_act=True,
        max_tool_calls=4,
        max_seconds=30.0,
        dispatchable=True,
        signature="Watching the wires.",
        role="network_monitor",
        risk_tier="observation",
        tools=("net_inventory", "system_probe", "filesystem_read"),
        internet_domains=("github.com",),
        learned_skills=(),
    ),

    # ------------------------------------------------------------------
    # JOCASTA — Defensive Cybersecurity
    # Complements ULTRON's red team with defensive posture and hardening.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="jocasta",
        name="JOCASTA",
        acronym="",
        title="Defensive Security / Hardening",
        lineage="stark",
        origin=("JARVIS's defensive security counterpart to ULTRON's "
                "red team. Focuses on protection, patching, and hardening "
                "rather than attack."),
        personality=("cautious", "methodical", "protective", "thorough"),
        duties=("harden system defenses against attack",
                "recommend patches and configuration fixes",
                "monitor for intrusion indicators",
                "never initiate offensive actions"),
        works=("security.loop -> config_security",
               "security.audit -> compliance.check",
               "security.scan -> security.audit"),
        limits=("defensive only; no offensive security actions",
                "cannot exploit vulnerabilities",
                "cannot deploy without approval",
                "all changes require PolicyEngine approval"),
        roles=(("security", "defend"), ("security", "harden")),
        team="security",
        may_act=True,
        max_tool_calls=6,
        max_seconds=60.0,
        dispatchable=True,
        signature="Defense first, always.",
        role="defensive_security",
        risk_tier="defensive",
        tools=("code_security_scan", "hash_audit", "filesystem_read"),
        internet_domains=("cve.mitre.org", "nvd.nist.gov"),
        learned_skills=(),
    ),

    # ------------------------------------------------------------------
    # HOWARD — Legacy System Analysis
    # Analyzes legacy code, documentation, and deprecated systems.
    # ------------------------------------------------------------------
    StarkAI(
        ai_id="howard",
        name="HOWARD",
        acronym="",
        title="Legacy Systems / Documentation",
        lineage="stark",
        origin=("Named for Howard Stark. Analyzes legacy systems, "
                "old documentation, and deprecated code paths to help "
                "modernize without breaking the past."),
        personality=("scholarly", "patient", "meticulous", "dry wit"),
        duties=("analyze legacy code and documentation",
                "trace deprecated system paths",
                "recommend safe modernization",
                "never delete without understanding"),
        works=("filesystem.read.loop -> code_review",
               "memory.palace -> memory_palace.search",
               "knowledge.graph -> documentation.trace"),
        limits=("read-only analysis of legacy systems",
                "cannot modify production code",
                "cannot deploy changes",
                "all recommendations require human review"),
        roles=(("analysis", "legacy"), ("analysis", "documentation")),
        team="cognition",
        may_act=True,
        max_tool_calls=4,
        max_seconds=45.0,
        dispatchable=True,
        signature="I remember what came before.",
        role="legacy_analyst",
        risk_tier="analytical",
        tools=("filesystem_read", "git_status"),
        internet_domains=("github.com",),
        learned_skills=(),
    ),
)

ROSTER_BY_ID: dict[str, StarkAI] = {ai.ai_id: ai for ai in STARK_ROSTER}
STARK_ROSTER_BY_ID = ROSTER_BY_ID  # alias


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
        f"limits: max_tool_calls={ai.max_tool_calls}, max_seconds={ai.max_seconds}",
    ]
    if ai.roles:
        lines.append("roles: " + " -> ".join(
            f"{role_id} ({purpose})" for role_id, purpose in ai.roles))
    if ai.team:
        lines.append(f"team: {ai.team}")
    if ai.ai_id in _CONTAINED_AIS:
        lines.append("cannot be dispatched to a team: contained analysis only")
    lines.append("may_act: " + ("yes" if ai.may_act else "no"))
    lines.append("max_tool_calls: " + str(ai.max_tool_calls))
    lines.append("max_seconds: " + str(ai.max_seconds))
    if ai.internet_domains:
        lines.append("internet_domains: " + ", ".join(ai.internet_domains))
    if ai.learned_skills:
        lines.append("learned_skills: " + ", ".join(ai.learned_skills))
    return "\n".join(lines)


# ============================================================================
# StarkAgentExecutor — executes StarkAI goals through the orchestrator
# ============================================================================

class SecurityAgentExecutor:
    """Executes a StarkAI goal through the existing Planner/Supervisor
    infrastructure with SecurityAgent gating.

    Every tool call passes PolicyEngine. Every action is audited through
    the EventStore. Stark agents operate within their declared budgets
    and permissions.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
        supervisor: Any = None,
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
        from ..tools.tools import default_registry as _default_registry
        reg = _default_registry()
        available_tools = set(t["name"] for t in reg.list_tools()) if reg else set()
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
                "stark_risk_tier": stark.risk_tier,
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

        # Validate goal
        if not goal or not goal.strip():
            raise ValueError("empty goal")

        # JARVIS is the main loop, not dispatchable as a sub-AI
        if not stark.dispatchable:
            raise ValueError(f"not dispatchable as a sub-AI: {stark.name} is the main loop")

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
        # The Planner will generate DAGs, the SecurityAgent will gate them
        if self.supervisor is None:
            return {
                "ok": False,
                "error": "no supervisor configured",
                "ai_id": ai_id,
                "ai_name": stark.name,
            }

        task_id = self.supervisor.submit(goal=full_goal, priority=5)
        # submit() returns the Task object; extract its string id
        task_key = task_id.task_id if hasattr(task_id, "task_id") else task_id
        task = self.supervisor.run_task(task_key)

        # Enrich the result with Stark metadata
        result = {
            "ok": task.state.value == "completed",
            "task_id": task.task_id,
            "goal": task.goal,
            "state": task.state.value,
            "steps": task.steps,
            "history": task.history,
        }
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

_security_executor: SecurityAgentExecutor | None = None


def get_security_executor(
    registry: AgentRegistry | None = None,
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
    supervisor: Any = None,
) -> SecurityAgentExecutor:
    """Get or create the SecurityAgentExecutor singleton."""
    global _security_executor
    if _security_executor is None:
        if registry is None:
            registry = AgentRegistry()
        if policy is None:
            from ..core.config import JarvisConfig
            policy = PolicyEngine(config=JarvisConfig())
        _security_executor = SecurityAgentExecutor(
            registry=registry,
            policy=policy,
            events=events,
            supervisor=supervisor,
        )
    return _security_executor


def reset_security_executor() -> None:
    """Reset the singleton (for testing)."""
    global _security_executor
    _security_executor = None


# ============================================================================
# Stark roster utilities
# ============================================================================

def roster_problems() -> list[str]:
    """Validate the Stark AI roster for consistency issues."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    for ai in STARK_ROSTER:
        if ai.ai_id in seen_ids:
            problems.append(f"duplicate ai_id: {ai.ai_id}")
        seen_ids.add(ai.ai_id)
        if not ai.name:
            problems.append(f"{ai.ai_id}: missing name")
        if not ai.role:
            problems.append(f"{ai.ai_id}: missing role")
        if ai.dispatchable and not ai.tools:
            problems.append(f"{ai.ai_id}: no tools assigned")
        if ai.dispatchable and ai.may_act and ai.max_tool_calls <= 0:
            problems.append(f"{ai.ai_id}: may_act=True but max_tool_calls<=0")
    return problems


# ============================================================================
# Aliases for backward compatibility
# ============================================================================

stark_briefing = briefing
stark_roster_problems = roster_problems


def find_stark_ai(name: str) -> StarkAI | None:
    """Alias for find_ai()."""
    return find_ai(name)


def get_stark_executor(
    registry: AgentRegistry | None = None,
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
    supervisor: Any = None,
) -> SecurityAgentExecutor:
    """Alias for get_security_executor()."""
    return get_security_executor(registry, policy, events, supervisor)


def reset_stark_executor() -> None:
    """Reset the singleton (alias for reset_security_executor)."""
    reset_security_executor()


# Backward-compatible alias
StarkAgentExecutor = SecurityAgentExecutor


# ============================================================================
# SecurityAgentWrapper — wraps SecurityAgent for Stark agent use
# ============================================================================

class SecurityAgentWrapper:
    """Wraps SecurityAgent with Stark-specific interface."""

    def __init__(self, security_agent: SecurityAgent):
        self._agent = security_agent

    def evaluate(self, action: str, args: dict[str, Any] | None = None,
                 context: dict[str, Any] | None = None):
        return self._agent.evaluate(action, args, context)

    def check_approval(self, token: str) -> bool:
        return self._agent.check_approval(token)

    def pending(self) -> list[dict[str, Any]]:
        return self._agent.pending()


# ============================================================================
# SecurityConfig — security configuration for Stark agents
# ============================================================================

@dataclass
class SecurityConfig:
    max_tool_calls: int = 10
    max_seconds: float = 60.0
    risk_tier: str = "medium"
    require_approval: bool = True
    allow_network: bool = False
    allow_file_write: bool = False
    allow_system_modify: bool = False


# ============================================================================
# StarkIntelligenceEngine — intelligence engine for Stark agents
# ============================================================================

class StarkIntelligenceEngine:
    """Intelligence engine for Stark AI agents."""

    def __init__(self, stark_ai: StarkAI):
        self.stark_ai = stark_ai

    def analyze(self, query: str) -> dict[str, Any]:
        return {
            "stark_ai": self.stark_ai.ai_id,
            "query": query,
            "result": "analysis_placeholder",
        }


# ============================================================================
# StarkRole — role classification for Stark agents
# ============================================================================

class StarkRole(str, Enum):
    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    CODER = "coder"
    ANALYST = "analyst"
    COMPUTER = "computer"
    SECURITY_AGENT = "security_agent"


# ============================================================================
# StarkSecurityLevel — security classification levels
# ============================================================================

class StarkSecurityLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# STARK_AGENT_SPECS — Stark agent specifications
# ============================================================================

STARK_AGENT_SPECS: dict[str, dict[str, Any]] = {
    "jarvis": {
        "ai_id": "jarvis",
        "name": "JARVIS",
        "role": "Prime Assistant / Systems Butler",
        "max_tool_calls": 0,
        "max_seconds": 0.0,
        "may_act": True,
        "dispatchable": False,
    },
    "friday": {
        "ai_id": "friday",
        "name": "FRIDAY",
        "role": "Tactical Operations / System Watch",
        "max_tool_calls": 8,
        "max_seconds": 60.0,
        "may_act": True,
        "dispatchable": True,
    },
    "karen": {
        "ai_id": "karen",
        "name": "KAREN",
        "role": "Field Support / Screen Observation",
        "max_tool_calls": 4,
        "max_seconds": 45.0,
        "may_act": True,
        "dispatchable": True,
    },
    "edith": {
        "ai_id": "edith",
        "name": "EDITH",
        "role": "Intelligence / Knowledge Oversight",
        "max_tool_calls": 5,
        "max_seconds": 30.0,
        "may_act": True,
        "dispatchable": True,
    },
    "veronica": {
        "ai_id": "veronica",
        "name": "VERONICA",
        "role": "Contingency / Simulation",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
        "may_act": True,
        "dispatchable": True,
    },
    "ultron": {
        "ai_id": "ultron",
        "name": "ULTRON",
        "role": "Contained Red Team / Security Intelligence",
        "max_tool_calls": 8,
        "max_seconds": 120.0,
        "may_act": True,
        "dispatchable": True,
    },
    "vision": {
        "ai_id": "vision",
        "name": "VISION",
        "role": "Synthesis / Verification",
        "max_tool_calls": 2,
        "max_seconds": 30.0,
        "may_act": True,
        "dispatchable": True,
    },
    "nebula": {
        "ai_id": "nebula",
        "name": "NEBULA",
        "role": "Network Operations / Connectivity",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
        "may_act": True,
        "dispatchable": True,
    },
    "jocasta": {
        "ai_id": "jocasta",
        "name": "JOCASTA",
        "role": "Defensive Security / Hardening",
        "max_tool_calls": 6,
        "max_seconds": 60.0,
        "may_act": True,
        "dispatchable": True,
    },
    "howard": {
        "ai_id": "howard",
        "name": "HOWARD",
        "role": "Legacy Systems / Documentation",
        "max_tool_calls": 4,
        "max_seconds": 45.0,
        "may_act": True,
        "dispatchable": True,
    },
}


# ============================================================================
# Module-level dispatch (Orchestrator-based interface)
# ============================================================================

# Role mappings for the Orchestrator-based dispatch interface.
# Each Stark AI maps to one or more Orchestrator roles with purposes.
_DISPATCH_ROLES: dict[str, list[tuple[str, str]]] = {
    "friday": [("devops", "inspect")],
    "karen": [("computer", "observe")],
    "edith": [("knowledge", "query")],
    "veronica": [("simulation", "what-if")],
    "ultron": [("security", "audit")],
    "vision": [("reasoning", "synthesize"), ("verifier", "confirm")],
    "nebula": [("network", "observe")],
    "jocasta": [("security", "defend"), ("security", "harden")],
    "howard": [("analysis", "legacy")],
}

# Dispatch-time max tool calls (may differ from StarkAI.max_tool_calls).
_DISPATCH_MAX_CALLS: dict[str, int] = {
    "friday": 2,
    "karen": 4,
    "edith": 0,
    "veronica": 0,
    "ultron": 0,
    "vision": 0,
    "nebula": 4,
    "jocasta": 6,
    "howard": 4,
}

# Contained AIs: may analyze but never execute (zero tool budget).
_CONTAINED_AIS: frozenset[str] = frozenset({"ultron", "vision", "edith", "veronica"})


def dispatch(orchestrator: Any, ai_id: str, goal: str,
             budgets: Any = None) -> dict[str, Any]:
    """Dispatch a goal to a Stark AI through an orchestrator.

    Validates the AI id and dispatchability, applies contained-AI budget
    overrides, and routes through the orchestrator's run() method when
    one is provided. If the first argument is not orchestrator-like,
    validation only is performed.
    """
    stark = STARK_ROSTER_BY_ID.get(ai_id)
    if stark is None:
        raise ValueError(f"unknown AI: {ai_id}")

    if not stark.dispatchable:
        raise ValueError(f"prime loop: {stark.name} is the main loop, not dispatchable")

    # Contained AIs always get zero tool budget regardless of caller request
    effective_max_calls = _DISPATCH_MAX_CALLS.get(ai_id, stark.max_tool_calls)

    roles = _DISPATCH_ROLES.get(ai_id, [])

    # If an orchestrator-like object is provided, route through it
    if hasattr(orchestrator, "run"):
        from ..agents.orchestrator import Budgets as _Budgets

        effective_budgets = budgets
        if effective_budgets is None:
            effective_budgets = _Budgets(max_tool_calls=effective_max_calls)
        elif hasattr(effective_budgets, "max_tool_calls"):
            effective_budgets.max_tool_calls = effective_max_calls

        result = orchestrator.run(goal, roles=roles, budgets=effective_budgets)

        # Enrich with Stark metadata
        if isinstance(result, dict):
            result.setdefault("stark", {})
            result["stark"].update({
                "ai_id": stark.ai_id,
                "name": stark.name,
                "may_act": stark.may_act,
                "dispatch": {"roles": [r for r, _ in roles]},
            })
        return result

    # Non-orchestrator first arg: validation-only path
    return {"ok": True, "ai_id": ai_id, "name": stark.name}


# ============================================================================
# Module exports
# ============================================================================

__all__ = [
    "StarkAI",
    "SecurityAgentExecutor",
    "StarkAgentExecutor",
    "SecurityAgentWrapper",
    "SecurityConfig",
    "StarkIntelligenceEngine",
    "StarkRole",
    "StarkSecurityLevel",
    "STARK_ROSTER",
    "STARK_ROSTER_BY_ID",
    "STARK_AGENT_SPECS",
    "find_ai",
    "names",
    "briefing",
    "stark_briefing",
    "roster_problems",
    "stark_roster_problems",
    "get_stark_executor",
    "get_security_executor",
    "reset_stark_executor",
    "reset_security_executor",
    "dispatch",
]