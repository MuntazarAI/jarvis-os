"""JARVIS Experience Layer — read-only dashboard consuming real JARVIS state.

This package is a *consumer* of existing JARVIS subsystems, never the owner
of intelligence. It does NOT create:

- a second planner
- a second agent system
- a second task engine
- a second memory system
- a second world model
- a second policy/approval system
- a second event bus
- a second scheduler

All UI state flows through existing subsystems via their public APIs.
"""

from .view import ExperienceView, ExperienceManager

__all__ = ["ExperienceView", "ExperienceManager"]
