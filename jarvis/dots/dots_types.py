"""DOT Templates - M13+ Advanced DOT Types.

Additional DOT types for specialized tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DotTemplate:
    """Template for creating DOTs with predefined configurations."""

    template_id: str
    name: str
    description: str
    role: str
    goal: str
    tools: list[str]
    permissions: list[str]
    skills: list[str]
    trigger_subscriptions: list[str]
    may_act: bool
    max_tool_calls: int
    max_seconds: float
    dispatchable: bool
    team: str
    risk_tier: str
    computer_config: dict[str, Any]
    internet_domains: list[str]
    tags: list[str]
    created_at: float = field(default_factory=time.time)


# -- Built-in Dot Templates --

_DOT_TEMPLATES: dict[str, DotTemplate] = {}


def register_template(template: DotTemplate) -> None:
    """Register a Dot template."""
    _DOT_TEMPLATES[template.template_id] = template


def get_template(template_id: str) -> DotTemplate | None:
    """Get a template by ID."""
    return _DOT_TEMPLATES.get(template_id)


def list_templates() -> list[DotTemplate]:
    """List all templates."""
    return list(_DOT_TEMPLATES.values())


def find_templates_by_tag(tag: str) -> list[DotTemplate]:
    """Find templates by tag."""
    return [t for t in _DOT_TEMPLATES.values() if tag in t.tags]


# -- Built-in Templates --


def _researcher_template() -> DotTemplate:
    return DotTemplate(
        template_id="researcher",
        name="Researcher Dot",
        description="Research specialist that investigates topics and finds sources",
        role="researcher",
        goal="Research topics thoroughly and cite sources",
        tools=["web_search", "filesystem_read", "memory_palace_search"],
        permissions=["internet:example.com", "net.fetch"],
        skills=[],
        trigger_subscriptions=["research_request", "research_requested"],
        may_act=True,
        max_tool_calls=8,
        max_seconds=60.0,
        dispatchable=True,
        team="intelligence",
        risk_tier="analytical",
        computer_config={},
        internet_domains=["github.com", "arxiv.org", "en.wikipedia.org"],
        tags=["research", "intelligence", "web"],
    )


def _coder_template() -> DotTemplate:
    return DotTemplate(
        template_id="coder",
        name="Coder Dot",
        description="Writes, reviews, and debugs code",
        role="coder",
        goal="Write clean, documented code",
        tools=["filesystem_read", "filesystem_write", "terminal_run", "git_status"],
        permissions=["fs.read", "fs.write", "exec", "vcs.read"],
        skills=[],
        trigger_subscriptions=["code_request", "code_review_request"],
        may_act=True,
        max_tool_calls=8,
        max_seconds=120.0,
        dispatchable=True,
        computer_config={
            "os": "linux",
            "max_memory_mb": 4096,
            "max_cpu_cores": 4.0,
            "network_enabled": False,
        },
        internet_domains=("github.com", "pypi.org", "docker.io"),
        tags=["coding", "development", "engineering"],
    )


def _writer_template() -> DotTemplate:
    return DotTemplate(
        template_id="writer",
        name="Writer Dot",
        description="Writes articles, reports, documentation, and stories",
        role="writer",
        goal="Write articles, reports, documentation, and stories",
        tools=["filesystem_read", "filesystem_write"],
        permissions=["fs.read", "fs.write"],
        skills=[],
        trigger_subscriptions=["write_request", "document_request"],
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        computer_config={
            "os": "linux",
            "max_memory_mb": 2048,
            "max_cpu_cores": 2.0,
            "network_enabled": False,
        },
        internet_domains=(),
        tags=["writing", "documentation", "content"],
    )


def _analyst_template() -> DotTemplate:
    return DotTemplate(
        template_id="analyst",
        name="Analyst Dot",
        description="Analyzes data, finds patterns, creates reports",
        role="analyst",
        goal="Analyze data patterns and create reports",
        tools=["filesystem_read", "filesystem_write", "terminal_run", "python_run"],
        permissions=["fs.read", "fs.write", "exec", "python_run"],
        skills=[],
        trigger_subscriptions=["analyze_request", "data_analysis_request"],
        may_act=True,
        max_tool_calls=6,
        max_seconds=60.0,
        dispatchable=True,
        computer_config={
            "os": "linux",
            "max_memory_mb": 2048,
            "max_cpu_cores": 2.0,
            "network_enabled": False,
        },
        internet_domains=(),
        tags=["analysis", "data", "statistics"],
    )


def _critic_template() -> DotTemplate:
    return DotTemplate(
        template_id="critic",
        name="Critic Dot",
        description="Reviews plans, finds flaws, suggests improvements",
        role="critic",
        goal="Review plans and proposals for flaws and contradictions",
        tools=["filesystem_read", "memory_palace_search"],
        permissions=["fs.read"],
        skills=[],
        trigger_subscriptions=["review_request", "critique_request"],
        may_act=True,
        max_tool_calls=4,
        max_seconds=30.0,
        dispatchable=True,
        computer_config={
            "os": "linux",
            "max_memory_mb": 1024,
            "max_cpu_cores": 1.0,
            "network_enabled": False,
        },
        internet_domains=(),
        tags=["criticism", "review", "quality"],
    )


def _coordinator_template() -> DotTemplate:
    return DotTemplate(
        template_id="coordinator",
        name="Coordinator Dot",
        description="Coordinates other dots, delegates tasks, tracks progress",
        role="coordinator",
        goal="Coordinate other dots and delegate tasks",
        tools=[],
        permissions=[],
        skills=[],
        trigger_subscriptions=["coordinate_request", "task_coordination_request"],
        may_act=True,
        max_tool_calls=4,
        max_seconds=30.0,
        dispatchable=True,
        computer_config={},
        internet_domains=(),
        tags=["coordination", "management", "planning"],
    )


# -- Register built-in templates --

for _tmpl in [
    _researcher_template(),
    _coder_template(),
    _writer_template(),
    _analyst_template(),
    _critic_template(),
    _coordinator_template(),
]:
    register_template(_tmpl)


__all__ = [
    "DotTemplate",
    "register_template",
    "get_template",
    "list_templates",
    "find_templates_by_tag",
    "researcher_template",
    "coder_template",
    "writer_template",
    "analyst_template",
    "critic_template",
    "coordinator_template",
]
