"""
AI Bot Roster — 250 AI Bots.

Distinct from Stark AI Agents (executive, personality-driven, policy-gated)
and DOT Templates (task-oriented, template-based). AI Bots are lightweight,
single-purpose autonomous workers designed for high-volume concurrent
execution. Each bot has a specific domain, tool set, and execution budget.

All bots operate within PolicyEngine gates. No bot can bypass security
controls or exceed its declared tool budget.

Categories (25 each):
  monitoring    - system health, uptime, resource tracking
  scanning      - security scanning, port scanning, vulnerability discovery
  analysis      - data analysis, pattern recognition, reporting
  optimization  - performance tuning, resource optimization
  maintenance   - cleanup, backup, log rotation, system upkeep
  communication - messaging, notification, alert routing
  research      - information gathering, source verification
  testing       - test execution, validation, quality assurance
  deployment    - deployment automation, rollback, health checks
  integration   - API integration, webhook handling, data sync
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AIBot",
    "AI_BOTS_250",
    "ai_bots_250_by_id",
    "generate_ai_bots",
    "count_by_category",
    "list_categories",
]


@dataclass
class AIBot:
    """A lightweight, single-purpose autonomous worker."""

    bot_id: str
    name: str
    domain: str
    role: str
    description: str
    tools: tuple[str, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    max_tool_calls: int = 4
    max_seconds: float = 30.0
    may_act: bool = True
    dispatchable: bool = True
    risk_tier: str = "low"
    team: str = "core"
    internet_domains: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    jobs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "name": self.name,
            "domain": self.domain,
            "role": self.role,
            "description": self.description,
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "max_tool_calls": self.max_tool_calls,
            "max_seconds": self.max_seconds,
            "may_act": self.may_act,
            "dispatchable": self.dispatchable,
            "risk_tier": self.risk_tier,
            "team": self.team,
            "internet_domains": list(self.internet_domains),
            "tags": list(self.tags),
            "jobs": list(self.jobs),
        }


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

_CATEGORY_CONFIGS: dict[str, dict[str, Any]] = {
    "monitoring": {
        "team": "operations",
        "risk_tier": "low",
        "base_tools": ("system_probe", "filesystem_read", "net_inventory"),
        "base_permissions": ("fs.read", "system.observe", "network.observe"),
        "base_tags": ("monitoring", "observability", "health"),
        "base_role": "monitor",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
    },
    "scanning": {
        "team": "security",
        "risk_tier": "medium",
        "base_tools": ("net_inventory", "port_scan", "web_audit", "dir_enum"),
        "base_permissions": ("security.scan", "network.observe"),
        "base_tags": ("scanning", "security", "reconnaissance"),
        "base_role": "scanner",
        "max_tool_calls": 6,
        "max_seconds": 60.0,
    },
    "analysis": {
        "team": "intelligence",
        "risk_tier": "low",
        "base_tools": ("filesystem_read", "python_run", "memory_palace_search"),
        "base_permissions": ("fs.read", "exec.eval"),
        "base_tags": ("analysis", "data", "reporting"),
        "base_role": "analyst",
        "max_tool_calls": 5,
        "max_seconds": 45.0,
    },
    "optimization": {
        "team": "core",
        "risk_tier": "low",
        "base_tools": ("system_probe", "filesystem_read", "python_run"),
        "base_permissions": ("fs.read", "system.observe", "exec.eval"),
        "base_tags": ("optimization", "performance", "tuning"),
        "base_role": "optimizer",
        "max_tool_calls": 4,
        "max_seconds": 30.0,
    },
    "maintenance": {
        "team": "operations",
        "risk_tier": "low",
        "base_tools": ("filesystem_read", "filesystem_write", "terminal_run"),
        "base_permissions": ("fs.read", "fs.write", "exec"),
        "base_tags": ("maintenance", "cleanup", "upkeep"),
        "base_role": "maintainer",
        "max_tool_calls": 5,
        "max_seconds": 60.0,
    },
    "communication": {
        "team": "core",
        "risk_tier": "low",
        "base_tools": ("filesystem_read", "filesystem_write"),
        "base_permissions": ("fs.read", "fs.write"),
        "base_tags": ("communication", "notification", "messaging"),
        "base_role": "communicator",
        "max_tool_calls": 3,
        "max_seconds": 15.0,
    },
    "research": {
        "team": "intelligence",
        "risk_tier": "low",
        "base_tools": ("web_fetch", "filesystem_read", "memory_palace_search"),
        "base_permissions": ("fs.read", "net.fetch"),
        "base_tags": ("research", "information", "verification"),
        "base_role": "researcher",
        "max_tool_calls": 6,
        "max_seconds": 60.0,
    },
    "testing": {
        "team": "quality",
        "risk_tier": "low",
        "base_tools": ("terminal_run", "python_run", "filesystem_read"),
        "base_permissions": ("fs.read", "exec", "exec.eval"),
        "base_tags": ("testing", "validation", "qa"),
        "base_role": "tester",
        "max_tool_calls": 6,
        "max_seconds": 60.0,
    },
    "deployment": {
        "team": "operations",
        "risk_tier": "medium",
        "base_tools": ("terminal_run", "filesystem_read", "system_probe"),
        "base_permissions": ("fs.read", "exec", "system.deploy"),
        "base_tags": ("deployment", "devops", "rollout"),
        "base_role": "deployer",
        "max_tool_calls": 5,
        "max_seconds": 60.0,
    },
    "integration": {
        "team": "core",
        "risk_tier": "low",
        "base_tools": ("web_fetch", "filesystem_read", "filesystem_write"),
        "base_permissions": ("fs.read", "fs.write", "net.fetch"),
        "base_tags": ("integration", "api", "sync"),
        "base_role": "integrator",
        "max_tool_calls": 5,
        "max_seconds": 45.0,
    },
}

# Assigned jobs per category
_BOT_JOB_MAP = {
    "monitoring": [
        "system_health_monitor", "uptime_tracker", "resource_tracker",
        "alert_dispatcher", "dashboard_updater", "metric_collector",
    ],
    "scanning": [
        "vulnerability_scanner", "port_scanner", "web_auditor",
        "directory_enumerator", "intrusion_detector", "threat_reporter",
    ],
    "analysis": [
        "data_analyst", "pattern_recognizer", "report_generator",
        "outlier_detector", "trend_analyst", "evidence_evaluator",
    ],
    "optimization": [
        "performance_tuner", "resource_optimizer", "system_analyzer",
        "bottleneck_identifier", "efficiency_reporter", "config_optimizer",
    ],
    "maintenance": [
        "system_cleaner", "backup_operator", "log_rotator",
        "temp_file_cleaner", "update_checker", "health_maintainer",
    ],
    "communication": [
        "message_router", "notification_dispatcher", "alert_relay",
        "status_broadcaster", "communication_logger", "message_queue_manager",
    ],
    "research": [
        "information_gatherer", "source_verifier", "research_summarizer",
        "topic_investigator", "literature_collector", "data_compiler",
    ],
    "testing": [
        "test_executor", "quality_assurance_bot", "validation_runner",
        "test_case_runner", "bug_reporter", "test_result_analyst",
    ],
    "deployment": [
        "deployment_automator", "rollback_coordinator", "health_checker",
        "release_manager", "deployment_monitor", "environment_provisioner",
    ],
    "integration": [
        "api_integrator", "webhook_handler", "data_synchronizer",
        "service_connector", "endpoint_monitor", "integration_tester",
    ],
}

_SUFFIXES = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
    "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
    "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
    "xray", "yankee", "zulu",
]


def _make_bot(category: str, index: int, cat_cfg: dict[str, Any]) -> AIBot:
    """Create a single AIBot for the given category and index."""
    suffix = _SUFFIXES[index % len(_SUFFIXES)]
    tier_index = index // len(_SUFFIXES)
    bot_id = f"bot-{category}-{suffix}-{tier_index:02d}"
    name = f"{category.title()} Bot {suffix.title()} {tier_index:02d}"

    tools = cat_cfg["base_tools"]
    tool_subset = tools[: min(len(tools), 2 + (index % 4))]

    max_calls = cat_cfg["max_tool_calls"] + (index % 3)
    max_seconds = cat_cfg["max_seconds"] + (index * 2.0)

    internet_map = {
        "monitoring": (),
        "scanning": ("cve.mitre.org", "nvd.nist.gov"),
        "analysis": (),
        "optimization": (),
        "maintenance": (),
        "communication": (),
        "research": ("github.com", "arxiv.org"),
        "testing": (),
        "deployment": ("github.com", "pypi.org"),
        "integration": ("github.com", "api.github.com"),
    }

    return AIBot(
        bot_id=bot_id,
        name=name,
        domain=category,
        role=cat_cfg["base_role"],
        description=f"{category.title()} automation bot — {name} handles "
                    f"{cat_cfg['base_role']} tasks within PolicyEngine gates.",
        tools=tool_subset,
        permissions=cat_cfg["base_permissions"],
        max_tool_calls=max_calls,
        max_seconds=max_seconds,
        may_act=True,
        dispatchable=True,
        risk_tier=cat_cfg["risk_tier"],
        team=cat_cfg["team"],
        internet_domains=internet_map[category],
        tags=cat_cfg["base_tags"] + (category, suffix),
        jobs=tuple(_BOT_JOB_MAP[category]),
    )


def generate_ai_bots(count_per_category: int = 25) -> tuple[AIBot, ...]:
    """Generate AI Bot instances across all categories.

    Args:
        count_per_category: Number of bots per category (default 25,
            yielding 250 total across 10 categories).

    Returns:
        Tuple of all generated AIBot instances.
    """
    bots: list[AIBot] = []
    for category_name, cat_cfg in _CATEGORY_CONFIGS.items():
        for i in range(count_per_category):
            bots.append(_make_bot(category_name, i, cat_cfg))
    return tuple(bots)


# Generate the 250-bot roster at import time
AI_BOTS_250: tuple[AIBot, ...] = generate_ai_bots(25)

# Index by bot_id for O(1) lookup
ai_bots_250_by_id: dict[str, AIBot] = {bot.bot_id: bot for bot in AI_BOTS_250}


def count_by_category() -> dict[str, int]:
    """Return bot count per category."""
    counts: dict[str, int] = {}
    for bot in AI_BOTS_250:
        cat = bot.domain
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def list_categories() -> list[str]:
    """List all bot categories."""
    return list(_CATEGORY_CONFIGS.keys())