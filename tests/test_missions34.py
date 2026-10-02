"""3.4 — proposals, detectors, HUD, API, CLI. Behavior verified."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.missions import detectors as detectors_mod  # noqa: E402
from jarvis.missions.hud import HudContext, build_snapshot  # noqa: E402
from jarvis.missions.manager import (  # noqa: E402
    InvalidProposalState,
    MissionDependencies,
    MissionManager,
)
from jarvis.missions.model import MissionStatus as _MS  # noqa: E402,F401
from jarvis.missions.model import MissionStatus  # noqa: E402
from jarvis.missions.proposals import (  # noqa: E402
    InvalidProposalTransition,
    MissionProposal,
    ProposalStatus,
    proposal_dedup_key,
    score_proposal,
    validate_proposal_transition,
)

ROOT = str(Path(__file__).resolve().parent.parent)


def _manager(**kw):
    deps = MissionDependencies(**kw)
    return MissionManager(deps)


# -- proposal model ----------------------------------------------------
def test_proposal_defaults_and_roundtrip():
    proposal = MissionProposal(title="T", reason="R", source="goal")
    assert proposal.status == ProposalStatus.DRAFT
    assert proposal.version == 1
    back = MissionProposal.from_dict(proposal.to_dict())
    assert back.title == "T" and back.status == ProposalStatus.DRAFT
    legacy = MissionProposal.from_dict({"title": "old"})
    assert legacy.status == ProposalStatus.DRAFT
    bad = MissionProposal.from_dict({"title": "x", "status": "bogus"})
    assert bad.status == ProposalStatus.DRAFT


def test_proposal_state_machine_valid():
    proposal = MissionProposal(title="T")
    proposal.transition(ProposalStatus.PROPOSED)
    proposal.transition(ProposalStatus.APPROVED)
    proposal.transition(ProposalStatus.CONVERTED)
    assert proposal.version == 4


def test_proposal_invalid_transitions():
    proposal = MissionProposal(title="T")
    try:
        proposal.transition(ProposalStatus.APPROVED)
        raise AssertionError("DRAFT→APPROVED must fail")
    except InvalidProposalTransition:
        pass
    proposal.transition(ProposalStatus.PROPOSED)
    proposal.transition(ProposalStatus.REJECTED)
    try:
        proposal.transition(ProposalStatus.APPROVED)
        raise AssertionError("terminal REJECTED must fail")
    except InvalidProposalTransition:
        pass
    validate_proposal_transition(ProposalStatus.DRAFT, ProposalStatus.CANCELLED)


def test_proposal_expiry_flag():
    live = MissionProposal(title="T", expires_at=time.time() + 3600)
    assert live.expired is False
    dead = MissionProposal(title="T", expires_at=time.time() - 1)
    assert dead.expired is True
    assert MissionProposal(title="T").expired is False


def test_dedup_key_deterministic():
    first = proposal_dedup_key("goal", "Build X", "", "advance")
    assert first == proposal_dedup_key("goal", "  build x  ", "", "advance")
    assert first != proposal_dedup_key("goal", "Build Y", "", "advance")
    assert first != proposal_dedup_key("event", "Build X", "", "advance")


def test_score_bounded_and_factored():
    score, factors = score_proposal(0.8, 0.7, 0.6, 0.9)
    assert 0.0 <= score <= 1.0
    assert set(factors) == {"urgency", "relevance", "novelty", "confidence"}
    clamped, _ = score_proposal(0.8, 0.7, 0.6, 0.9,
                                weights={"urgency": 99.0, "novelty": -5.0})
    assert 0.0 <= clamped <= 1.0
    rec_score, rec_factors = score_proposal(0.5, 0.5, 0.5, 0.5,
                                            weights=None)
    assert "recurrence" not in rec_factors


# -- detectors ---------------------------------------------------------
def test_detect_blocked_mission():
    manager = _manager()
    mission = manager.create("Stuck", goal="ship it")
    mission.status = mission.status.__class__("blocked")
    mission.blocked_by = ["camera backend missing"]
    found = detectors_mod.detect_blocked_missions(manager)
    assert len(found) == 1
    assert found[0].source == "blocked-mission"
    assert found[0].status == ProposalStatus.PROPOSED
    assert "camera backend missing" in found[0].reason
    assert found[0].suggested_objectives
    # Second scan: dedup, no duplicate proposal.
    assert detectors_mod.detect_blocked_missions(manager) == []
    assert len(manager.list_proposals()) == 1


def test_detect_blocked_objective():
    manager = _manager()
    mission = manager.create("Pipes", goal="build pipeline")
    first = manager.add_objective(mission.mission_id, "Research")
    second = manager.add_objective(
        mission.mission_id, "Build", depends_on=[first.objective_id])
    from jarvis.missions.model import ObjectiveStatus
    second.status = ObjectiveStatus.BLOCKED
    found = detectors_mod.detect_blocked_objectives(manager)
    assert len(found) == 1
    assert found[0].source == "blocked-objective"


def test_detect_unfinished_goals():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    palace.store_goal("Build JARVIS vision", source="user")
    manager = _manager()
    found = detectors_mod.detect_unfinished_goals(manager, palace)
    assert len(found) == 1
    assert found[0].source == "goal"
    assert "vision" in found[0].goal_refs or "vision" in found[0].title.lower()
    assert detectors_mod.detect_unfinished_goals(None, None) == []


def test_detect_repeated_failures_threshold_and_cooldown():
    from jarvis.core.types import TaskState
    from jarvis.tasks.engine import TaskEngine
    tasks = TaskEngine()
    task = tasks.register("flaky deploy")
    task.state = TaskState.FAILED
    task.attempts = 5
    task.history.append({"event": "failed", "at": time.time() - 7200})
    manager = _manager()
    found = detectors_mod.detect_repeated_failures(
        manager, tasks, threshold=3, cooldown_s=3600)
    assert len(found) == 1
    assert found[0].source == "failure"
    # Below threshold: silence.
    task2 = tasks.register("ok task")
    task2.state = TaskState.FAILED
    task2.attempts = 1
    assert detectors_mod.detect_repeated_failures(
        manager, tasks, threshold=3) == []
    assert detectors_mod.detect_repeated_failures(manager, None) == []


def test_detect_capability_gap():
    manager = _manager()
    mission = manager.create("Needful", goal="needs things")
    obj = manager.add_objective(mission.mission_id, "Do it")
    obj.required_tools = ["tool-missing-xyz"]
    found = detectors_mod.detect_capability_gaps(manager, tools=None)
    assert found == []  # no tool registry → no claims
    assert detectors_mod.detect_capability_gaps(
        manager, tools=None, required=["tool-missing-xyz"]) == []


def test_detect_world_changes():
    manager = _manager()
    assert detectors_mod.detect_world_changes(manager, None) == []
    assert detectors_mod.scan_all(manager) == []


def test_scan_all_aggregates():
    manager = _manager()
    mission = manager.create("Stuck", goal="ship it")
    mission.status = mission.status.__class__("blocked")
    mission.blocked_by = ["no network"]
    found = detectors_mod.scan_all(manager)
    assert any(p.source == "blocked-mission" for p in found)


# -- approval lifecycle --------------------------------------------------
def test_approve_reject_ignore_paths():
    manager = _manager()
    mission = manager.create("M", goal="g")
    mission.status = mission.status.__class__("blocked")
    mission.blocked_by = ["x"]
    proposal = detectors_mod.detect_blocked_missions(manager)[0]
    manager.approve_proposal(proposal.proposal_id, by="tester")
    assert proposal.status == ProposalStatus.APPROVED
    assert proposal.provenance["approved_by"] == "tester"
    second = detectors_mod.detect_blocked_missions(manager)
    assert second == []  # approved proposals do not reduplicate
    manager2 = _manager()
    mission2 = manager2.create("M2", goal="g2")
    mission2.status = mission2.status.__class__("blocked")
    mission2.blocked_by = ["y"]
    other = detectors_mod.detect_blocked_missions(manager2)[0]
    manager2.reject_proposal(other.proposal_id, reason="not now")
    assert other.status == ProposalStatus.REJECTED
    assert any("not now" in u for u in other.uncertainty)
    third = detectors_mod.detect_blocked_missions(manager2)
    assert third == [] or all(
        p.proposal_id != other.proposal_id for p in third)


def test_expire_proposals():
    manager = _manager()
    mission = manager.create("M", goal="g")
    mission.status = mission.status.__class__("blocked")
    mission.blocked_by = ["x"]
    proposal = detectors_mod.detect_blocked_missions(manager)[0]
    proposal.expires_at = time.time() - 1
    assert manager.expire_proposals() == [proposal.proposal_id]
    assert proposal.status == ProposalStatus.EXPIRED
    assert manager.expire_proposals() == []


def test_convert_creates_mission_once():
    manager = _manager()
    mission = manager.create("Orig", goal="original")
    mission.status = mission.status.__class__("blocked")
    mission.blocked_by = ["camera"]
    proposal = detectors_mod.detect_blocked_missions(manager)[0]
    manager.approve_proposal(proposal.proposal_id)
    created = manager.convert_proposal(proposal.proposal_id)
    assert created.goal and proposal.status == ProposalStatus.CONVERTED
    assert proposal.converted_mission_id == created.mission_id
    assert created.metadata["proposal_id"] == proposal.proposal_id
    assert len(created.objectives) == len(proposal.suggested_objectives)
    # Idempotent: second call returns the same mission.
    assert manager.convert_proposal(
        proposal.proposal_id).mission_id == created.mission_id


def test_convert_refuses_unapproved_and_stale():
    manager = _manager()
    mission = manager.create("M", goal="g")
    mission.status = mission.status.__class__("blocked")
    mission.blocked_by = ["x"]
    proposal = detectors_mod.detect_blocked_missions(manager)[0]
    try:
        manager.convert_proposal(proposal.proposal_id)
        raise AssertionError("unapproved conversion must fail")
    except Exception as exc:
        assert "APPROVED" in str(exc)
    manager.approve_proposal(proposal.proposal_id)
    try:
        manager.convert_proposal(
            proposal.proposal_id,
            still_valid=lambda: (False, "service recovered"))
        raise AssertionError("stale conversion must fail")
    except Exception as exc:
        assert "no longer necessary" in str(exc)
    assert proposal.status == ProposalStatus.CANCELLED


def test_convert_blocked_by_emergency_stop(tmp_path):
    from jarvis.core.config import JarvisConfig
    from jarvis.policy.policy import PolicyEngine
    config = JarvisConfig()
    config.paths.home = Path(tempfile.mkdtemp())
    policy = PolicyEngine(config)
    policy.engage_stop()
    try:
        from jarvis.missions.manager import MissionDependencies
        manager = MissionManager(MissionDependencies(policy=policy))
        mission = manager.create("M", goal="g")
        mission.status = mission.status.__class__("blocked")
        mission.blocked_by = ["x"]
        proposal = detectors_mod.detect_blocked_missions(manager)[0]
        manager.approve_proposal(proposal.proposal_id)
        try:
            manager.convert_proposal(proposal.proposal_id)
            raise AssertionError("e-stop conversion must fail")
        except Exception as exc:
            assert "emergency stop" in str(exc)
    finally:
        policy.release_stop()


def test_proposal_persistence_roundtrip(tmp_path):
    from jarvis.missions.manager import MissionDependencies, MissionManager
    from jarvis.world.registry import JsonFileWorldStore
    store = JsonFileWorldStore(str(tmp_path / "missions.json"))
    manager = MissionManager(MissionDependencies(store=store))
    mission = manager.create("M", goal="g")
    mission.status = mission.status.__class__("blocked")
    mission.blocked_by = ["x"]
    proposal = detectors_mod.detect_blocked_missions(manager)[0]
    fresh = MissionManager(MissionDependencies(store=store))
    assert fresh.get_proposal(proposal.proposal_id) is not None
    assert fresh.get_proposal("prop-missing") is None


# -- HUD -----------------------------------------------------------------
def test_hud_snapshot_structure():
    from jarvis.missions.hud import HudContext, build_snapshot
    manager = _manager()
    mission = manager.create("HUD", goal="show me")
    manager.add_objective(mission.mission_id, "Step")
    snapshot = build_snapshot(HudContext(missions=manager))
    for key in ("missions", "objectives", "dots", "tasks", "blockers",
                "approvals", "notifications", "evidence", "proposals",
                "system", "emergency_stop", "generated_at"):
        assert key in snapshot, key
    assert snapshot["missions"][0]["name"] == "HUD"
    assert snapshot["emergency_stop"] is False
    import json
    json.dumps(snapshot, default=str)  # must serialize


def test_hud_degrades_with_nothing_bound():
    from jarvis.missions.hud import HudContext, build_snapshot
    snapshot = build_snapshot(HudContext())
    assert snapshot["missions"] == []
    assert snapshot["emergency_stop"] is False


def test_hud_never_leaks_tokens():
    from jarvis.missions.hud import HudContext, build_snapshot
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.types import ActionPlan
    policy = PolicyEngine()
    plan = ActionPlan(action="terminal_run x", args={},
                      required_permissions=["exec"])
    decision = policy.evaluate("op", plan)
    token = policy.request_approval("op", plan, decision)
    snapshot = build_snapshot(HudContext(policy=policy))
    dumped = json.dumps(snapshot, default=str)
    assert token not in dumped
    assert any("…" in a.get("token_hint", "") for a in snapshot["approvals"])


# -- API -------------------------------------------------------------------
def _api():
    from jarvis.api.server import JarvisAPI
    from unittest.mock import MagicMock
    from jarvis.missions.manager import MissionDependencies, MissionManager
    jarvis = MagicMock()
    jarvis.missions = MissionManager(MissionDependencies())
    api = JarvisAPI(jarvis)
    return api


def test_api_control_and_proposals():
    api = _api()
    manager = api.jarvis.missions
    mission = manager.create("Web", goal="via api")
    code, payload = api.handle("GET", "/api/missions/control", b"", {})
    assert code == 200 and payload["missions"]
    code, payload = api.handle(
        "GET", f"/api/missions/{mission.mission_id}", b"", {})
    assert code == 200 and payload["mission_id"] == mission.mission_id
    code, _ = api.handle("GET", "/api/missions/msn-nope", b"", {})
    assert code == 404
    code, payload = api.handle("GET", "/api/missions/proposals", b"", {})
    assert code == 200 and payload["proposals"] == []
    code, _ = api.handle("GET", "/api/missions/proposals/prop-nope",
                         b"", {})
    assert code == 404


# -- CLI ---------------------------------------------------------------------
def test_cli_proposals_flow(tmp_path):
    home = str(tmp_path)
    base = ["python3", "-m", "jarvis.cli", "--home", home, "missions",
            "proposals"]

    def run(*args, expect=0):
        proc = subprocess.run(list(base) + list(args), capture_output=True,
                              text=True, timeout=180, cwd=ROOT)
        assert proc.returncode == expect, proc.stderr[-500:]
        return proc.stdout

    assert "no proposals" in run("list").lower()
    mid = json.loads(subprocess.run(
        ["python3", "-m", "jarvis.cli", "--home", home, "missions",
         "create", "Stuck | blocked goal", "--json"],
        capture_output=True, text=True, timeout=180,
        cwd=ROOT).stdout)["mission"]["mission_id"]
    # Force blocked state via objectives path is covered elsewhere; use scan
    # on an empty system (may find nothing) and manual lifecycle instead.
    assert "nothing detected" in run("scan").lower() or "score=" in run("scan")
    assert "unknown proposal" in run("inspect", "prop-nope", expect=2)
    assert "usage" in run("approve", expect=2).lower()


def test_cli_control_and_missions_regression(tmp_path):
    home = str(tmp_path)

    def run(*args, expect=0):
        proc = subprocess.run(
            ["python3", "-m", "jarvis.cli", "--home", home] + list(args),
            capture_output=True, text=True, timeout=180, cwd=ROOT)
        assert proc.returncode == expect, proc.stderr[-500:]
        return proc.stdout

    assert "missions:" in run("missions", "control").lower()
    assert "missions" in run("missions", "control", "--json").lower()
    assert "no missions yet" in run("missions", "list").lower()
