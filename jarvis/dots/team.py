"""DotTeam — multi-bot coordination for many bots working together.

OpenDots-inspired: dots can form teams to work on complex goals together.
Each team has a coordinator, members with assigned roles, and shared
workspaces. Teams can have their own goals, budgets, and approval workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..core.types import now


@dataclass
class DotTeamMember:
    """A dot's membership in a team."""

    dot_id: str
    dot_name: str
    role: str = "member"  # member, lead, coordinator, observer
    joined_at: float = field(default_factory=now)
    responsibilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dot_id": self.dot_id, "dot_name": self.dot_name,
            "role": self.role, "joined_at": self.joined_at,
            "responsibilities": list(self.responsibilities),
        }


@dataclass
class DotTeam:
    """A team of dots working together on shared goals.

    Teams enable multi-bot coordination where multiple dots collaborate
    on complex goals that no single dot could handle alone.
    """

    team_id: str = field(default_factory=lambda: f"team-{uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    goal: str = ""
    coordinator_dot_id: str = ""  # Dot that leads the team
    members: dict[str, DotTeamMember] = field(default_factory=dict)
    shared_space_id: str = ""  # Space the team works in
    status: str = "forming"  # forming, active, completed, disbanded
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_member(self, dot_id: str, dot_name: str,
                   role: str = "member",
                   responsibilities: list[str] | None = None) -> None:
        """Add a dot to the team."""
        self.members[dot_id] = DotTeamMember(
            dot_id=dot_id, dot_name=dot_name, role=role,
            responsibilities=list(responsibilities or []),
        )
        self.updated_at = now()

    def remove_member(self, dot_id: str) -> bool:
        """Remove a dot from the team."""
        if dot_id in self.members:
            del self.members[dot_id]
            self.updated_at = now()
            return True
        return False

    def get_member(self, dot_id: str) -> DotTeamMember | None:
        """Get a team member by dot ID."""
        return self.members.get(dot_id)

    def is_member(self, dot_id: str) -> bool:
        """Check if a dot is a team member."""
        return dot_id in self.members

    def member_count(self) -> int:
        """Return the number of team members."""
        return len(self.members)

    def complete(self) -> None:
        """Mark the team as completed."""
        self.status = "completed"
        self.completed_at = now()
        self.updated_at = now()

    def disband(self) -> None:
        """Disband the team."""
        self.status = "disbanded"
        self.updated_at = now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id, "name": self.name,
            "description": self.description, "goal": self.goal,
            "coordinator_dot_id": self.coordinator_dot_id,
            "members": {did: m.to_dict() for did, m in self.members.items()},
            "shared_space_id": self.shared_space_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DotTeam":
        return cls(
            team_id=data.get("team_id", f"team-{uuid4().hex[:12]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            goal=data.get("goal", ""),
            coordinator_dot_id=data.get("coordinator_dot_id", ""),
            members={
                did: DotTeamMember(
                    dot_id=m.get("dot_id", ""),
                    dot_name=m.get("dot_name", ""),
                    role=m.get("role", "member"),
                    joined_at=m.get("joined_at", now()),
                    responsibilities=list(m.get("responsibilities", [])),
                )
                for did, m in data.get("members", {}).items()
            },
            shared_space_id=data.get("shared_space_id", ""),
            status=data.get("status", "forming"),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            completed_at=data.get("completed_at"),
            metadata=dict(data.get("metadata", {})),
        )


# -- DotTeamManager — manages multiple dot teams ---------------------------

class DotTeamManager:
    """Manages dot teams for multi-bot coordination."""

    def __init__(self) -> None:
        self._teams: dict[str, DotTeam] = {}

    def create_team(self, name: str, goal: str,
                    coordinator_dot_id: str = "",
                    description: str = "",
                    shared_space_id: str = "") -> DotTeam:
        """Create a new dot team."""
        team = DotTeam(
            name=name, description=description, goal=goal,
            coordinator_dot_id=coordinator_dot_id,
            shared_space_id=shared_space_id,
        )
        self._teams[team.team_id] = team
        return team

    def get_team(self, team_id: str) -> DotTeam | None:
        """Get a team by ID."""
        return self._teams.get(team_id)

    def list_teams(self) -> list[DotTeam]:
        """List all teams."""
        return list(self._teams.values())

    def add_member(self, team_id: str, dot_id: str, dot_name: str,
                   role: str = "member",
                   responsibilities: list[str] | None = None) -> bool:
        """Add a dot as a member of a team."""
        team = self.get_team(team_id)
        if team is None:
            return False
        team.add_member(dot_id, dot_name, role, responsibilities)
        return True

    def remove_member(self, team_id: str, dot_id: str) -> bool:
        """Remove a dot from a team."""
        team = self.get_team(team_id)
        if team is None:
            return False
        return team.remove_member(dot_id)

    def complete_team(self, team_id: str) -> bool:
        """Mark a team as completed."""
        team = self.get_team(team_id)
        if team is None:
            return False
        team.complete()
        return True

    def disband_team(self, team_id: str) -> bool:
        """Disband a team."""
        team = self.get_team(team_id)
        if team is None:
            return False
        team.disband()
        return True

    def teams_for_dot(self, dot_id: str) -> list[DotTeam]:
        """Return all teams a dot is a member of."""
        return [t for t in self._teams.values() if t.is_member(dot_id)]

    def active_teams(self) -> list[DotTeam]:
        """Return all active (forming or active) teams."""
        return [t for t in self._teams.values()
                if t.status in ("forming", "active")]

    def stats(self) -> dict[str, Any]:
        """Return team statistics."""
        total = len(self._teams)
        by_status: dict[str, int] = {}
        for t in self._teams.values():
            by_status[t.status] = by_status.get(t.status, 0) + 1
        total_members = sum(t.member_count() for t in self._teams.values())
        return {
            "total_teams": total,
            "by_status": by_status,
            "total_members": total_members,
        }


__all__ = [
    "DotTeamMember",
    "DotTeam",
    "DotTeamManager",
]
