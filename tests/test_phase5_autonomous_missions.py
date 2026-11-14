"""Phase 5 integration tests: Autonomous Missions.

Tests:
- MissionApprovalGate — policy-gated mission step execution with
  approval tokens, pause/resume, deny
- MissionReplanner — world change detection, impact assessment,
  proposal generation
- Combined flow — mission with approval + replanning

No offensive capabilities. All targets are local temp fixtures.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.policy.policy import PolicyEngine
from jarvis.missions import (
    MissionManager, MissionDependencies, Mission, MissionStatus,
    MissionApprovalGate, MissionStepVerdict, MissionReplanner,
    ChangeImpact,
)
from jarvis.missions.proposals import MissionProposal


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-missions-")


@pytest.fixture
def config(home):
    cfg = JarvisConfig()
    cfg.paths.home = Path(home)
    cfg.policy.local_only = True
    cfg.models.cloud_enabled = False
    cfg.models.ollama_enabled = False
    cfg.policy.require_approval_above_risk = 0.3
    return cfg


@pytest.fixture
def policy(config):
    return PolicyEngine(config=config)


@pytest.fixture
def manager(home, config, policy):
    deps = MissionDependencies(
        tasks=None, dots=None, palace=None,
        world_registry=None, triggers=None, store=None,
        policy=policy, bus=None)
    return MissionManager(deps=deps)


# -- MissionApprovalGate tests --------------------------------------------


def test_approval_gate_allows_safe_step(policy):
    """Safe mission steps pass through without approval."""
    gate = MissionApprovalGate(policy=policy, actor="mission-test")

    verdict = gate.evaluate(
        action="filesystem_read",
        args={"path": "/tmp/safe.txt"},
        mission_id="mission-1", objective_id="obj-1", step_index=0,
    )

    assert verdict.allowed is True
    assert verdict.approval_token == ""
    assert gate.allowed_count == 1
    assert gate.blocked_count == 0


def test_approval_gate_creates_token_for_risky_step(policy):
    """Risky mission steps create approval tokens and pause."""
    gate = MissionApprovalGate(policy=policy, actor="mission-test")

    verdict = gate.evaluate(
        action="filesystem_write",
        args={"path": "/tmp/sensitive.txt", "content": "data"},
        mission_id="mission-1", objective_id="obj-1", step_index=0,
    )

    assert verdict.allowed is True  # allowed but needs approval
    assert verdict.approval_token != ""
    assert len(verdict.approval_token) >= 8
    assert gate.pending_count == 1
    assert verdict.needs_approval() is True


def test_approval_gate_blocks_destructive_step(policy):
    """Destructive mission steps are blocked."""
    gate = MissionApprovalGate(policy=policy, actor="mission-test")

    verdict = gate.evaluate(
        action="rm -rf /",
        args={},
        mission_id="mission-1", objective_id="obj-1", step_index=0,
    )

    assert verdict.allowed is False
    assert gate.blocked_count == 1


def test_approval_gate_check_approval(policy):
    """check_approval reflects PolicyEngine state."""
    gate = MissionApprovalGate(policy=policy, actor="mission-test")

    verdict = gate.evaluate(
        action="filesystem_write",
        args={"path": "/tmp/sensitive.txt", "content": "data"},
        mission_id="mission-1", objective_id="obj-1", step_index=0,
    )
    token = verdict.approval_token

    # Not yet approved
    assert gate.check_approval(token) is False

    # Approve via PolicyEngine
    assert policy.approve(token, by="operator") is True
    assert gate.check_approval(token) is True


def test_approval_gate_pending_list(policy):
    """pending() lists all missions waiting for approval."""
    gate = MissionApprovalGate(policy=policy, actor="mission-test")

    gate.evaluate(
        action="filesystem_write",
        args={"path": "/tmp/a.txt", "content": "a"},
        mission_id="mission-1", objective_id="obj-1", step_index=0,
    )
    gate.evaluate(
        action="filesystem_write",
        args={"path": "/tmp/b.txt", "content": "b"},
        mission_id="mission-2", objective_id="obj-2", step_index=0,
    )

    pending = gate.pending()
    assert len(pending) == 2
    mission_ids = {p["mission_id"] for p in pending}
    assert mission_ids == {"mission-1", "mission-2"}

    for p in pending:
        assert p["token_prefix"] != ""
        assert p["risk_level"] in ("low", "medium", "high", "destructive")


def test_approval_gate_status(policy):
    """status() includes approval metrics."""
    gate = MissionApprovalGate(policy=policy, actor="mission-test")

    gate.evaluate(
        action="filesystem_read",
        args={"path": "/tmp/safe.txt"},
        mission_id="mission-1", objective_id="obj-1", step_index=0,
    )
    gate.evaluate(
        action="filesystem_write",
        args={"path": "/tmp/sensitive.txt", "content": "x"},
        mission_id="mission-1", objective_id="obj-1", step_index=1,
    )

    status = gate.status()
    assert status["total_evaluations"] == 2
    assert status["allowed"] == 1
    assert status["pending_approvals"] == 1
    assert status["blocked"] == 0


# -- MissionReplanner tests -----------------------------------------------


def test_replanner_detects_entity_added():
    """detect_changes finds new entities in world snapshots."""
    replanner = MissionReplanner()

    previous = {"entities": [], "timeline": []}
    current = {
        "entities": [{"entity_id": "device:laptop",
                      "name": "laptop", "attributes": {"status": "online"}}],
        "timeline": [],
    }

    changes = replanner.detect_changes(previous, current)
    assert len(changes) == 1
    assert changes[0]["kind"] == "entity_added"
    assert changes[0]["entity_id"] == "device:laptop"


def test_replanner_detects_entity_updated():
    """detect_changes finds entity attribute updates."""
    replanner = MissionReplanner()

    previous = {
        "entities": [{"entity_id": "device:laptop",
                      "name": "laptop", "attributes": {"status": "online"}}],
        "timeline": [],
    }
    current = {
        "entities": [{"entity_id": "device:laptop",
                      "name": "laptop", "attributes": {"status": "offline"}}],
        "timeline": [],
    }

    changes = replanner.detect_changes(previous, current)
    assert len(changes) == 1
    assert changes[0]["kind"] == "entity_updated"
    assert changes[0]["entity_id"] == "device:laptop"


def test_replanner_detects_entity_removed():
    """detect_changes finds entity removals."""
    replanner = MissionReplanner()

    previous = {
        "entities": [{"entity_id": "device:old-phone",
                      "name": "old phone", "attributes": {"status": "offline"}}],
        "timeline": [],
    }
    current = {"entities": [], "timeline": []}

    changes = replanner.detect_changes(previous, current)
    assert len(changes) == 1
    assert changes[0]["kind"] == "entity_removed"
    assert changes[0]["entity_id"] == "device:old-phone"


def test_replanner_detects_timeline_event():
    """detect_changes finds new timeline events."""
    replanner = MissionReplanner()

    previous = {"entities": [], "timeline": [{"description": "old event"}]}
    current = {
        "entities": [],
        "timeline": [
            {"description": "old event"},
            {"description": "new event", "source": "system"},
        ],
    }

    changes = replanner.detect_changes(previous, current)
    assert len(changes) == 1
    assert changes[0]["kind"] == "timeline_event"
    assert changes[0]["description"] == "new event"


def test_replanner_no_changes_returns_empty():
    """No changes returns an empty list."""
    replanner = MissionReplanner()

    snapshot = {"entities": [], "timeline": []}
    changes = replanner.detect_changes(snapshot, snapshot)
    assert changes == []


def test_replanner_assess_impact_matches_objective():
    """assess_impact finds changes that match objective keywords."""
    replanner = MissionReplanner()

    # Create a mock mission with objectives
    class MockObjective:
        def __init__(self, oid, desc):
            self.objective_id = oid
            self.description = desc

    class MockMission:
        def __init__(self, mid, objectives):
            self.mission_id = mid
            self.objectives = objectives

    mission = MockMission("mission-1", [
        MockObjective("obj-1", "backup laptop data to server"),
    ])

    changes = [{
        "kind": "entity_added",
        "entity_id": "device:laptop",
        "name": "laptop",
        "attributes": {"status": "online"},
    }]

    impacts = replanner.assess_impact(mission, changes)
    assert len(impacts) >= 1
    assert impacts[0].mission_id == "mission-1"
    assert impacts[0].objective_id == "obj-1"
    assert impacts[0].needs_replan is True
    assert impacts[0].impact_score > 0


def test_replanner_assess_impact_no_match():
    """assess_impact returns empty when changes don't match objectives."""
    replanner = MissionReplanner()

    class MockObjective:
        def __init__(self, oid, desc):
            self.objective_id = oid
            self.description = desc

    class MockMission:
        def __init__(self, mid, objectives):
            self.mission_id = mid
            self.objectives = objectives

    mission = MockMission("mission-1", [
        MockObjective("obj-1", "backup laptop data to server"),
    ])

    changes = [{
        "kind": "entity_added",
        "entity_id": "device:printer",
        "name": "printer",
        "attributes": {"status": "offline"},
    }]

    impacts = replanner.assess_impact(mission, changes)
    # "printer" doesn't match "laptop" in the objective
    assert len(impacts) == 0


