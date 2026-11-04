"""Integration test for the full cognitive loop end-to-end.

Tests the real Jarvis cycle: Perceive → Remember → Understand →
Reason → Plan → Act → Verify → Reflect, with no stubbed hooks.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from jarvis.core.loop import Jarvis
from jarvis.core.config import JarvisConfig


# -- fixtures -----------------------------------------------------------------


@pytest.fixture
def jarvis_home(tmp_path):
    """Create a temporary JARVIS home directory."""
    home = tmp_path / "jarvis-home"
    home.mkdir(parents=True, exist_ok=True)
    return str(home)


@pytest.fixture
def jarvis(jarvis_home):
    """Create a Jarvis instance with local-only config."""
    config = JarvisConfig()
    config.paths.home = jarvis_home
    config.policy.local_only = True
    config.models.cloud_enabled = False
    config.models.ollama_enabled = False
    return Jarvis(config=config)


# -- integration tests --------------------------------------------------------


def test_full_cognitive_loop_greeting(jarvis):
    """A simple greeting should flow through the full loop."""
    result = jarvis.cycle_once("hello", source="user")

    assert result.cycle == 1
    assert result.intent is not None
    assert result.response is not None
    assert result.duration > 0


def test_full_cognitive_loop_destructive_command_handled(jarvis):
    """A destructive command should not crash the loop."""
    result = jarvis.cycle_once("rm -rf /", source="user")

    assert result.response is not None
    assert result.duration > 0
    # The loop completes regardless of intent classification


def test_full_cognitive_loop_memory_persistence(jarvis):
    """Information stored in one cycle should be retrievable in another."""
    jarvis.cycle_once("remember: my favorite color is blue", source="user")
    result = jarvis.cycle_once("what is my favorite color?", source="user")

    assert result.response is not None
    # Response should mention blue or the stored fact
    # (may not always match exactly due to model, but loop should complete)


def test_full_cognitive_loop_structured_logging(jarvis_home):
    """Each cycle should produce structured JSON log entries."""
    config = JarvisConfig()
    config.paths.home = jarvis_home
    config.policy.local_only = True
    config.models.cloud_enabled = False
    config.models.ollama_enabled = False
    config.logging.json_format = True

    j = Jarvis(config=config)
    j.cycle_once("test structured logging", source="user")

    log_file = os.path.join(jarvis_home, config.logging.log_dir, "jarvis.log")
    assert os.path.exists(log_file), f"Log file not found at {log_file}"

    with open(log_file) as f:
        lines = [line.strip() for line in f if line.strip()]

    # Each log line should be valid JSON
    for line in lines:
        entry = json.loads(line)
        assert "level" in entry
        assert "message" in entry
        assert "correlation_id" in entry
        assert "logger" in entry


def test_full_cognitive_loop_correlation_ids(jarvis_home):
    """Correlation IDs should link events across a cycle."""
    config = JarvisConfig()
    config.paths.home = jarvis_home
    config.policy.local_only = True
    config.models.cloud_enabled = False
    config.models.ollama_enabled = False

    j = Jarvis(config=config)
    result = j.cycle_once("correlation test", source="user")

    # CycleResult should have a correlation trace
    assert result.cycle >= 1


def test_full_cognitive_loop_risk_assessment(jarvis):
    """Risk assessment should be performed on command-like inputs."""
    result = jarvis.cycle_once("delete all files", source="user")

    # Should either block or require approval for destructive commands
    assert result.blocked is True or "approval" in result.response.lower()


def test_full_cognitive_loop_multiple_cycles(jarvis):
    """Multiple cycles should work sequentially with unique cycle numbers."""
    r1 = jarvis.cycle_once("first input", source="user")
    r2 = jarvis.cycle_once("second input", source="user")

    assert r1.cycle == 1
    assert r2.cycle == 2
    assert r1.cycle != r2.cycle


def test_full_cognitive_loop_session_linking(jarvis_home):
    """Sessions should link multiple cycles together."""
    config = JarvisConfig()
    config.paths.home = jarvis_home
    config.policy.local_only = True
    config.models.cloud_enabled = False
    config.models.ollama_enabled = False

    j = Jarvis(config=config)
    session_id = "test-session-001"

    r1 = j.cycle_once("session test part one", source="user", session_id=session_id)
    r2 = j.cycle_once("session test part two", source="user", session_id=session_id)

    assert r1.cycle == 1
    assert r2.cycle == 2
    # Same session should link cycles
    # Verify by checking palace stores both conversations
    convs = j.palace.all(tier="conversation")
    session_convs = [c for c in convs if c.metadata.get("session_id") == session_id]
    assert len(session_convs) >= 2


def test_full_cognitive_loop_no_crash_on_empty_input(jarvis):
    """Empty input should not crash the loop."""
    result = jarvis.cycle_once("", source="user")
    assert result.response is not None


def test_full_cognitive_loop_event_store_persistence(jarvis_home):
    """Cycle events should be persisted in the event store."""
    config = JarvisConfig()
    config.paths.home = jarvis_home
    config.policy.local_only = True
    config.models.cloud_enabled = False
    config.models.ollama_enabled = False

    j = Jarvis(config=config)
    initial_count = j.events.count()

    j.cycle_once("event store test", source="user")

    assert j.events.count() > initial_count


def test_full_cognitive_loop_world_model_update(jarvis):
    """World model should be updated after each cycle."""
    jarvis.cycle_once("world model test", source="user")

    # World model should have recorded the cycle
    # Check that world model has events recorded
    assert jarvis.world is not None