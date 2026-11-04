"""DOTS 3.1 — persistent autonomous workers.

OpenDots-inspired: specialist Dots with name, role, instructions,
permitted tools, and optional assigned computers. Spaces provide
workspaces for Dot documents. Ask → Browse → Approve → Save workflow
provides human-in-the-loop gating.

Colibri-inspired: efficient model resource tiering for Dot computers.

Dot templates provide quick creation of specialist dots (researcher,
coder, writer, analyst, critic, coordinator). Dot teams enable
multi-bot coordination for complex goals.
"""

from .computer import DotComputer
from .manager import DotDependencies, DotManager
from .model import (
    DOT_SCHEMA_VERSION,
    Checkpoint,
    Dot,
    DotStatus,
    InvalidTransition,
    validate_transition,
)
from .space import Space, SpacePage
from .team import DotTeam, DotTeamManager, DotTeamMember
from .templates import (
    DotTemplate,
    analyst_template,
    coordinator_template,
    critic_template,
    coder_template,
    researcher_template,
    writer_template,
    find_templates_by_tag,
    get_template,
    list_templates,
    register_template,
)

__all__ = [
    # Manager
    "DotDependencies",
    "DotManager",
    # Model
    "DOT_SCHEMA_VERSION",
    "Checkpoint",
    "Dot",
    "DotStatus",
    "InvalidTransition",
    "validate_transition",
    # Computer (OpenDots: each Dot can have its own computer)
    "DotComputer",
    # Space (OpenDots: workspaces for Dot documents)
    "Space",
    "SpacePage",
    # Team (multi-bot coordination)
    "DotTeamMember",
    "DotTeam",
    "DotTeamManager",
    # Templates (quick dot creation)
    "DotTemplate",
    "analyst_template",
    "coordinator_template",
    "critic_template",
    "coder_template",
    "researcher_template",
    "writer_template",
    "find_templates_by_tag",
    "get_template",
    "list_templates",
    "register_template",
]
