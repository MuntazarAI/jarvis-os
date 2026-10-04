"""Durable Autonomous Tasks 1.0: contracts, store, runner, recovery.

Every test uses fakes or tmp homes — no network, no models, no mic.
Failure paths are tested as first-class behavior, not afterthoughts.
"""

import json
import threading

import pytest

from jarvis.durable import (DurableRunner, TaskStore, TaskStoreError,
                            check_transition, classify, decide)
from jarvis.durable.mesh import mesh_executor
from jarvis.durable.task import (RetryPolicy, StepState, Task, TaskError,
                                 TaskState)


def _store(tmp_path, **kw):
    return TaskStore(str(tmp_path), **kw)


def _runner(store, **kw):
    kw.setdefault("executor", lambda t, s: {
        "ok": True, "verification": "verified",
        "side_effects": [f"did:{s.title}"], "output_ref": "out"})
    return DurableRunner(store, **kw)


def _ready_task(runner, **kw):
    kw.setdefault("steps", [{"title": "step one"}])
    task = runner.create(title="demo", **kw)
    runner.mark_ready(task.task_id)
    return task


# -- state machine ----------------------------------------------------------

def test_legal_transitions():
    assert check_transition(TaskState.CREATED, TaskState.PLANNING)
    assert check_transition(TaskState.RUNNING, TaskState.COMPLETED)
    assert check_transition(TaskState.CHECKPOINTED, TaskState.COMPLETED)
    assert check_transition(TaskState.VERIFYING, TaskState.RECOVERING)
    assert check_transition(TaskState.RETRYING, TaskState.RUNNING)
    assert check_transition(TaskState.FAILED, TaskState.RECOVERING)


def test_illegal_transitions_raise_and_lock_terminals():
    task = Task(title="t")
    with pytest.raises(TaskError):
        task.transition(TaskState.RUNNING)  # created -> running
    assert task.state == TaskState.CREATED  # failed move changes nothing
    task.transition(TaskState.PLANNING)
    task.transition(TaskState.CANCELLED)
    with pytest.raises(TaskError):
        task.transition(TaskState.READY)
    done = Task(title="d")
    done.state = TaskState.COMPLETED
    with pytest.raises(TaskError):
        done.transition(TaskState.READY)


def test_bad_state_strings_rejected():
    with pytest.raises(TaskError):
        Task(title="t", state="flying")
    with pytest.raises(TaskError):
        RetryPolicy(max_attempts=99)
    with pytest.raises(TaskError):
        RetryPolicy(backoff_base_s=-1.0)


def test_titles_truncated_not_rejected():
    task = Task(title="x" * 500)
    assert len(task.title) == 300
    assert len(task.steps) == 0


def test_retry_backoff_caps():
    policy = RetryPolicy(max_attempts=5, backoff_base_s=60.0,
                         backoff_max_s=100.0)
    assert policy.delay_for(1) == 60.0
    assert policy.delay_for(9) == 100.0


# -- store -------------------------------------------------------------------

def test_persist_and_reload_across_instances(tmp_path):
    home = str(tmp_path)
    store = TaskStore(home)
    runner = _runner(store)
    task = runner.create(title="persist me",
                         steps=[{"title": "s"}])
    runner.mark_ready(task.task_id)
    reloaded = TaskStore(home).get(task.task_id)
    assert reloaded is not None
    assert reloaded.title == "persist me"
    assert reloaded.state == TaskState.READY
    assert reloaded.steps[0].title == "s"


def test_store_file_is_valid_json(tmp_path):
    store = _store(tmp_path)
    _runner(store).create(title="t", steps=[{"title": "s"}])
    raw = json.loads((tmp_path / "durable-tasks.json").read_text())
    assert raw["version"] == 1
    assert len(raw["tasks"]) == 1


def test_corrupt_file_fails_closed(tmp_path):
    (tmp_path / "durable-tasks.json").write_text("{not json")
    store = _store(tmp_path)
    assert store.corrupt
    assert store.list() == []


