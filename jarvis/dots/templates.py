"""Dot templates — preconfigured dot types for common roles (OpenDots-inspired).

Each template defines a dot with a name, role, instructions, permitted tools,
permissions, and default configuration. Users can instantiate these templates
to quickly create specialized dots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..core.types import now


@dataclass
class DotTemplate:
    """A template for creating dots with preconfigured roles and tools."""

    template_id: str = field(default_factory=lambda: f"template-{uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    role: str = "general"
    instructions: str = ""
    goal_template: str = ""  # Template for the dot's goal, can include {user_input}
    permitted_tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    ask_before_act: bool = False
    require_approval_for: list[str] = field(default_factory=list)
    max_tool_calls: int = 8
    max_seconds: float = 60.0
    computer_config: dict[str, Any] = field(default_factory=dict)
    space_id: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id, "name": self.name,
            "description": self.description, "role": self.role,
            "instructions": self.instructions,
            "goal_template": self.goal_template,
            "permitted_tools": list(self.permitted_tools),
            "permissions": list(self.permissions),
            "skills": list(self.skills),
            "ask_before_act": self.ask_before_act,
            "require_approval_for": list(self.require_approval_for),
            "max_tool_calls": self.max_tool_calls,
            "max_seconds": self.max_seconds,
            "computer_config": dict(self.computer_config),
            "space_id": self.space_id,
            "tags": list(self.tags),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DotTemplate":
        return cls(
            template_id=data.get("template_id", f"template-{uuid4().hex[:12]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            role=data.get("role", "general"),
            instructions=data.get("instructions", ""),
            goal_template=data.get("goal_template", ""),
            permitted_tools=list(data.get("permitted_tools", [])),
            permissions=list(data.get("permissions", [])),
            skills=list(data.get("skills", [])),
            ask_before_act=bool(data.get("ask_before_act", False)),
            require_approval_for=list(data.get("require_approval_for", [])),
            max_tool_calls=int(data.get("max_tool_calls", 8)),
            max_seconds=float(data.get("max_seconds", 60.0)),
            computer_config=dict(data.get("computer_config", {})),
            space_id=data.get("space_id", ""),
            tags=list(data.get("tags", [])),
            created_at=data.get("created_at", now()),
        )


# -- Built-in dot templates (OpenDots-inspired specialist roles) ------------

def researcher_template() -> DotTemplate:
    """Researcher dot — investigates topics, finds sources, summarizes findings."""
    return DotTemplate(
        name="Researcher",
        role="researcher",
        instructions=(
            "You are a research specialist. Your job is to investigate topics "
            "thoroughly, find credible sources, extract key facts, and "
            "summarize findings with citations. Always verify claims against "
            "multiple sources before reporting."
        ),
        goal_template="Research the topic: {user_input} and provide a comprehensive summary with sources",
        permitted_tools=["web_search", "filesystem_read", "memory_palace_search"],
        permissions=["internet:example.com", "net.fetch"],
        ask_before_act=False,
        require_approval_for=["web_search"],
        max_tool_calls=8,
        max_seconds=60.0,
        computer_config={
            "os": "linux",
            "max_memory_mb": 2048,
            "max_cpu_cores": 2.0,
            "network_enabled": True,
            "allowed_domains": ["en.wikipedia.org", "arxiv.org", "github.com"],
        },
        tags=["research", "intelligence", "web"],
    )


def coder_template() -> DotTemplate:
    """Coder dot — writes, reviews, and debugs code."""
    return DotTemplate(
        name="Coder",
        role="coder",
        instructions=(
            "You are a coding specialist. Write clean, well-documented code. "
            "Review code for bugs and security issues. Debug failures and "
            "suggest fixes. Always explain your changes."
        ),
        goal_template="Code task: {user_input}",
        permitted_tools=["filesystem_read", "filesystem_write", "terminal_run", "git_status"],
        permissions=["fs.read", "fs.write", "exec", "vcs.read"],
        ask_before_act=True,
        require_approval_for=["filesystem_write", "terminal_run"],
        max_tool_calls=10,
        max_seconds=120.0,
        computer_config={
            "os": "linux",
            "max_memory_mb": 4096,
            "max_cpu_cores": 4.0,
            "network_enabled": False,
        },
        tags=["coding", "development", "engineering"],
    )


def writer_template() -> DotTemplate:
    """Writer dot — writes articles, reports, documentation, and stories."""
    return DotTemplate(
        name="Writer",
        role="writer",
        instructions=(
            "You are a writing specialist. Write clear, engaging content. "
            "Adapt your tone to the audience. Structure documents logically. "
            "Edit and refine drafts based on feedback."
        ),
        goal_template="Write about: {user_input}",
        permitted_tools=["filesystem_read", "filesystem_write"],
        permissions=["fs.read", "fs.write"],
        ask_before_act=False,
        require_approval_for=[],
        max_tool_calls=6,
        max_seconds=45.0,
        computer_config={
            "os": "linux",
            "max_memory_mb": 1024,
            "max_cpu_cores": 1.0,
            "network_enabled": False,
        },
        tags=["writing", "documentation", "content"],
    )


def analyst_template() -> DotTemplate:
    """Analyst dot — analyzes data, finds patterns, creates reports."""
    return DotTemplate(
        name="Analyst",
        role="analyst",
        instructions=(
            "You are a data analysis specialist. Find patterns in data. "
            "Create statistical summaries. Identify trends and anomalies. "
            "Present findings with clear visualizations and recommendations."
        ),
        goal_template="Analyze: {user_input}",
        permitted_tools=["filesystem_read", "terminal_run", "python_run"],
        permissions=["fs.read", "exec", "python_run"],
        ask_before_act=True,
        require_approval_for=["terminal_run"],
        max_tool_calls=6,
        max_seconds=60.0,
        computer_config={
            "os": "linux",
            "max_memory_mb": 2048,
            "max_cpu_cores": 2.0,
            "network_enabled": False,
        },
        tags=["analysis", "data", "statistics"],
    )


def critic_template() -> DotTemplate:
    """Critic dot — reviews plans, finds flaws, suggests improvements."""
    return DotTemplate(
        name="Critic",
        role="critic",
        instructions=(
            "You are a critical thinking specialist. Review plans and "
            "proposals for flaws, contradictions, and risks. Suggest "
            "improvements. Be constructive but thorough."
        ),
        goal_template="Critique: {user_input}",
        permitted_tools=["filesystem_read", "memory_palace_search"],
        permissions=["fs.read"],
        ask_before_act=False,
        require_approval_for=[],
        max_tool_calls=4,
        max_seconds=30.0,
        computer_config={
            "os": "linux",
            "max_memory_mb": 1024,
            "max_cpu_cores": 1.0,
            "network_enabled": False,
        },
        tags=["criticism", "review", "quality"],
    )


def coordinator_template() -> DotTemplate:
    """Coordinator dot — coordinates other dots, delegates tasks, tracks progress."""
    return DotTemplate(
        name="Coordinator",
        role="coordinator",
        instructions=(
            "You are a coordination specialist. Break down complex goals "
            "into subtasks. Assign work to other dots. Track progress. "
            "Report status to the user."
        ),
        goal_template="Coordinate: {user_input}",
        permitted_tools=[],
        permissions=[],
        ask_before_act=False,
        require_approval_for=[],
        max_tool_calls=4,
        max_seconds=30.0,
        computer_config={},
        tags=["coordination", "management", "planning"],
    )


# -- Template registry ------------------------------------------------------

_DOT_TEMPLATES: dict[str, DotTemplate] = {}


def register_template(template: DotTemplate) -> None:
    """Register a dot template."""
    _DOT_TEMPLATES[template.template_id] = template


def get_template(template_id: str) -> DotTemplate | None:
    """Get a template by ID."""
    return _DOT_TEMPLATES.get(template_id)


def list_templates() -> list[DotTemplate]:
    """List all registered templates."""
    return list(_DOT_TEMPLATES.values())


def find_templates_by_tag(tag: str) -> list[DotTemplate]:
    """Find templates by tag."""
    return [t for t in _DOT_TEMPLATES.values() if tag in t.tags]


# -- Register built-in templates -------------------------------------------

for _tmpl in [
    researcher_template(),
    coder_template(),
    writer_template(),
    analyst_template(),
    critic_template(),
    coordinator_template(),
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