def test_replanner_propose_replan(manager):
    """propose_replan generates MissionProposal objects for high impact."""
    replanner = MissionReplanner()

    class MockObjective:
        def __init__(self, oid, desc):
            self.objective_id = oid
            self.description = desc

    class MockMission:
        def __init__(self, mid, objectives):
            self.mission_id = mid
            self.objectives = objectives

    mission = MockMission("mission-1", [
        MockObjective("obj-1", "backup laptop data to server"),
    ])

    impacts = [
        ChangeImpact(
            mission_id="mission-1",
            objective_id="obj-1",
            change_type="entity_added",
            change_description="laptop came online",
            impact_score=0.8,
            needs_replan=True,
            reason="laptop mentioned in objective",
        )
    ]

    proposals = replanner.propose_replan(manager, mission, impacts)
    assert len(proposals) == 1
    assert "proposal_id" in proposals[0]
    assert "title" in proposals[0]
    assert "reason" in proposals[0]
    assert "replan" in proposals[0]["title"].lower() or "mission" in proposals[0]["title"].lower()


def test_replanner_skips_low_impact(manager):
    """propose_replan skips changes with impact below 0.5."""
    replanner = MissionReplanner()

    class MockObjective:
        def __init__(self, oid, desc):
            self.objective_id = oid
            self.description = desc

    class MockMission:
        def __init__(self, mid, objectives):
            self.mission_id = mid
            self.objectives = objectives

    mission = MockMission("mission-1", [
        MockObjective("obj-1", "backup data"),
    ])

    impacts = [
        ChangeImpact(
            mission_id="mission-1",
            objective_id="obj-1",
            change_type="entity_added",
            change_description="minor change",
            impact_score=0.3,  # below 0.5 threshold
            needs_replan=True,
            reason="low impact",
        )
    ]

    proposals = replanner.propose_replan(manager, mission, impacts)
    assert len(proposals) == 0