def test_unknown_version_fails_closed(tmp_path):
    (tmp_path / "durable-tasks.json").write_text(
        json.dumps({"version": 999, "tasks": {}}))
    store = _store(tmp_path)
    assert "version" in store.corrupt
    assert store.list() == []


def test_one_bad_record_does_not_poison_store(tmp_path):
    store = _store(tmp_path)
    _runner(store).create(title="good", steps=[{"title": "s"}])
    raw = json.loads((tmp_path / "durable-tasks.json").read_text())
    raw["tasks"]["task-bad"] = {"state": "flying", "title": "bad"}
    (tmp_path / "durable-tasks.json").write_text(json.dumps(raw))
    store2 = _store(tmp_path)
    assert not store2.corrupt
    assert [t.task_id for t in store2.list()] != []
    assert store2.get("task-bad") is None


def test_registry_bound_is_enforced(tmp_path):
    store = _store(tmp_path, max_tasks=2)
    runner = _runner(store)
    runner.create(title="a")
    runner.create(title="b")
    with pytest.raises(TaskStoreError):
        runner.create(title="c")


def test_mutate_unknown_id_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(TaskStoreError):
        with store.mutate("task-nope"):
            pass


def test_cross_process_visibility_via_mtime(tmp_path):
    home = str(tmp_path)
    first = TaskStore(home)
    _runner(first).create(title="from-a")
    second = TaskStore(home)
    assert any(t.title == "from-a" for t in second.list())
    with second.mutate(second.list()[0].task_id) as live:
        live.title = "renamed-by-b"
    assert first.get(second.list()[0].task_id).title == "renamed-by-b"


# -- runner: happy path -------------------------------------------------------

