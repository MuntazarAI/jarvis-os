"""
Expanded DOT Templates — 200 DotTemplate instances.

Generates 200 Dot templates across 10 operational categories (20 each),
following the same pattern as the built-in templates in dots_types.py.
All DOTs are bounded by PolicyEngine, may_act flags, tool budgets, and
explicit permissions. No DOT can bypass security gates.

Categories:
  research     (20) - investigation, sources, literature review
  coding       (20) - code writing, review, debugging
  writing      (20) - articles, reports, documentation
  analysis     (20) - data analysis, pattern finding, reports
  criticism    (20) - plan review, flaw detection, QA
  coordination (20) - task delegation, progress tracking
  security     (20) - security scanning, audit, hardening
  network      (20) - network monitoring, connectivity
  simulation   (20) - what-if analysis, contingency planning
  legacy       (20) - legacy code analysis, documentation
"""

from __future__ import annotations

import time
from typing import Any

from .dots_types import DotTemplate, register_template

__all__ = [
    "DOT_TEMPLATES_200",
    "dot_templates_200_by_id",
    "generate_dot_templates",
    "count_by_category",
    "list_categories",
]

# ---------------------------------------------------------------------------
# Category definitions for DOT templates
# ---------------------------------------------------------------------------

_CATEGORY_CONFIGS: dict[str, dict[str, Any]] = {
    "research": {
        "role": "researcher",
        "team": "intelligence",
        "risk_tier": "analytical",
        "base_tools": ["web_search", "filesystem_read", "memory_palace_search"],
        "base_permissions": ["internet:allowlist", "fs.read"],
        "base_skills": [],
        "base_internet_domains": ["github.com", "arxiv.org", "en.wikipedia.org"],
        "base_tags": ["research", "intelligence", "web"],
        "base_duties": ("investigate topics thoroughly", "find and cite sources",
                        "summarize with confidence levels", "flag unverified claims"),
        "base_goal": "Research topics thoroughly and cite sources",
        "max_tool_calls": 8,
        "max_seconds": 60.0,
    },
    "coding": {
        "role": "coder",
        "team": "engineering",
        "risk_tier": "medium",
        "base_tools": ["filesystem_read", "filesystem_write", "terminal_run", "git_status"],
        "base_permissions": ["fs.read", "fs.write", "exec", "vcs.read"],
        "base_skills": [],
        "base_internet_domains": ["github.com", "pypi.org", "docker.io"],
        "base_tags": ["coding", "development", "engineering"],
        "base_duties": ("write clean documented code", "review and debug code",
                        "follow security best practices", "test before commit"),
        "base_goal": "Write clean, documented, secure code",
        "max_tool_calls": 8,
        "max_seconds": 120.0,
    },
    "writing": {
        "role": "writer",
        "team": "content",
        "risk_tier": "low",
        "base_tools": ["filesystem_read", "filesystem_write"],
        "base_permissions": ["fs.read", "fs.write"],
        "base_skills": [],
        "base_internet_domains": [],
        "base_tags": ["writing", "documentation", "content"],
        "base_duties": ("write articles reports documentation", "maintain consistent style",
                        "cite sources when used", "proofread before delivery"),
        "base_goal": "Write articles, reports, documentation, and stories",
        "max_tool_calls": 6,
        "max_seconds": 45.0,
    },
    "analysis": {
        "role": "analyst",
        "team": "data",
        "risk_tier": "medium",
        "base_tools": ["filesystem_read", "filesystem_write", "terminal_run", "python_run"],
        "base_permissions": ["fs.read", "fs.write", "exec", "python_run"],
        "base_skills": [],
        "base_internet_domains": [],
        "base_tags": ["analysis", "data", "statistics"],
        "base_duties": ("analyze data patterns", "create reports",
                        "identify outliers and trends", "validate assumptions"),
        "base_goal": "Analyze data patterns and create reports",
        "max_tool_calls": 6,
        "max_seconds": 60.0,
    },
    "criticism": {
        "role": "critic",
        "team": "quality",
        "risk_tier": "low",
        "base_tools": ["filesystem_read", "memory_palace_search"],
        "base_permissions": ["fs.read"],
        "base_skills": [],
        "base_internet_domains": [],
        "base_tags": ["criticism", "review", "quality"],
        "base_duties": ("review plans for flaws", "suggest improvements",
                        "identify contradictions", "name missing evidence"),
        "base_goal": "Review plans and proposals for flaws and contradictions",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
    },
    "coordination": {
        "role": "coordinator",
        "team": "management",
        "risk_tier": "low",
        "base_tools": [],
        "base_permissions": [],
        "base_skills": [],
        "base_internet_domains": [],
        "base_tags": ["coordination", "management", "planning"],
        "base_duties": ("coordinate other dots", "delegate tasks",
                        "track progress", "escalate blockers"),
        "base_goal": "Coordinate other dots and delegate tasks",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
    },
    "security": {
        "role": "security_analyst",
        "team": "security",
        "risk_tier": "adversarial",
        "base_tools": ["code_security_scan", "filesystem_read", "net_inventory"],
        "base_permissions": ["fs.read", "security.scan"],
        "base_skills": [],
        "base_internet_domains": ["cve.mitre.org", "nvd.nist.gov"],
        "base_tags": ["security", "audit", "vulnerability"],
        "base_duties": ("scan for vulnerabilities", "audit configurations",
                        "report security findings", "recommend hardening"),
        "base_goal": "Perform security scanning and audit",
        "max_tool_calls": 8,
        "max_seconds": 120.0,
    },
    "network": {
        "role": "network_monitor",
        "team": "perception",
        "risk_tier": "observation",
        "base_tools": ["net_inventory", "system_probe", "filesystem_read"],
        "base_permissions": ["fs.read", "network.observe"],
        "base_skills": [],
        "base_internet_domains": ["github.com"],
        "base_tags": ["network", "monitoring", "connectivity"],
        "base_duties": ("monitor network health", "track device fabric",
                        "report outages", "never open ports without approval"),
        "base_goal": "Monitor network health and connectivity",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
    },
    "simulation": {
        "role": "simulation_engineer",
        "team": "cognition",
        "risk_tier": "simulation",
        "base_tools": ["filesystem_read", "memory_palace_search", "simulation_run"],
        "base_permissions": ["fs.read", "simulation.run"],
        "base_skills": [],
        "base_internet_domains": [],
        "base_tags": ["simulation", "contingency", "what-if"],
        "base_duties": ("stress-test plans", "name failure modes",
                        "keep answers hypothetical", "recommend dry runs"),
        "base_goal": "Stress-test plans via simulation",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
    },
    "legacy": {
        "role": "legacy_analyst",
        "team": "cognition",
        "risk_tier": "analytical",
        "base_tools": ["filesystem_read", "git_status", "documentation_trace"],
        "base_permissions": ["fs.read", "vcs.read"],
        "base_skills": [],
        "base_internet_domains": ["github.com"],
        "base_tags": ["legacy", "documentation", "analysis"],
        "base_duties": ("analyze legacy code", "trace deprecated paths",
                        "recommend safe modernization", "never delete without understanding"),
        "base_goal": "Analyze legacy systems and documentation",
        "max_tool_calls": 4,
        "max_seconds": 45.0,
    },
}

