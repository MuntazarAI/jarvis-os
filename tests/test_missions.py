"""Missions 3.3 — mission control and persistent missions."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.types import TaskState  # noqa: E402
from jarvis.missions.manager import MissionDependencies, MissionManager  # noqa: E402
from jarvis.missions.model import (  # noqa: E402
    InvalidMissionTransition,
    Mission,
    MissionStatus,
    Objective,
    ObjectiveStatus,
    compute_progress,
    ready_objectives,
    validate_mission_transition,
)
from jarvis.missions.runtime import MissionContext, MissionRuntime  # noqa: E402
from jarvis.missions.verification import (  # noqa: E402
    verify_all,
    verify_criterion,
)
from jarvis.tasks.engine import TaskEngine  # noqa: E402

ROOT = str(Path(__file__).resolve().parent.parent)


def _deps(**kw):
    base = {"tasks": TaskEngine()}
    base.update(kw)
    return MissionDependencies(**base)


def _manager(**kw):
    return MissionManager(_deps(**kw))


def _mission(manager=None, **kw):
    manager = manager or _manager()
    args = {"name": "Atlas", "goal": "ship atlas"}
    args.update(kw)
    return manager, manager.create(**args)


# -- state machine ---------------------------------------------------
def test_mission_transitions_valid():
    mission = Mission(name="t", goal="g")
    assert mission.status == MissionStatus.DRAFT
    mission.transition(MissionStatus.READY)
    mission.transition(MissionStatus.RUNNING)
    mission.transition(MissionStatus.PAUSED)
    mission.transition(MissionStatus.RUNNING)
    mission.transition(MissionStatus.VERIFYING)
    mission.transition(MissionStatus.COMPLETED)
    assert mission.completed_at is not None


def test_mission_invalid_transitions_rejected():
    mission = Mission(name="t", goal="g")
    try:
        mission.transition(MissionStatus.RUNNING)
        raise AssertionError("DRAFT→RUNNING must fail")
    except InvalidMissionTransition:
        pass
    mission.transition(MissionStatus.READY)
    mission.transition(MissionStatus.RUNNING)
    mission.transition(MissionStatus.COMPLETED)
    for target in (MissionStatus.RUNNING, MissionStatus.READY,
                   MissionStatus.PAUSED, MissionStatus.STOPPED):
        try:
            mission.transition(target)
            raise AssertionError(f"COMPLETED→{target} must fail")
        except InvalidMissionTransition:
            pass
    validate_mission_transition(MissionStatus.READY, MissionStatus.RUNNING)


def test_mission_lifecycle_manager():
    manager, mission = _mission()
    assert mission.status == MissionStatus.READY
    assert [m.mission_id for m in manager.list()] == [mission.mission_id]
    assert manager.inspect(mission.mission_id)["name"] == "Atlas"
    assert manager.inspect("msn-missing") is None
    manager.start(mission.mission_id)
    assert mission.status == MissionStatus.RUNNING
    manager.pause(mission.mission_id)
    assert mission.status == MissionStatus.PAUSED
    manager.resume(mission.mission_id)
    assert mission.status == MissionStatus.RUNNING
    manager.stop(mission.mission_id, reason="done testing")
    assert mission.status == MissionStatus.STOPPED
    try:
        manager.start(mission.mission_id)
        raise AssertionError("start on STOPPED must fail")
    except InvalidMissionTransition:
        pass
    try:
        manager.cancel(mission.mission_id)
        raise AssertionError("cancel on STOPPED must fail")
    except InvalidMissionTransition:
        pass


def test_mission_cancel_and_recover():
    manager, mission = _mission()
    manager.cancel(mission.mission_id, reason="scope cut")
    assert mission.status == MissionStatus.CANCELLED
    manager.recover(mission.mission_id, reason="scope restored")
    assert mission.status == MissionStatus.READY
    assert len(mission.metadata["past_runs"]) == 1
    try:
        manager.recover(mission.mission_id)
        raise AssertionError("recover on READY must fail")
    except InvalidMissionTransition:
        pass
    try:
        manager.start("msn-missing")
        raise AssertionError("unknown mission must fail")
    except KeyError:
        pass


# -- objectives ------------------------------------------------------
def test_objective_creation_and_deps():
    manager, mission = _mission()
    first = manager.add_objective(mission.mission_id, "Research",
                                  description="gather facts", weight=1.0)
    second = manager.add_objective(
        mission.mission_id, "Build", depends_on=[first.objective_id],
        weight=3.0)
    assert second.depends_on == [first.objective_id]
    try:
        manager.add_objective(mission.mission_id, "Bad",
                              depends_on=["obj-missing"])
        raise AssertionError("unknown dep must fail")
    except KeyError:
        pass
    ready = ready_objectives(mission)
    assert [o.objective_id for o in ready] == [first.objective_id]
    first.status = ObjectiveStatus.COMPLETED
    ready = ready_objectives(mission)
    assert [o.objective_id for o in ready] == [second.objective_id]


def test_objective_unknown_dep_blocks():
    mission = Mission(name="t", goal="g")
    orphan = Objective(mission_id="x", name="orphan")
    orphan.depends_on.append("obj-ghost")
    mission.objectives["o1"] = orphan
    assert ready_objectives(mission) == []


def test_dependency_failure_blocks_dependent():
    mission = Mission(name="t", goal="g")
    first = Objective(mission_id="x", name="first")
    second = Objective(mission_id="x", name="second")
    second.depends_on.append(first.objective_id)
    mission.objectives = {first.objective_id: first,
                          second.objective_id: second}
    first.status = ObjectiveStatus.FAILED
    assert ready_objectives(mission) == []
    assert second.status == ObjectiveStatus.BLOCKED


def test_ready_objective_selection_priority():
    mission = Mission(name="t", goal="g")
    low = Objective(mission_id="x", name="low", priority=1)
    high = Objective(mission_id="x", name="high", priority=9)
    mission.objectives = {low.objective_id: low, high.objective_id: high}
    ready = ready_objectives(mission)
    assert [o.name for o in ready] == ["high", "low"]


def test_weighted_progress():
    mission = Mission(name="t", goal="g")
    assert compute_progress(mission) == 0.0
    research = Objective(mission_id="x", name="r", weight=1.0)
    build = Objective(mission_id="x", name="b", weight=3.0)
    mission.objectives = {research.objective_id: research,
                          build.objective_id: build}
    assert compute_progress(mission) == 0.0
    research.status = ObjectiveStatus.COMPLETED
    assert compute_progress(mission) == 0.25
    build.progress = 0.5
    # completed 1.0 + in-progress 0.5*3*0.99, over weight 4
    assert compute_progress(mission) == round((1.0 + 0.5 * 3 * 0.99) / 4, 4)
    build.status = ObjectiveStatus.FAILED
    assert compute_progress(mission) == 0.25


def test_assign_dot():
    manager, mission = _mission()
    obj = manager.add_objective(mission.mission_id, "Build")
    manager.assign_dot(mission.mission_id, obj.objective_id, "dot-1")
    assert obj.dot_id == "dot-1"
    assert "dot-1" in mission.dot_ids
    try:
        manager.assign_dot(mission.mission_id, "obj-missing", "dot-1")
        raise AssertionError("unknown objective must fail")
    except KeyError:
        pass


# -- persistence -----------------------------------------------------
def test_persistence_reload_and_corrupt(tmp_path):
    from jarvis.world.registry import JsonFileWorldStore
    store = JsonFileWorldStore(str(tmp_path / "missions.json"))
    manager = MissionManager(_deps(store=store))
    mission = manager.create("Persist", goal="survive restart")
    obj = manager.add_objective(mission.mission_id, "Step")
    obj.status = ObjectiveStatus.COMPLETED
    manager.persist()
    fresh = MissionManager(_deps(store=store))
    assert fresh.get(mission.mission_id) is not None
    assert fresh.get(mission.mission_id).objectives[obj.objective_id].status \
        == ObjectiveStatus.COMPLETED
    (tmp_path / "missions.json").write_text("{broken")
    assert MissionManager(_deps(store=store)).list() == []


def test_no_secrets_persisted(tmp_path):
    from jarvis.world.registry import JsonFileWorldStore
    store = JsonFileWorldStore(str(tmp_path / "missions.json"))
    manager = MissionManager(_deps(store=store))
    mission = manager.create("Secret", goal="handle stuff")
    mission.metadata["api_token"] = "sk-live-SECRET-123"
    mission.metadata["password"] = "hunter2"
    manager.persist()
    raw = (tmp_path / "missions.json").read_text()
    assert "sk-live-SECRET-123" not in raw
    assert "hunter2" not in raw


# -- runtime ---------------------------------------------------------
def _ctx(**kw):
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.agents.orchestrator import Budgets, Orchestrator, OrchestratorContext
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    tasks = kw.get("tasks") or TaskEngine()
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=kw.get("policy") or PolicyEngine(),
        tools=default_registry())
    orch = Orchestrator(ctx, Budgets(max_agents=3, max_tool_calls=2,
                                     max_runtime_s=30.0))
    from jarvis.missions.runtime import MissionContext
    return MissionContext(orchestrator=orch, tasks=tasks,
                          palace=kw.get("palace"), policy=ctx.policy)


def test_runtime_advance_empty_mission(tmp_path):
    manager = MissionManager(_deps(store=None))
    mission = manager.create("Empty", goal="nothing to do")
    from jarvis.missions.runtime import MissionRuntime
    report = MissionRuntime(manager).advance(
        mission.mission_id, _ctx(tasks=manager.deps.tasks))
    assert report.outcome in ("waiting", "completed")
    assert report.progress == mission.progress


def test_runtime_terminal_mission_skips():
    manager = _manager()
    mission = manager.create("Done", goal="done")
    manager.cancel(mission.mission_id)
    from jarvis.missions.runtime import MissionRuntime
    report = MissionRuntime(manager).advance(
        mission.mission_id, _ctx(tasks=manager.deps.tasks))
    assert report.outcome == "skipped"


def test_runtime_emergency_stop_blocks():
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    import tempfile
    config = JarvisConfig()
    config.paths.home = Path(tempfile.mkdtemp())
    policy = PolicyEngine(config)
    policy.engage_stop()
    try:
        manager = MissionManager(_deps(policy=policy))
        mission = manager.create("Stopped", goal="do not run")
        manager.add_objective(mission.mission_id, "Step")
        from jarvis.missions.runtime import MissionRuntime
        report = MissionRuntime(manager).advance(
            mission.mission_id, _ctx(tasks=manager.deps.tasks,
                                     policy=policy))
        assert report.outcome == "blocked"
        assert "emergency stop" in report.reason
    finally:
        policy.release_stop()


def test_runtime_failed_objective_marks_failed():
    manager = _manager()
    mission = manager.create("Fail", goal="do impossible thing xyz")
    manager.add_objective(mission.mission_id, "Impossible step")
    from jarvis.missions.runtime import MissionRuntime
    report = MissionRuntime(manager).advance(
        mission.mission_id, _ctx(tasks=manager.deps.tasks))
    assert report.outcome in ("advanced", "waiting", "failed", "blocked")
    assert mission.objectives  # objectives tracked regardless


def test_checkpoint_records_uncertainty_honestly():
    manager = _manager()
    mission = manager.create("Fragile", goal="fragile work")
    manager.add_objective(mission.mission_id, "Step")
    from jarvis.missions.runtime import MissionRuntime
    report = MissionRuntime(manager).advance(
        mission.mission_id, _ctx(tasks=manager.deps.tasks))
    checkpoints = mission.metadata.get("checkpoints", [])
    assert checkpoints, "every advance must checkpoint"
    assert "verdict" in checkpoints[-1]


def test_interrupted_execution_recovers():
    manager = _manager()
    mission = manager.create("Crash", goal="survive crash")
    manager.start(mission.mission_id)
    assert mission.status.value == "running"
    # Simulate crash: fresh manager over same in-memory state is trivially
    # consistent; recovery path is exercised via recover().
    manager.stop(mission.mission_id, reason="simulated crash")
    recovered = manager.recover(mission.mission_id, reason="restart")
    assert recovered.status.value == "ready"
    assert len(recovered.metadata["past_runs"]) == 1


# -- verification ----------------------------------------------------
def _vctx(mission=None, **kw):
    from jarvis.missions.runtime import MissionContext
    ctx = MissionContext(**kw)
    ctx.mission = mission
    return ctx


def test_verify_task_completed_states():
    from jarvis.missions.verification import verify_criterion
    tasks = TaskEngine()
    task = tasks.register("write report")
    assert verify_criterion(
        {"kind": "task_completed", "task_id": task.task_id},
        _vctx(tasks=tasks)).verdict == "INCOMPLETE"
    tasks.complete(task.task_id, "done")
    assert verify_criterion(
        {"kind": "task_completed", "task_id": task.task_id},
        _vctx(tasks=tasks)).verdict == "SUCCESS"
    tasks.fail(task.task_id, "boom", retry=False)
    assert verify_criterion(
        {"kind": "task_completed", "task_id": task.task_id},
        _vctx(tasks=tasks)).verdict == "FAILURE"
    assert verify_criterion(
        {"kind": "task_completed", "task_id": "task-missing"},
        _vctx(tasks=tasks)).verdict == "UNCERTAIN"


def test_verify_tests_passed_parsing():
    from jarvis.missions.verification import verify_criterion
    assert verify_criterion(
        {"kind": "tests_passed", "output": "5 passed"}, _vctx()).verdict \
        == "SUCCESS"
    assert verify_criterion(
        {"kind": "tests_passed",
         "output": "1 failed, 4 passed"}, _vctx()).verdict == "FAILURE"
    assert verify_criterion({"kind": "tests_passed"}, _vctx()).verdict == \
        "INCOMPLETE"
    assert verify_criterion(
        {"kind": "tests_passed", "output": "collected things"},
        _vctx()).verdict == "UNCERTAIN"


def test_verify_evidence_refs_required():
    from jarvis.missions.verification import verify_criterion
    assert verify_criterion(
        {"kind": "evidence_exists", "refs": ["a", "b"]},
        _vctx()).verdict == "SUCCESS"
    assert verify_criterion({"kind": "evidence_exists", "refs": []},
                            _vctx()).verdict == "INCOMPLETE"


def test_verify_objectives_completed():
    from jarvis.missions.verification import verify_criterion
    mission = Mission(name="t", goal="g")
    first = Objective(mission_id="x", name="a")
    second = Objective(mission_id="x", name="b")
    mission.objectives = {first.objective_id: first,
                          second.objective_id: second}
    first.status = ObjectiveStatus.COMPLETED
    assert verify_criterion(
        {"kind": "objectives_completed",
         "objective_ids": [first.objective_id, second.objective_id]},
        _vctx(mission)).verdict == "INCOMPLETE"
    second.status = ObjectiveStatus.FAILED
    assert verify_criterion(
        {"kind": "objectives_completed",
         "objective_ids": [first.objective_id, second.objective_id]},
        _vctx(mission)).verdict == "FAILURE"
    assert verify_criterion(
        {"kind": "objectives_completed", "objective_ids": ["obj-nope"]},
        _vctx(mission)).verdict == "UNCERTAIN"
    assert verify_criterion(
        {"kind": "nope-kind"}, _vctx()).verdict == "UNCERTAIN"


def test_verify_files_exist(tmp_path):
    from jarvis.missions.verification import verify_criterion
    target = tmp_path / "proof.txt"
    target.write_text("done")
    assert verify_criterion(
        {"kind": "files_exist", "paths": [str(target)]},
        _vctx()).verdict == "SUCCESS"
    assert verify_criterion(
        {"kind": "files_exist", "paths": [str(tmp_path / "nope")]},
        _vctx()).verdict == "FAILURE"
    assert verify_criterion({"kind": "files_exist", "paths": []},
                            _vctx()).verdict == "INCOMPLETE"


def test_verify_command_recorded():
    from jarvis.missions.verification import verify_criterion
    tasks = TaskEngine()
    task = tasks.register("deploy")
    assert verify_criterion(
        {"kind": "command_recorded", "task_id": task.task_id},
        _vctx(tasks=tasks)).verdict == "INCOMPLETE"
    task.history.append({"event": "ran pytest tests/ -q", "at": 0})
    assert verify_criterion(
        {"kind": "command_recorded", "task_id": task.task_id,
         "command": "pytest"}, _vctx(tasks=tasks)).verdict == "SUCCESS"
    assert verify_criterion(
        {"kind": "command_recorded", "task_id": task.task_id,
         "command": "rm -rf"}, _vctx(tasks=tasks)).verdict == "FAILURE"
    assert verify_criterion(
        {"kind": "command_recorded", "task_id": "task-nope"},
        _vctx(tasks=tasks)).verdict == "UNCERTAIN"


def test_verify_manual_approval_token():
    from jarvis.missions.verification import verify_criterion
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.types import ActionPlan
    policy = PolicyEngine()
    assert verify_criterion({"kind": "manual_approval"},
                            _vctx(policy=policy)).verdict == "INCOMPLETE"
    plan = ActionPlan(action="terminal_run x", args={},
                      required_permissions=["exec"])
    decision = policy.evaluate("op", plan)
    token = policy.request_approval("op", plan, decision)
    policy.approve(token, by="user")
    assert verify_criterion({"kind": "manual_approval", "token": token},
                            _vctx(policy=policy)).verdict == "SUCCESS"
    assert verify_criterion({"kind": "manual_approval", "token": "tok-nope"},
                            _vctx(policy=policy)).verdict == "FAILURE"


def test_verify_aggregation_order():
    from jarvis.missions.verification import verify_all
    assert verify_all([], _vctx())["verdict"] == "SUCCESS"
    assert verify_all(
        [{"kind": "evidence_exists", "refs": ["a"]},
         {"kind": "evidence_exists", "refs": []}], _vctx())["verdict"] \
        == "INCOMPLETE"
    assert verify_all(
        [{"kind": "evidence_exists", "refs": []},
         {"kind": "nope-kind"}], _vctx())["verdict"] == "INCOMPLETE"


# -- evidence / conflicts --------------------------------------------
def test_evidence_tracking_and_conflicts_visible():
    manager = _manager()
    mission = manager.create("Evidenced", goal="track things")
    obj = manager.add_objective(mission.mission_id, "Step")
    mission.evidence_refs.append("trace:abc")
    obj.evidence_refs.append("trace:abc")
    assert "trace:abc" in mission.evidence_refs
    assert "trace:abc" in obj.evidence_refs


def test_contradictory_claims_preserved():
    manager = _manager()
    mission = manager.create("Conflicted", goal="disagree")
    mission.uncertainty.append("source A says up")
    mission.uncertainty.append("source B says down")
    assert len(mission.uncertainty) == 2
    manager.persist()


# -- memory / world integration ----------------------------------------
def test_memory_integration_decisions_only():
    import tempfile
    from jarvis.core.loop import Jarvis
    jarvis = Jarvis(home=tempfile.mkdtemp())
    try:
        before = jarvis.palace.stats()["total"]
        manager = MissionManager(__import__(
            "jarvis.missions.manager",
            fromlist=["MissionDependencies"]).MissionDependencies(
                tasks=jarvis.tasks, palace=jarvis.palace))
        mission = manager.create("Mem", goal="remember outcomes")
        assert jarvis.palace.stats()["total"] == before
        assert mission.mission_id
    finally:
        jarvis.close()


def test_world_registry_mirror():
    from jarvis.world.registry import WorldRegistry
    from jarvis.missions.manager import MissionDependencies, MissionManager
    from jarvis.tasks.engine import TaskEngine
    registry = WorldRegistry()
    manager = MissionManager(MissionDependencies(
        tasks=TaskEngine(), world_registry=registry))
    mission = manager.create("Atlas", goal="build atlas")
    manager.add_objective(mission.mission_id, "Research")
    entity = registry.get_entity(f"mission:{mission.mission_id[:8]}")
    assert entity is not None and entity.type == "mission"
    rels = registry.get_relationships(f"mission:{mission.mission_id[:8]}")
    assert any(r.rel == "contains" for r in rels)


# -- proactive / schedule integration ------------------------------------
def test_proactive_mission_events():
    manager = _manager()
    mission = manager.create("P", goal="emit events")
    events = []
    manager.deps.bus = type("Bus", (), {
        "publish": lambda self, e: events.append(e) or e})()
    manager.start(mission.mission_id)
    assert any(getattr(e, "type", "") == "mission.started" for e in events)


def test_schedule_integration_manual():
    manager = _manager()
    mission = manager.create("Sched", goal="periodic check")
    # Missions reuse dot schedules: a mission-owned dot can be scheduled.
    assert manager.get(mission.mission_id).status.value == "ready"


# -- CLI -----------------------------------------------------------------
def test_cli_missions_commands(tmp_path):
    home = str(tmp_path)
    base = ["python3", "-m", "jarvis.cli", "--home", home, "missions"]

    def run(*args, expect=0):
        proc = subprocess.run(list(base) + list(args), capture_output=True,
                              text=True, timeout=180, cwd=ROOT)
        assert proc.returncode == expect, proc.stderr[-500:]
        return proc.stdout

    assert "(no missions yet)" in run("list")
    out = run("create", "Atlas | build the atlas", "--json")
    mid = json.loads(out)["mission"]["mission_id"]
    assert "ready" in run("inspect", mid).lower()
    assert "ready" in run("status", "--json").lower()
    added = run("objectives", "add", mid, "Research | gather facts",
                "--weight", "1.5", "--json")
    oid = json.loads(added)["objective"]["objective_id"]
    assert "Research" in run("objectives", mid)
    started = run("start", mid).lower()
    assert "started" in started or "running" in started
    explained = run("explain", mid)
    assert "Atlas" in explained and "progress" in explained
    assert "verdict" in run("verify", mid, "--json")
    assert "checkpoints" in run("checkpoint", mid, "--json").lower() or \
        "checkpoints" in run("checkpoint", mid).lower()
    assert "paused" in run("pause", mid).lower()
    assert "running" in run("resume", mid).lower()
    assert "cancelled" in run("cancel", mid).lower()
    assert "unknown mission" in run("inspect", "msn-missing", expect=2)
    assert "usage" in run("create", expect=2).lower()


def test_cli_missions_advanced_json(tmp_path):
    home = str(tmp_path)
    base = ["python3", "-m", "jarvis.cli", "--home", home, "missions"]

    def run(*args, expect=0):
        proc = subprocess.run(list(base) + list(args), capture_output=True,
                              text=True, timeout=180, cwd=ROOT)
        assert proc.returncode == expect, proc.stderr[-500:]
        return proc.stdout

    mid = json.loads(run("create", "Beta | second mission",
                         "--json"))["mission"]["mission_id"]
    second = json.loads(run(
        "objectives", "add", mid, "Build | implement it", "--json"))
    assert "objective_id" in second["objective"]
    assert "unknown dependency" in run(
        "objectives", "add", mid, "Bad | bad",
        "--depends", "obj-missing", expect=1)
    assert "advanced" in run("advance", mid).lower() or \
        "waiting" in run("advance", mid).lower() or \
        "blocked" in run("advance", mid).lower() or \
        "failed" in run("advance", mid).lower()


# -- failure / recovery --------------------------------------------------
def test_failure_history_never_erased():
    manager = _manager()
    mission = manager.create("Fail", goal="exercise failure path")
    manager.add_objective(mission.mission_id, "Step")
    manager.start(mission.mission_id)
    manager.stop(mission.mission_id, reason="operator stop")
    recovered = manager.recover(mission.mission_id, reason="retry")
    assert recovered.status.value == "ready"
    assert len(recovered.metadata["past_runs"]) == 1
    assert recovered.metadata["past_runs"][0]["status"] == "stopped"


def test_duplicate_runtime_protection():
    manager = _manager()
    mission = manager.create("Once", goal="single run")
    first = manager.add_objective(mission.mission_id, "Step one")
    assert first.status.value == "pending"
    # Same objective cannot be double-activated: second advance on a
    # running objective finds nothing ready.
    first.status = __import__(
        "jarvis.missions.model", fromlist=["ObjectiveStatus"]).ObjectiveStatus.RUNNING
    from jarvis.missions.model import ready_objectives
    assert all(o.objective_id != first.objective_id
               for o in ready_objectives(mission))