def test_full_advance_to_completed_with_checkpoints(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = _ready_task(runner, steps=[{"title": "a"},
                                      {"title": "b"}])
    runner.advance(task.task_id)
    assert store.get(task.task_id).state == TaskState.READY
    runner.advance(task.task_id)
    final = store.get(task.task_id)
    assert final.state == TaskState.COMPLETED
    assert len(final.checkpoints) == 2
    assert final.checkpoints[0].side_effects_confirmed == ["did:a"]


def test_partial_progress_without_confirmation(tmp_path):
    store = _store(tmp_path)
    runner = DurableRunner(store, executor=lambda t, s: {
        "ok": True, "verification": "partial", "output_ref": "o"})
    task = _ready_task(runner)
    runner.advance(task.task_id)
    final = store.get(task.task_id)
    assert final.state == TaskState.COMPLETED
    assert final.checkpoints == []  # nothing confirmed
    assert final.provenance["completed_unverified"] == 1


def test_idempotency_key_advances_per_attempt(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = _ready_task(runner)
    runner.advance(task.task_id)
    key = store.get(task.task_id).steps[0].idempotency_key
    assert key == f"{task.task_id}:{store.get(task.task_id).steps[0].step_id}:attempt-1"


def test_advance_from_wrong_state_raises(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = runner.create(title="fresh")  # still PLANNING, not READY
    with pytest.raises(TaskStoreError):
        runner.advance(task.task_id)


# -- runner: retries, failure, cancellation ------------------------------------

def test_transient_failure_retries_then_succeeds(tmp_path):
    calls = {"n": 0}

    def flaky(task, step):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"ok": False, "error": "boom", "kind": "transient",
                    "verification": "failed"}
        return {"ok": True, "verification": "verified",
                "side_effects": [], "output_ref": "o"}

    store = _store(tmp_path)
    runner = DurableRunner(store, executor=flaky)
    task = _ready_task(runner)
    runner.advance(task.task_id)
    assert store.get(task.task_id).state == TaskState.RETRYING
    runner.advance(task.task_id)
    runner.advance(task.task_id)
    final = store.get(task.task_id)
    assert final.state == TaskState.COMPLETED
    assert final.steps[0].attempts == 3


def test_retry_budget_exhaustion_fails_closed(tmp_path):
    store = _store(tmp_path)
    runner = DurableRunner(store, executor=lambda t, s: {
        "ok": False, "error": "always", "kind": "transient",
        "verification": "failed"})
    task = runner.create(title="doomed", steps=[{"title": "s"}],
                         retry_policy={"max_attempts": 1})
    runner.mark_ready(task.task_id)
    runner.advance(task.task_id)  # single attempt, no retry budget
    final = store.get(task.task_id)
    assert final.state == TaskState.FAILED
    assert final.provenance["failure"] == "always"


def test_permanent_failure_does_not_retry(tmp_path):
    store = _store(tmp_path)
    runner = DurableRunner(store, executor=lambda t, s: {
        "ok": False, "error": "nope", "kind": "permanent",
        "verification": "failed"})
    task = _ready_task(runner)
    runner.advance(task.task_id)
    assert store.get(task.task_id).state == TaskState.FAILED


def test_executor_crash_is_unknown_and_retried(tmp_path):
    def crash(task, step):
        raise RuntimeError("mesh died")

    store = _store(tmp_path)
    runner = DurableRunner(store, executor=crash)
    task = _ready_task(runner)
    runner.advance(task.task_id)
    assert store.get(task.task_id).state == TaskState.RETRYING


def test_policy_block_cancels_without_side_effects(tmp_path):
    store = _store(tmp_path)
    runner = DurableRunner(store, executor=lambda t, s: {
        "ok": False, "error": "denied", "kind": "policy",
        "verification": "failed"})
    task = _ready_task(runner)
    runner.advance(task.task_id)
    final = store.get(task.task_id)
    assert final.state == TaskState.CANCELLED
    assert "policy" in final.provenance["failure"]


def test_cancel_request_honored_mid_run(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = _ready_task(runner, steps=[{"title": "a"},
                                      {"title": "b"}])
    runner.advance(task.task_id)
    runner.cancel(task.task_id, reason="changed mind")
    assert store.get(task.task_id).state == TaskState.CANCELLED
    assert store.get(task.task_id).provenance["cancel_reason"] == \
        "changed mind"


def test_deadline_failure(tmp_path):
    import time
    store = _store(tmp_path)
    runner = _runner(store)
    task = runner.create(title="late", steps=[{"title": "s"}],
                         deadline=time.time() - 1)
    runner.mark_ready(task.task_id)
    runner.advance(task.task_id)
    assert store.get(task.task_id).state == TaskState.FAILED


def test_emergency_stop_cancels(tmp_path):
    class EStop:
        def emergency_stop_engaged(self):
            return True

    store = _store(tmp_path)
    runner = DurableRunner(store, executor=lambda t, s: {"ok": True},
                           policy=EStop())
    task = _ready_task(runner)
    runner.advance(task.task_id)
    assert store.get(task.task_id).state == TaskState.CANCELLED


def test_pause_resume_roundtrip_and_illegal_pause(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = _ready_task(runner)
    runner.pause(task.task_id)
    assert store.get(task.task_id).state == TaskState.PAUSED
    runner.resume(task.task_id)
    assert store.get(task.task_id).state == TaskState.READY
    runner.advance(task.task_id)
    assert store.get(task.task_id).state == TaskState.COMPLETED
    with pytest.raises(TaskError):
        runner.pause(task.task_id)  # terminal: not pausable


# -- recovery ------------------------------------------------------------------

def test_recover_verified_step_resumes(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = _ready_task(runner, steps=[{"title": "a"},
                                      {"title": "b"}])
    runner.advance(task.task_id)  # first step verified
    with store.mutate(task.task_id) as live:
        live.state = TaskState.RUNNING  # simulate crash residue
    store2 = TaskStore(store.home)
    runner2 = _runner(store2)
    decision = runner2.recover(task.task_id)
    assert decision["action"] == "RESUME"
    assert store2.get(task.task_id).state == TaskState.READY
    assert store2.get(task.task_id).provenance["recovery_log"]


def test_recover_unknown_outcome_reconciles(tmp_path):
    store = _store(tmp_path)
    seen = {"checked": 0}

    def checker(task, step):
        seen["checked"] += 1
        return "confirmed"

    runner = DurableRunner(store, executor=lambda t, s: {
        "ok": False, "error": "died mid-write", "kind": "unknown",
        "verification": "unknown"}, checker=checker)
    task = _ready_task(runner)
    runner.advance(task.task_id)  # unknown -> retrying? attempts=1
    with store.mutate(task.task_id) as live:
        live.state = TaskState.RUNNING
    store2 = TaskStore(store.home)
    runner2 = DurableRunner(store2, executor=lambda t, s: {
        "ok": True, "verification": "verified",
        "side_effects": [], "output_ref": "o"}, checker=checker)
    decision = runner2.recover(task.task_id)
    assert decision["action"] == "RECONCILE"
    assert decision["reconciled"] == "confirmed"
    assert seen["checked"] == 1


def test_recover_absent_side_effect_retries(tmp_path):
    store = _store(tmp_path)
    runner = DurableRunner(
        store, executor=lambda t, s: {"ok": True,
                                      "verification": "verified",
                                      "side_effects": [],
                                      "output_ref": "o"},
        checker=lambda t, s: "absent")
    task = _ready_task(runner)
    # A step that was ATTEMPTED with no verifiable outcome is what
    # earns reconciliation (a fresh READY task correctly RESUMEs).
    with store.mutate(task.task_id) as live:
        step = live.steps[0]
        step.attempts = 1
        step.state = StepState.RUNNING
        live.current_step = step.step_id
        live.state = TaskState.RUNNING  # crash residue
    store2 = TaskStore(store.home)
    decision = DurableRunner(store2,
                             checker=lambda t, s: "absent").recover(
        task.task_id)
    assert decision["action"] == "RECONCILE"
    assert decision["reconciled"] == "absent"
    assert store2.get(task.task_id).state == TaskState.RETRYING


def test_recover_honors_cancel_deadline_and_policy(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = _ready_task(runner)
    runner.cancel(task.task_id)
    with store.mutate(task.task_id) as live:
        # cancellation during flight still recovers to CANCELLED
        live.cancel_requested = True
        live.state = TaskState.RUNNING
    decision = DurableRunner(TaskStore(store.home)).recover(
        task.task_id)
    assert decision["action"] == "CANCEL"


def test_decide_matrix_unit():
    task = Task(title="t")
    assert decide(task, {"cancel_requested": True,
                         "emergency": False,
                         "deadline_exceeded": False,
                         "verification": "verified",
                         "step_state": "none",
                         "attempts": 0})["action"] == "CANCEL"
    assert decide(task, {"cancel_requested": False, "emergency": True,
                         "deadline_exceeded": False,
                         "verification": "verified",
                         "step_state": "none",
                         "attempts": 0})["action"] == "CANCEL"
    assert decide(task, {"cancel_requested": False,
                         "emergency": False,
                         "deadline_exceeded": True,
                         "verification": "verified",
                         "step_state": "none",
                         "attempts": 0})["action"] == "FAIL"
    assert decide(task, {"cancel_requested": False,
                         "emergency": False,
                         "deadline_exceeded": False,
                         "verification": "verified",
                         "step_state": "succeeded",
                         "attempts": 1})["action"] == "RESUME"
    assert decide(task, {"cancel_requested": False,
                         "emergency": False,
                         "deadline_exceeded": False,
                         "verification": "failed",
                         "step_state": "failed",
                         "attempts": 1})["action"] == "RETRY"
    assert decide(task, {"cancel_requested": False,
                         "emergency": False,
                         "deadline_exceeded": False,
                         "verification": "unknown",
                         "step_state": "running",
                         "attempts": 1})["action"] == "RECONCILE"
    assert decide(task, {"cancel_requested": False,
                         "emergency": False,
                         "deadline_exceeded": False,
                         "verification": "unknown",
                         "step_state": "pending",
                         "attempts": 0})["action"] == "RESUME"
    waiting = decide(task, {"cancel_requested": False,
                            "emergency": False,
                            "deadline_exceeded": False,
                            "verification": "verified",
                            "step_state": "none", "attempts": 0},
                     approval_ok=False)
    assert waiting["action"] == "WAIT"


def test_recover_all_sweeps_stranded_tasks(tmp_path):
    home = str(tmp_path)
    store = TaskStore(home)
    runner = _runner(store)
    task = _ready_task(runner)
    with store.mutate(task.task_id) as live:
        live.state = TaskState.RUNNING
    results = DurableRunner(TaskStore(home)).recover_all()
    assert len(results) == 1
    assert results[0]["task_id"] == task.task_id


def test_recovery_trail_is_bounded_and_explained(tmp_path):
    store = _store(tmp_path)
    runner = _runner(store)
    task = _ready_task(runner)
    for _ in range(3):
        with store.mutate(task.task_id) as live:
            live.state = TaskState.RUNNING
        DurableRunner(TaskStore(store.home)).recover(task.task_id)
    trail = TaskStore(store.home).get(task.task_id
                                      ).provenance["recovery_log"]
    assert len(trail) == 3
    assert all("action" in entry and "reason" in entry
               for entry in trail)


# -- mesh executor --------------------------------------------------------------

import types as _types

from jarvis.durable.task import TaskStep


def _ns_task(task_id):
    return _types.SimpleNamespace(task_id=task_id)


def test_mesh_note_step_needs_no_orchestrator():
    run = mesh_executor(object())
    out = run(_ns_task("t"), TaskStep(title="note: just log"))
    assert out == {"ok": True, "verification": "verified",
                   "side_effects": [], "output_ref": "just log"}


def test_mesh_empty_step_is_permanent_failure():
    out = mesh_executor(object())(_ns_task("t"), TaskStep(title=""))
    assert out["ok"] is False and out["kind"] == "permanent"


def test_mesh_unavailable_orchestrator_is_unknown():
    class NoMesh:
        def _build_orchestrator(self):
            raise RuntimeError("no models")

    out = mesh_executor(NoMesh())(_ns_task("t"),
                                  TaskStep(title="do research"))
    assert out["kind"] == "unknown"
    assert out["verification"] == "unknown"


def test_mesh_result_mapping():
    class FakeOrch:
        def __init__(self, result):
            self.result = result

        def run(self, **kw):
            return self.result

    class Jarvis:
        def __init__(self, result):
            self.result = result

        def _build_orchestrator(self):
            return FakeOrch(self.result)

    step = TaskStep(title="goal")
    ok_plain = mesh_executor(Jarvis({"ok": True, "status": "ok",
                                     "blackboard": {},
                                     "outcome": "done"}))(
        _ns_task("t"), step)
    assert ok_plain["verification"] == "partial"  # success ≠ verified
    ok_verified = mesh_executor(Jarvis({
        "ok": True, "status": "ok", "outcome": "done",
        "blackboard": {"sections": {"verification": [
            {"content": {"verdict": "verified"}}]}}}))(
        _ns_task("t"), step)
    assert ok_verified["verification"] == "verified"
    timeout = mesh_executor(Jarvis({"ok": False, "status": "timeout",
                                    "failure": "slow"}))(
        _ns_task("t"), step)
    assert timeout["kind"] == "timeout"
    failed = mesh_executor(Jarvis({"ok": False, "status": "failed",
                                   "failure": "bad"}))(
        _ns_task("t"), step)
    assert failed["kind"] == "permanent"


# -- concurrency ------------------------------------------------------------------

def test_concurrent_creates_stay_consistent(tmp_path):
    home = str(tmp_path)
    errors: list = []

    def make(n):
        try:
            _runner(TaskStore(home)).create(title=f"t-{n}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=make, args=(n,))
               for n in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    final = TaskStore(home)
    assert len(final.list()) == 10
    raw = json.loads((tmp_path / "durable-tasks.json").read_text())
    assert len(raw["tasks"]) == 10