_DOT_JOB_MAP = {
    "research": [
        "investigator", "source_citer", "literature_reviewer",
        "topic_analyst", "unverified_claim_flagger", "web_researcher",
    ],
    "coding": [
        "code_writer", "code_reviewer", "debugger", "test_writer",
        "documentation_writer", "security_code_reviewer",
    ],
    "writing": [
        "article_writer", "report_author", "documentation_creator",
        "story_writer", "proofreader", "style_editor",
    ],
    "analysis": [
        "data_analyst", "pattern_finder", "report_creator",
        "outlier_detector", "trend_analyst", "assumption_validator",
    ],
    "criticism": [
        "plan_reviewer", "flaw_detector", "qa_analyst",
        "contradiction_finder", "missing_evidence_identifier", "quality_assessor",
    ],
    "coordination": [
        "task_delegator", "progress_tracker", "blocker_escalator",
        "team_coordinator", "workflow_manager", "dot_scheduler",
    ],
    "security": [
        "vulnerability_scanner", "security_auditor", "hardening_recommender",
        "compliance_checker", "threat_detector", "security_reporter",
    ],
    "network": [
        "network_monitor", "connectivity_tracker", "outage_reporter",
        "latency_analyst", "device_fabric_observer", "port_watcher",
    ],
    "simulation": [
        "plan_stress_tester", "what_if_analyst", "contingency_planner",
        "failure_mode_analyst", "dry_run_coordinator", "simulation_runner",
    ],
    "legacy": [
        "legacy_code_analyst", "documentation_tracer", "modernization_planner",
        "deprecated_system_reviewer", "code_archaeologist", "migration_advisor",
    ],
}

