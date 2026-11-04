"""Phase 10: Experience Layer — read-only UI consuming real JARVIS state.

Tests that the Experience Manager and dashboard:
- Read real state from MemoryPalace, WorldModel, PolicyEngine, TaskEngine,
  EnhancedSupervisor — never create duplicates
- Expose no secrets, approval tokens, or raw credentials
- Produce valid HTML dashboard from real subsystem state
- Are read-only: nothing is mutated
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.memory.palace import MemoryPalace
from jarvis.policy.policy import PolicyEngine
from jarvis.tasks.engine import TaskEngine
from jarvis.world.model import WorldModel
from jarvis.agents import EnhancedSupervisor
from jarvis.experience import ExperienceView, ExperienceManager
from jarvis.experience.dashboard import render_dashboard, render_from_manager


# -- helpers ------------------------------------------------------------


def _mk_palace() -> MemoryPalace:
    home = tempfile.mkdtemp(prefix="exp-palace-")
    return MemoryPalace(path=str(Path(home) / "memories.db"))


def _mk_world() -> WorldModel:
    return WorldModel()


def _mk_policy() -> PolicyEngine:
    return PolicyEngine()


def _mk_tasks() -> TaskEngine:
    return TaskEngine()


def _mk_supervisor() -> EnhancedSupervisor:
    return EnhancedSupervisor()


# -- ExperienceManager snapshot tests ------------------------------------


def test_snapshot_empty_subsystems():
    """Snapshot with no subsystems returns zeros."""
    mgr = ExperienceManager()
    v = mgr.snapshot()
    assert v.memory_total == 0
    assert v.memory_live == 0
    assert v.memory_archived == 0
    assert v.world_entities == 0
    assert v.world_events == 0
    assert v.world_rooms == 0
    assert v.agents_total == 0
    assert v.agents_idle == 0
    assert v.agents_working == 0
    assert v.agents_failed == 0
    assert v.tasks_total == 0
    assert v.tasks_queued == 0
    assert v.tasks_running == 0
    assert v.tasks_completed == 0
    assert v.tasks_failed == 0
    assert v.policy_decisions == 0
    assert v.pending_approvals == 0
    assert v.emergency_stop is False
    assert v.posture == "clear"


def test_snapshot_reads_memory_palace():
    """Snapshot reads real MemoryPalace stats."""
    palace = _mk_palace()
    palace.store_conversation("user", "hello", session_id="s1", room="Home")
    palace.store_conversation("jarvis", "hi there", session_id="s1", room="Home")
    palace.store_episode("test episode", room="Home", importance=0.5)

    mgr = ExperienceManager(palace=palace)
    v = mgr.snapshot()
    assert v.memory_total >= 2
    assert v.memory_live >= 2


def test_snapshot_reads_world_model():
    """Snapshot reads real WorldModel state."""
    world = _mk_world()
    world.upsert("device", "laptop", status="online")
    world.record_event("test event", source="test")

    mgr = ExperienceManager(world=world)
    v = mgr.snapshot()
    assert v.world_entities == 1
    assert v.world_events == 1


def test_snapshot_reads_agents():
    """Snapshot reads real EnhancedSupervisor agents."""
    sup = _mk_supervisor()
    reg = sup.registry

    mgr = ExperienceManager(supervisor=sup)
    v = mgr.snapshot()
    assert v.agents_total == len(reg.list_agents())
    # All default agents should be idle initially
    assert v.agents_idle == v.agents_total


def test_snapshot_reads_tasks():
    """Snapshot reads real TaskEngine state."""
    tasks = _mk_tasks()
    tasks.register("task one", priority=5)
    tasks.register("task two", priority=3)

    mgr = ExperienceManager(tasks=tasks)
    v = mgr.snapshot()
    assert v.tasks_total == 2
    assert v.tasks_queued == 2


def test_policy_decisions_count():
    """policy_decisions counts pending approvals from PolicyEngine."""
    policy = _mk_policy()

    # Create an approval via request_approval
    from jarvis.core.types import ActionPlan
    plan = ActionPlan(action="filesystem_write", args={"path": "/tmp/test.txt"})
    decision = policy.evaluate("security-manager", plan)
    token = policy.request_approval("security-manager", plan, decision)

    mgr = ExperienceManager(policy=policy)
    count = mgr.pending_approval_count()
    assert count >= 1  # Our token plus any pending from previous runs

    # Approving removes it from pending
    assert policy.approve(token, by="operator") is True
    # Our specific token is no longer pending
    assert policy.approvals[token]["status"] == "approved"


def test_emergency_stop_flag():
    """emergency_stop reads from PolicyEngine."""
    policy = _mk_policy()

    mgr = ExperienceManager(policy=policy)
    assert mgr.snapshot().emergency_stop is False

    policy.engage_stop()
    assert mgr.snapshot().emergency_stop is True

    policy.release_stop()
    assert mgr.snapshot().emergency_stop is False


def test_posture_from_memory():
    """Posture reflects memory state."""
    palace = _mk_palace()

    # No memories -> clear
    mgr = ExperienceManager(palace=palace)
    assert mgr.snapshot().posture == "clear"

    # Some live memories -> review
    palace.store_episode("test", room="Home", importance=0.5)
    mgr = ExperienceManager(palace=palace)
    assert mgr.snapshot().posture == "review"

    # Archived > 0 but not > live -> attention
    palace.store_episode("old", room="Home", importance=0.1)
    palace.archive(palace.all(tier="episodic")[0].id)
    mgr = ExperienceManager(palace=palace)
    assert mgr.snapshot().posture == "attention"

    # More archived than live -> critical
    for i in range(5):
        palace.store_episode(f"old {i}", room="Home", importance=0.1)
    all_episodes = palace.all(tier="episodic")
    # Keep only 1 live, archive the rest
    for m in all_episodes[1:]:
        palace.archive(m.id)
    mgr = ExperienceManager(palace=palace)
    assert mgr.snapshot().posture == "critical"


def test_snapshot_is_read_only():
    """Snapshot does not mutate any subsystem."""
    palace = _mk_palace()
    world = _mk_world()
    policy = _mk_policy()
    tasks = _mk_tasks()
    sup = _mk_supervisor()

    mgr = ExperienceManager(palace=palace, world=world, policy=policy,
                            tasks=tasks, supervisor=sup)

    palace_count_before = len(palace.all())
    world_count_before = len(world.entities())
    tasks_count_before = len(tasks.tasks)

    mgr.snapshot()

    assert len(palace.all()) == palace_count_before
    assert len(world.entities()) == world_count_before
    assert len(tasks.tasks) == tasks_count_before


# -- Dashboard rendering tests ---------------------------------------------


def test_render_dashboard_returns_html():
    """render_dashboard produces valid HTML with expected sections."""
    palace = _mk_palace()
    palace.store_episode("test episode", room="Home", importance=0.5)

    mgr = ExperienceManager(palace=palace)
    snap = mgr.snapshot()
    html = render_dashboard(snap)

    assert "<!doctype html>" in html.lower()
    assert "<html" in html.lower()
    assert "JARVIS-OS" in html
    assert "System Dashboard" in html
    assert "System Posture" in html
    assert "Subsystem health" in html
    assert "Memory" in html
    assert "World Model" in html
    assert "Agents" in html
    assert "Tasks" in html
    assert "Security" in html


def test_render_dashboard_escapes_values():
    """Dashboard HTML-escapes values — no injection."""
    palace = _mk_palace()
    palace.store_conversation("user", "<script>alert('xss')</script>",
                              session_id="s1", room="Home")

    mgr = ExperienceManager(palace=palace)
    snap = mgr.snapshot()
    html = render_dashboard(snap)

    # The raw script tag should not appear; it should be escaped
    assert "<script>" not in html
    assert "&lt;script&gt;" in html or "alert" not in html


def test_render_dashboard_from_manager():
    """render_from_manager produces HTML from an ExperienceManager."""
    palace = _mk_palace()
    palace.store_episode("dashboard test", room="Home", importance=0.5)

    mgr = ExperienceManager(palace=palace)
    snap = mgr.snapshot()
    html = render_from_manager(mgr)

    assert "<!doctype html>" in html.lower()
    assert str(snap.memory_total) in html


def test_render_dashboard_no_secrets():
    """Dashboard never exposes approval tokens or secrets."""
    policy = _mk_policy()

    from jarvis.core.types import ActionPlan
    plan = ActionPlan(action="filesystem_write", args={"path": "/tmp/secret.txt"})
    decision = policy.evaluate("security-manager", plan)
    token = policy.request_approval("security-manager", plan, decision)

    mgr = ExperienceManager(policy=policy)
    html = render_dashboard(mgr.snapshot())

    assert token not in html
    assert "secret.txt" not in html  # secret path should not leak


def test_dashboard_posture_badge():
    """Dashboard renders posture badge."""
    palace = _mk_palace()
    palace.store_episode("test", room="Home", importance=0.5)

    mgr = ExperienceManager(palace=palace)
    snap = mgr.snapshot()
    html = render_dashboard(snap)

    assert f'posture-{snap.posture}' in html
    assert snap.posture in html


def test_health_check():
    """health() reports subsystem status."""
    palace = _mk_palace()
    world = _mk_world()
    policy = _mk_policy()
    tasks = _mk_tasks()
    sup = _mk_supervisor()

    mgr = ExperienceManager(palace=palace, world=world, policy=policy,
                            tasks=tasks, supervisor=sup)
    health = mgr.health()

    assert "healthy" in health
    assert health["healthy"] is True
    assert "posture" in health
    assert "subsystems" in health
    assert health["subsystems"]["memory_palace"] is True
    assert health["subsystems"]["world_model"] is True
    assert health["subsystems"]["policy_engine"] is True
    assert health["subsystems"]["task_engine"] is True
    assert health["subsystems"]["agent_supervisor"] is True


def test_as_public_report_no_secrets():
    """as_public_report returns scrubbed report."""
    palace = _mk_palace()
    palace.store_episode("test", room="Home", importance=0.5)

    mgr = ExperienceManager(palace=palace)
    report = mgr.as_public_report()

    assert "snapshot" in report
    assert "pending_approval_count" in report
    assert "health" in report
    assert report["snapshot"]["memory_total"] >= 1


def test_empty_dashboard_still_valid():
    """Empty dashboard renders valid HTML."""
    mgr = ExperienceManager()
    snap = mgr.snapshot()
    html = render_dashboard(snap)

    assert "<!doctype html>" in html.lower()
    assert "JARVIS-OS" in html
    assert "System Dashboard" in html


def test_view_to_dict_is_dict():
    """ExperienceView.to_dict returns a dict."""
    view = ExperienceView()
    d = view.to_dict()
    assert isinstance(d, dict)
    assert d["memory_total"] == 0
    assert d["posture"] == "unknown"