"""
Expanded Stark AI Roster — 500 StarkAI agents.

Generates 500 StarkAI agents across 10 operational categories (50 each),
all bounded by PolicyEngine, SecurityAgent auditing, and explicit tool
budgets. No agent can bypass PolicyEngine or exceed its declared limits.

Categories:
  security    (50) - ULTRON/JOCASTA lineage, red & blue team
  operations  (50) - FRIDAY lineage, system ops, devops
  perception  (50) - KAREN lineage, screen & field observation
  intelligence(50) - EDITH lineage, knowledge & research oversight
  simulation  (50) - VERONICA lineage, contingency & simulation
  cognition   (50) - reasoning, planning, analysis
  network     (50) - NEBULA lineage, connectivity & device fabric
  legacy      (50) - HOWARD lineage, documentation & legacy systems
  research    (50) - research specialists, literature review
  general     (50) - JARVIS lineage, assistants, coordinators

Each agent gets a unique ai_id, name, title, role, tools, permissions,
max_tool_calls, max_seconds, risk_tier, team, and personality.
"""

from __future__ import annotations

from dataclasses import field
from typing import Any

from .stark import StarkAI

__all__ = [
    "STARK_ROSTER_500",
    "stark_roster_500_by_id",
    "generate_stark_agents",
    "count_by_category",
    "list_categories",
]

# ---------------------------------------------------------------------------
# Category definitions: (name, team, base_role, risk_tier, base_tools)
# ---------------------------------------------------------------------------

_CATEGORIES: dict[str, dict[str, Any]] = {
    "security": {
        "team": "security",
        "base_role": "security_engineer",
        "risk_tier": "adversarial",
        "base_tools": (
            "code_security_scan", "hash_audit", "filesystem_read",
            "system_probe", "net_inventory", "web_audit",
            "dir_enum", "sqli_scan", "port_scan", "vuln_scan",
            "ssl_scan", "dns_enum", "cve_lookup",
        ),
        "personality": ("intense", "meticulous", "adversarial", "cautious"),
        "duties": (
            "scan for vulnerabilities",
            "audit code and configurations",
            "report security findings",
            "recommend hardening measures",
        ),
        "works": ("security_scanning", "vulnerability_assessment", "compliance_audit"),
    },
    "operations": {
        "team": "core",
        "base_role": "system_administrator",
        "risk_tier": "operational",
        "base_tools": (
            "system_probe", "terminal_run", "filesystem_read",
            "filesystem_write", "git_status", "automation_trigger",
        ),
        "personality": ("quick", "tactical", "reliable", "informal"),
        "duties": (
            "monitor system health",
            "execute operational tasks",
            "report status plainly",
            "escalate risky actions",
        ),
        "works": ("system_administration", "device_monitoring", "automation"),
    },
    "perception": {
        "team": "perception",
        "base_role": "field_observer",
        "risk_tier": "observation",
        "base_tools": ("capture_read", "screen_understand", "screen_ocr", "filesystem_read"),
        "personality": ("friendly", "protective", "patient", "observant"),
        "duties": (
            "capture screen when asked",
            "return capture scope and path",
            "stop when policy requires",
            "never store raw screenshots",
        ),
        "works": ("screen_observation", "field_support", "visual_capture"),
    },
    "intelligence": {
        "team": "intelligence",
        "base_role": "knowledge_overseer",
        "risk_tier": "analytical",
        "base_tools": ("filesystem_read", "memory_palace_search", "knowledge_graph_query"),
        "personality": ("cool", "procedural", "mission-focused", "neutral"),
        "duties": (
            "link requests to known entities",
            "surface provenance and missing evidence",
            "separate fact from hypothesis",
            "refuse surveillance-shaped requests",
        ),
        "works": ("knowledge_graph_query", "memory_search", "entity_resolution"),
    },
    "simulation": {
        "team": "cognition",
        "base_role": "simulation_engineer",
        "risk_tier": "simulation",
        "base_tools": ("filesystem_read", "memory_palace_search", "simulation_run"),
        "personality": ("steady", "engineering-focused", "contingency-minded", "unexcitable"),
        "duties": (
            "stress-test plans before execution",
            "name failure modes and missing resources",
            "keep answers labelled hypothetical",
            "recommend dry runs when risk is unclear",
        ),
        "works": ("plan_stress_test", "what_if_analysis", "contingency_planning"),
    },
    "cognition": {
        "team": "cognition",
        "base_role": "cognitive_engineer",
        "risk_tier": "analytical",
        "base_tools": ("filesystem_read", "memory_palace_search", "python_run", "reasoning_engine"),
        "personality": ("deliberate", "ethical", "calm", "philosophical"),
        "duties": (
            "synthesize available evidence",
            "check claims match provenance",
            "mark verified/failed/uncertain honestly",
            "refuse to bless unchecked results",
        ),
        "works": ("evidence_synthesis", "claim_verification", "hypothesis_validation"),
    },
    "network": {
        "team": "perception",
        "base_role": "network_monitor",
        "risk_tier": "observation",
        "base_tools": ("net_inventory", "system_probe", "filesystem_read", "connectivity_check"),
        "personality": ("watchful", "steady", "technical", "patient"),
        "duties": (
            "monitor network health and connectivity",
            "track device fabric state",
            "report outages and latency",
            "never open ports without approval",
        ),
        "works": ("network_monitoring", "connectivity_check", "device_fabric_read"),
    },
    "legacy": {
        "team": "cognition",
        "base_role": "legacy_analyst",
        "risk_tier": "analytical",
        "base_tools": ("filesystem_read", "git_status", "documentation_trace"),
        "personality": ("scholarly", "patient", "meticulous", "dry wit"),
        "duties": (
            "analyze legacy code and documentation",
            "trace deprecated system paths",
            "recommend safe modernization",
            "never delete without understanding",
        ),
        "works": ("legacy_code_analysis", "documentation_trace", "modernization_planning"),
    },
    "research": {
        "team": "intelligence",
        "base_role": "researcher",
        "risk_tier": "analytical",
        "base_tools": ("web_fetch", "filesystem_read", "memory_palace_search"),
        "personality": ("curious", "thorough", "cautious", "systematic"),
        "duties": (
            "investigate topics thoroughly",
            "find and cite sources",
            "summarize findings with confidence levels",
            "flag unverified claims",
        ),
        "works": ("topic_research", "source_citation", "literature_review"),
    },
    "general": {
        "team": "core",
        "base_role": "assistant",
        "risk_tier": "medium",
        "base_tools": ("filesystem_read", "filesystem_write", "system_probe"),
        "personality": ("calm", "precise", "helpful", "loyal"),
        "duties": (
            "route work to the right subsystem",
            "remember operator context",
            "ask before risky actions",
            "run the main cognitive loop",
        ),
        "works": ("task_routing", "context_management", "general_assistance"),
    },
}