_SUFFIXES = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
    "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
    "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
    "xray", "yankee", "zulu",
]


def _make_dot_template(
    category: str,
    index: int,
    cat_cfg: dict[str, Any],
) -> DotTemplate:
    """Create a single DotTemplate for the given category and index."""
    suffix = _SUFFIXES[index % len(_SUFFIXES)]
    tier_index = index // len(_SUFFIXES)
    template_id = f"dot-{category}-{suffix}-{tier_index:02d}"
    name = f"{category.title()} Dot {suffix.title()} {tier_index:02d}"

    # Select a subset of tools
    tools = cat_cfg["base_tools"]
    tool_subset = tools[: min(len(tools), 2 + (index % 4))]

    # Vary max tool calls
    max_calls = cat_cfg["max_tool_calls"] + (index % 4)
    max_seconds = cat_cfg["max_seconds"] + (index * 5.0)

    # Build trigger subscriptions
    triggers = [
        f"{category}_request",
        f"{category}_requested",
        f"{category}_task",
    ]

    return DotTemplate(
        template_id=template_id,
        name=name,
        description=f"{cat_cfg['base_goal']} — {category} specialist variant {suffix}",
        role=cat_cfg["role"],
        goal=cat_cfg["base_goal"],
        tools=tool_subset,
        permissions=list(cat_cfg["base_permissions"]),
        skills=list(cat_cfg["base_skills"]),
        trigger_subscriptions=triggers,
        may_act=True,
        max_tool_calls=max_calls,
        max_seconds=max_seconds,
        dispatchable=True,
        team=cat_cfg["team"],
        risk_tier=cat_cfg["risk_tier"],
        computer_config={
            "os": "linux",
            "max_memory_mb": 2048 + (index * 256),
            "max_cpu_cores": float(1 + (index % 4)),
            "network_enabled": category in ("research", "coding", "security", "network"),
        },
        internet_domains=list(cat_cfg["base_internet_domains"]),
        tags=list(cat_cfg["base_tags"]) + [category, suffix],
        jobs=list(_DOT_JOB_MAP[category]),
        created_at=time.time(),
    )


def generate_dot_templates(count_per_category: int = 20) -> list[DotTemplate]:
    """Generate DotTemplate instances across all categories.

    Args:
        count_per_category: Number of templates per category (default 20,
            yielding 200 total across 10 categories).

    Returns:
        List of all generated DotTemplate instances.
    """
    templates: list[DotTemplate] = []
    for category_name, cat_cfg in _CATEGORY_CONFIGS.items():
        for i in range(count_per_category):
            templates.append(_make_dot_template(category_name, i, cat_cfg))
    return templates


# Generate the 200-template roster at import time
DOT_TEMPLATES_200: list[DotTemplate] = generate_dot_templates(20)

# Register all templates with the dots_types registry
for _tmpl in DOT_TEMPLATES_200:
    register_template(_tmpl)

# Index by template_id for O(1) lookup
dot_templates_200_by_id: dict[str, DotTemplate] = {
    t.template_id: t for t in DOT_TEMPLATES_200
}


def count_by_category() -> dict[str, int]:
    """Return template count per category."""
    counts: dict[str, int] = {}
    for t in DOT_TEMPLATES_200:
        cat = t.template_id.split("-")[1] if len(t.template_id.split("-")) > 1 else "unknown"
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def list_categories() -> list[str]:
    """List all template categories."""
    return list(_CATEGORY_CONFIGS.keys())