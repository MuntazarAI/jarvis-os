"""Dot Spaces — workspaces for Dot documents and collaboration (OpenDots-inspired).

A Space is a home for working documents. Dots appear in navigation and can
be granted access to multiple Spaces in their settings. Each Dot has a
default destination for saved pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..core.types import now


@dataclass
class Space:
    """A workspace home for Dot documents.

    Spaces organize documents and pages. Dots can be members of multiple
    Spaces and each Dot has a default Space for saving pages.
    """

    space_id: str = field(default_factory=lambda: f"space-{uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    owner_dot_id: str = ""  # Dot that created/owns this Space
    member_dot_ids: list[str] = field(default_factory=list)  # Dots with access
    default_dot_id: str = ""  # Default Dot for new pages in this Space
    pages: list[str] = field(default_factory=list)  # Page entry IDs
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "space_id": self.space_id, "name": self.name,
            "description": self.description,
            "owner_dot_id": self.owner_dot_id,
            "member_dot_ids": list(self.member_dot_ids),
            "default_dot_id": self.default_dot_id,
            "pages": list(self.pages),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Space":
        return cls(
            space_id=data.get("space_id", f"space-{uuid4().hex[:12]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            owner_dot_id=data.get("owner_dot_id", ""),
            member_dot_ids=list(data.get("member_dot_ids", [])),
            default_dot_id=data.get("default_dot_id", ""),
            pages=list(data.get("pages", [])),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SpacePage:
    """A page/document within a Space.

    Pages have a searchable library, grid/list views, and nested
    subpages. Each page has a title, content, and provenance.
    """

    page_id: str = field(default_factory=lambda: f"page-{uuid4().hex[:12]}")
    space_id: str = ""
    title: str = ""
    content: str = ""
    content_type: str = "markdown"  # markdown, text, html, json
    author_dot_id: str = ""  # Dot that created the page
    parent_page_id: str = ""  # For nested subpages
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id, "space_id": self.space_id,
            "title": self.title, "content": self.content,
            "content_type": self.content_type,
            "author_dot_id": self.author_dot_id,
            "parent_page_id": self.parent_page_id,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpacePage":
        return cls(
            page_id=data.get("page_id", f"page-{uuid4().hex[:12]}"),
            space_id=data.get("space_id", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            content_type=data.get("content_type", "markdown"),
            author_dot_id=data.get("author_dot_id", ""),
            parent_page_id=data.get("parent_page_id", ""),
            tags=list(data.get("tags", [])),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            metadata=dict(data.get("metadata", {})),
        )