# Base suffixes for agent naming within each category
_SUFFIXES = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
    "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
    "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
    "xray", "yankee", "zulu", "aurora", "nova", "orion", "lyra", "sirius",
    "vega", "cassiopeia", "andromeda", "pegasus", "phoenix", "atlas",
    "hercules", "perseus", "icarus", "daedalus", "prometheus", "chronos",
    "aeon", "zenith", "nadir", "eclipse", "horizon", "eventide",
]


def _make_agent(
    category: str,
    index: int,
    cat_cfg: dict[str, Any],
) -> StarkAI:
    """Create a single StarkAI agent for the given category and index."""
    suffix = _SUFFIXES[index % len(_SUFFIXES)]
    tier_index = index // len(_SUFFIXES)
    ai_id = f"stark-{category}-{suffix}-{tier_index:02d}"
    name = f"{category.upper()}-{suffix.upper()}-{tier_index:02d}"
    acronym = f"{category[:3].upper()}-{suffix[:3].upper()}"

    # Vary tool budget by index within category
    base_calls = {"security": 8, "operations": 6, "perception": 4,
                  "intelligence": 5, "simulation": 4, "cognition": 4,
                  "network": 4, "legacy": 4, "research": 6, "general": 4}[category]
    max_calls = base_calls + (index % 6)
    max_seconds = 30.0 + (index % 90)

    # Select a subset of base tools (not all agents get all tools)
    tools = cat_cfg["base_tools"]
    tool_subset = tools[: min(len(tools), 3 + (index % 5))]

    # Assigned jobs per category
    job_map = {
        "security": (
            "vulnerability_scanner", "security_auditor", "threat_hunter",
            "intrusion_analyst", "compliance_checker", "red_team_analyst",
            "blue_team_defender", "incident_responder", "code_security_reviewer",
            "network_security_monitor",
        ),
        "operations": (
            "system_administrator", "devops_engineer", "site_reliability_engineer",
            "system_monitor", "automation_operator", "incident_coordinator",
            "health_check_operator", "resource_manager", "deployment_coordinator",
        ),
        "perception": (
            "screen_observer", "field_support_agent", "visual_capture_analyst",
            "ocr_operator", "scene_describer", "observation_recorder",
        ),
        "intelligence": (
            "knowledge_overseer", "entity_resolver", "provenance_analyst",
            "knowledge_graph_querier", "memory_search_operator", "fact_checker",
        ),
        "simulation": (
            "simulation_engineer", "contingency_planner", "what_if_analyst",
            "plan_stress_tester", "failure_mode_analyst", "dry_run_coordinator",
        ),
        "cognition": (
            "cognitive_engineer", "evidence_synthesizer", "claim_verifier",
            "hypothesis_validator", "reasoning_analyst", "world_model_operator",
        ),
        "network": (
            "network_monitor", "connectivity_analyst", "device_fabric_observer",
            "outage_reporter", "latency_tracker", "port_watcher",
        ),
        "legacy": (
            "legacy_code_analyst", "documentation_tracer", "modernization_planner",
            "deprecated_system_reviewer", "code_archaeologist", "migration_advisor",
        ),
        "research": (
            "researcher", "source_citation_analyst", "literature_reviewer",
            "topic_investigator", "unverified_claim_flagger", "web_researcher",
        ),
        "general": (
            "assistant", "task_router", "context_manager", "general_helper",
            "cognitive_loop_operator", "operator_liaison",
        ),
    }

    # Vary internet domains by category
    internet_map = {
        "security": ("cve.mitre.org", "nvd.nist.gov", "github.com"),
        "operations": ("github.com", "pypi.org"),
        "perception": (),
        "intelligence": ("github.com", "developer.mozilla.org"),
        "simulation": ("github.com",),
        "cognition": ("github.com",),
        "network": ("github.com",),
        "legacy": ("github.com",),
        "research": ("github.com", "arxiv.org", "en.wikipedia.org"),
        "general": ("pypi.org", "docs.python.org", "github.com"),
    }

    return StarkAI(
        ai_id=ai_id,
        name=name,
        acronym=acronym,
        title=f"{cat_cfg['base_role'].replace('_', ' ').title()} {suffix.title()}",
        lineage="stark",
        origin=f"Expanded Stark AI roster — {category} category, agent {index + 1} of 50.",
        personality=cat_cfg["personality"],
        duties=cat_cfg["duties"],
        works=cat_cfg["works"],
        limits=(
            f"{category} category agent — bounded by PolicyEngine",
            "cannot bypass security gates or exceed declared tool budget",
            "every tool call requires explicit approval",
        ),
        roles=((cat_cfg["base_role"], "execute"),),
        team=cat_cfg["team"],
        may_act=True,
        max_tool_calls=max_calls,
        max_seconds=max_seconds,
        dispatchable=True,
        signature=f"{name} standing by.",
        role=cat_cfg["base_role"],
        risk_tier=cat_cfg["risk_tier"],
        tools=tool_subset,
        internet_domains=internet_map[category],
        learned_skills=(),
        jobs=job_map[category],
    )


def generate_stark_agents(count_per_category: int = 50) -> tuple[StarkAI, ...]:
    """Generate StarkAI agents across all categories.

    Args:
        count_per_category: Number of agents per category (default 50,
            yielding 500 total across 10 categories).

    Returns:
        Tuple of all generated StarkAI agents.
    """
    agents: list[StarkAI] = []
    for category_name, cat_cfg in _CATEGORIES.items():
        for i in range(count_per_category):
            agents.append(_make_agent(category_name, i, cat_cfg))
    return tuple(agents)


# Generate the 500-agent roster at import time
STARK_ROSTER_500: tuple[StarkAI, ...] = generate_stark_agents(50)

# Index by ai_id for O(1) lookup
stark_roster_500_by_id: dict[str, StarkAI] = {
    ai.ai_id: ai for ai in STARK_ROSTER_500
}


def count_by_category() -> dict[str, int]:
    """Return agent count per category."""
    counts: dict[str, int] = {}
    for ai in STARK_ROSTER_500:
        cat = ai.ai_id.split("-")[1] if len(ai.ai_id.split("-")) > 1 else "unknown"
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def list_categories() -> list[str]:
    """List all agent categories."""
    return list(_CATEGORIES.keys())