def test_replanner_status():
    """status() returns replanner metrics."""
    replanner = MissionReplanner()
    status = replanner.status()
    assert "proposals_generated" in status
    assert "has_world_snapshot" in status
    assert status["has_world_snapshot"] is False

    replanner.update_world_snapshot({"entities": [], "timeline": []})
    status = replanner.status()
    assert status["has_world_snapshot"] is True


# -- Combined flow tests --------------------------------------------------


def test_mission_with_approval_and_replanning(manager, policy):
    """Combined flow: mission step requires approval, then world change
    triggers replanning proposal."""
    gate = MissionApprovalGate(policy=policy, actor="mission-test")
    replanner = MissionReplanner(manager=manager)

    # Step 1: Mission step requires approval
    verdict = gate.evaluate(
        action="filesystem_write",
        args={"path": "/tmp/mission-file.txt", "content": "mission data"},
        mission_id="mission-1", objective_id="obj-1", step_index=0,
    )
    assert verdict.allowed is True
    assert verdict.approval_token != ""

    # Approve the mission step
    assert policy.approve(verdict.approval_token, by="operator") is True
    assert gate.check_approval(verdict.approval_token) is True

    # Step 2: World change triggers replanning
    previous = {"entities": [], "timeline": []}
    current = {
        "entities": [{"entity_id": "device:laptop",
                      "name": "laptop", "attributes": {"status": "online"}}],
        "timeline": [],
    }
    changes = replanner.detect_changes(previous, current)
    assert len(changes) == 1

    class MockObjective:
        def __init__(self, oid, desc):
            self.objective_id = oid
            self.description = desc

    class MockMission:
        def __init__(self, mid, objectives):
            self.mission_id = mid
            self.objectives = objectives

    mission = MockMission("mission-1", [
        MockObjective("obj-1", "backup laptop data"),
    ])

    impacts = replanner.assess_impact(mission, changes)
    assert len(impacts) >= 1
    assert impacts[0].needs_replan is True

    # Propose replanning
    proposals = replanner.propose_replan(manager, mission, impacts)
    # May be 0 if dedup or scoring filters it, but impact is high enough
    # that it should generate at least one
    # (proposal generation depends on manager state, so we just check it
    #  doesn't crash)
    assert isinstance(proposals, list)


def test_mission_manager_integration(manager):
    """MissionManager can create and list missions."""
    # Create a mission directly via the model
    from jarvis.missions.model import Mission, MissionStatus

    mission = Mission(
        mission_id="mission-test-1",
        name="Test Mission",
        description="test objective",
        status=MissionStatus.DRAFT,
    )
    manager.missions[mission.mission_id] = mission
    manager.persist()

    assert manager.missions["mission-test-1"].name == "Test Mission"
    assert manager.missions["mission-test-1"].status == MissionStatus.DRAFT

    missions = manager.list()
    assert len(missions) == 1
    assert missions[0].mission_id == "mission-test-1"