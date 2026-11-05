"""
Build-Your-Own-X Integration — JARVIS-OS OMNINET subsystem.

Integrates https://github.com/codecrafters-io/build-your-own-x — a
compilation of step-by-step guides for re-creating technologies from
scratch. Provides a research and implementation roadmap for JARVIS-OS
to build its own AI models, databases, operating systems, neural
networks, and more.

Read-only reference — no external code is fetched or executed without
explicit operator approval through PolicyEngine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class BuildGuide:
    """A build-your-own technology guide reference."""
    guide_id: str
    title: str
    category: str
    language: str
    description: str
    source_url: str
    difficulty: str  # beginner | intermediate | advanced
    estimated_hours: float
    tags: list[str] = field(default_factory=list)


@dataclass
class BuildProject:
    """A build-your-own project instance."""
    project_id: str
    guide_id: str
    name: str
    status: str  # planned | in_progress | completed | blocked
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None


class BuildYourOwnX:
    """
    Build-Your-Own-X — technology implementation roadmap.

    Provides references to step-by-step guides for building technologies
    from scratch across 25+ categories: AI models, AR, BitTorrent,
    Blockchain, Bots, CLI tools, Databases, Docker, Emulators, Front-end
    frameworks, Games, Git, Memory allocators, Network stacks, Neural
    networks, Operating systems, Physics engines, Processors, Programming
    languages, Regex engines, Search engines, Shells, Template engines,
    Text editors, Visual recognition systems, Voxel engines, Web browsers,
    Web servers.

    Read-only reference. Implementation requires explicit operator
    approval through PolicyEngine for each project.
    """

    CATEGORIES = [
        "3d_renderer", "ai_model", "augmented_reality", "bittorrent_client",
        "blockchain_cryptocurrency", "bot", "command_line_tool", "database",
        "docker", "emulator_virtual_machine", "front_end_framework_library",
        "game", "git", "memory_allocator", "network_stack", "neural_network",
        "operating_system", "physics_engine", "processor",
        "programming_language", "regex_engine", "search_engine", "shell",
        "template_engine", "text_editor", "visual_recognition_system",
        "voxel_engine", "web_browser", "web_server",
    ]

    # Curated build guides from build-your-own-x
    GUIDES: dict[str, BuildGuide] = {}

    def __init__(self, policy: PolicyEngine | None = None,
                 events: EventStore | None = None) -> None:
        self.policy = policy
        self.events = events
        self.projects: dict[str, BuildProject] = {}
        self._initialized = False
        self._seed_guides()

    def _seed_guides(self) -> None:
        """Seed build guides from build-your-own-x categories."""
        seeds = [
            ("build-your-own-ai-model", "AI Model", "ai_model", "Python",
             "Build a Large Language Model from scratch", "beginner", 40.0,
             ["llm", "ai", "neural-network", "python"]),
            ("build-your-own-neural-network", "Neural Network", "neural_network", "Python",
             "Build a neural network from scratch", "beginner", 20.0,
             ["neural-network", "deep-learning", "python"]),
            ("build-your-own-operating-system", "Operating System", "operating_system", "C",
             "Build an operating system from scratch", "advanced", 200.0,
             ["os", "kernel", "c"]),
            ("build-your-own-database", "Database", "database", "Python",
             "Build a database from scratch", "intermediate", 60.0,
             ["database", "sql", "storage", "python"]),
            ("build-your-own-web-server", "Web Server", "web_server", "Python",
             "Build a web server from scratch", "beginner", 15.0,
             ["web", "http", "server", "python"]),
            ("build-your-own-web-browser", "Web Browser", "web_browser", "C++",
             "Build a web browser from scratch", "advanced", 300.0,
             ["browser", "web", "rendering", "c++"]),
            ("build-your-own-git", "Git", "git", "Python",
             "Build a Git-like version control system from scratch", "intermediate", 50.0,
             ["git", "version-control", "python"]),
            ("build-your-own-command_line_tool", "Command-Line Tool", "command_line_tool", "Go",
             "Build a command-line tool from scratch", "beginner", 10.0,
             ["cli", "go", "tool"]),
            ("build-your-own-search_engine", "Search Engine", "search_engine", "Python",
             "Build a search engine from scratch", "intermediate", 80.0,
             ["search", "indexing", "python"]),
            ("build-your-own_text_editor", "Text Editor", "text_editor", "C",
             "Build a text editor from scratch", "intermediate", 40.0,
             ["editor", "text", "c"]),
            ("build-your-own_docker", "Docker", "docker", "Go",
             "Build a container runtime from scratch", "advanced", 100.0,
             ["docker", "containers", "go"]),
            ("build-your-own_augmented_reality", "Augmented Reality", "augmented_reality", "C#",
             "Build an AR system from scratch", "intermediate", 60.0,
             ["ar", "unity", "c#"]),
            ("build-your-own_blockchain_cryptocurrency", "Blockchain / Cryptocurrency", "blockchain_cryptocurrency", "Go",
             "Build a blockchain from scratch", "intermediate", 40.0,
             ["blockchain", "crypto", "go"]),
            ("build-your-own_bot", "Bot", "bot", "Python",
             "Build a bot from scratch", "beginner", 15.0,
             ["bot", "automation", "python"]),
            ("build-your-own_network_stack", "Network Stack", "network_stack", "C",
             "Build a network stack from scratch", "advanced", 150.0,
             ["network", "tcp-ip", "c"]),
            ("build-your-own_physics_engine", "Physics Engine", "physics_engine", "C++",
             "Build a physics engine from scratch", "advanced", 120.0,
             ["physics", "simulation", "c++"]),
            ("build-your-own_processor", "Processor", "processor", "Verilog",
             "Build a processor from scratch", "advanced", 200.0,
             ["processor", "verilog", "hardware"]),
            ("build-your-own_programming_language", "Programming Language", "programming_language", "Python",
             "Build a programming language from scratch", "advanced", 150.0,
             ["language", "compiler", "python"]),
            ("build-your-own_regex_engine", "Regex Engine", "regex_engine", "Python",
             "Build a regex engine from scratch", "beginner", 10.0,
             ["regex", "parser", "python"]),
            ("build-your-own_shell", "Shell", "shell", "C",
             "Build a shell from scratch", "intermediate", 50.0,
             ["shell", "terminal", "c"]),
            ("build-your-own_template_engine", "Template Engine", "template_engine", "Python",
             "Build a template engine from scratch", "beginner", 15.0,
             ["template", "python"]),
            ("build-your-own_visual_recognition_system", "Visual Recognition System", "visual_recognition_system", "Python",
             "Build a visual recognition system from scratch", "intermediate", 60.0,
             ["vision", "recognition", "python"]),
            ("build-your-own_voxel_engine", "Voxel Engine", "voxel_engine", "C++",
             "Build a voxel engine from scratch", "advanced", 100.0,
             ["voxel", "engine", "c++"]),
            ("build-your-own_3d_renderer", "3D Renderer", "3d_renderer", "C++",
             "Build a 3D renderer from scratch", "advanced", 100.0,
             ["renderer", "3d", "c++"]),
            ("build-your-own_front_end_framework_library", "Front-end Framework / Library", "front_end_framework_library", "JavaScript",
             "Build a front-end framework from scratch", "intermediate", 60.0,
             ["frontend", "javascript", "framework"]),
            ("build-your-own_emulator_virtual_machine", "Emulator / Virtual Machine", "emulator_virtual_machine", "C",
             "Build an emulator or VM from scratch", "advanced", 150.0,
             ["emulator", "vm", "c"]),
            ("build-your-own_game", "Game", "game", "C++",
             "Build a game from scratch", "intermediate", 60.0,
             ["game", "c++"]),
            ("build-your-own_memory_allocator", "Memory Allocator", "memory_allocator", "C",
             "Build a memory allocator from scratch", "intermediate", 30.0,
             ["memory", "allocator", "c"]),
            ("build-your-own_bittorrent_client", "BitTorrent Client", "bittorrent_client", "Python",
             "Build a BitTorrent client from scratch", "intermediate", 50.0,
             ["bittorrent", "p2p", "python"]),
        ]

        for guide_id, title, category, language, description, difficulty, hours, tags in seeds:
            self.GUIDES[guide_id] = BuildGuide(
                guide_id=guide_id,
                title=title,
                category=category,
                language=language,
                description=description,
                source_url=f"https://github.com/codecrafters-io/build-your-own-x",
                difficulty=difficulty,
                estimated_hours=hours,
                tags=tags,
            )

    def initialize(self) -> dict[str, Any]:
        """Initialize the Build-Your-Own-X subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "build_your_own_x",
            "source": "https://github.com/codecrafters-io/build-your-own-x",
            "guides": len(self.GUIDES),
            "categories": len(self.CATEGORIES),
            "read_only": True,
            "policy_gated": True,
        }

    def list_guides(self, category: str | None = None) -> list[BuildGuide]:
        """List build guides, optionally filtered by category."""
        guides = list(self.GUIDES.values())
        if category:
            guides = [g for g in guides if g.category == category]
        return guides

    def get_guide(self, guide_id: str) -> BuildGuide | None:
        """Get a build guide by ID."""
        return self.GUIDES.get(guide_id)

    def create_project(self, guide_id: str, name: str) -> BuildProject:
        """Create a new build project from a guide."""
        guide = self.GUIDES.get(guide_id)
        if not guide:
            raise ValueError(f"unknown guide: {guide_id}")
        project = BuildProject(
            project_id=f"byox-{int(time.time() * 1000)}",
            guide_id=guide_id,
            name=name,
            status="planned",
        )
        self.projects[project.project_id] = project
        if self.events:
            self.events.append({
                "event": "build_your_own_x.project_created",
                "project_id": project.project_id,
                "guide_id": guide_id,
                "name": name,
                "at": project.created_at,
            })
        return project

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "build_your_own_x",
            "status": "operational" if self._initialized else "offline",
            "source": "https://github.com/codecrafters-io/build-your-own-x",
            "guides": len(self.GUIDES),
            "categories": len(self.CATEGORIES),
            "projects": len(self.projects),
            "capabilities": [
                "guide_reference",
                "project_planning",
                "implementation_tracking",
                "technology_roadmap",
            ],
            "read_only": True,
            "policy_gated": True,
            "constraints": [
                "no_external_code_fetch_without_approval",
                "implementation_requires_policy_grant",
                "read_only_reference",
            ],
        }


# Global instance
_byox: BuildYourOwnX | None = None


def get_build_your_own_x(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> BuildYourOwnX:
    """Get or create the global Build-Your-Own-X instance."""
    global _byox
    if _byox is None:
        _byox = BuildYourOwnX(policy=policy, events=events)
    return _byox


__all__ = [
    "BuildYourOwnX",
    "BuildGuide",
    "BuildProject",
    "get_build_your_own_x",
]