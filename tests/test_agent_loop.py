"""
Tests for Autonomous Agent Loop Infrastructure
"""

import asyncio
import time
import tempfile
import os
import pytest

from jarvis.autonomy.agent_loop import (
    LoopTask,
    TaskStatus,
    TaskPriority,
    TaskQueue,
    LoopController,
    LoopCheckpoint,
    get_task_queue,
    get_loop_controller,
    initialize_autonomous_loop,
)
from jarvis.autonomy.checkpoint import (
    CheckpointManager,
    LoopRecovery,
    create_checkpoint_manager,
    create_loop_recovery,
)


class TestTaskQueue:
    """Test task queue operations."""

    @pytest.fixture
    def queue(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        queue = TaskQueue(db_path)
        yield queue
        os.unlink(db_path)

    def test_enqueue_dequeue(self, queue):
        task = LoopTask(
            task_id="test-1",
            name="Test Task",
            description="Test",
            agent_id="jarvis",
            payload={"action": "test"},
            priority=TaskPriority.HIGH
        )
        queue.enqueue(task)

        dequeued = queue.dequeue(limit=1)
        assert len(dequeued) == 1
        assert dequeued[0].task_id == "test-1"
        assert dequeued[0].status == TaskStatus.RUNNING

    def test_priority_ordering(self, queue):
        # Add tasks with different priorities
        for priority in [TaskPriority.LOW, TaskPriority.NORMAL, TaskPriority.HIGH, TaskPriority.CRITICAL]:
            task = LoopTask(
                task_id=f"task-{priority.value}",
                name=f"Task {priority.name}",
                description="Test",
                agent_id="jarvis",
                payload={},
                priority=priority
            )
            queue.enqueue(task)

        # Should dequeue in priority order
        first = queue.dequeue(limit=1)[0]
        assert first.priority == TaskPriority.CRITICAL

    def test_complete_fail(self, queue):
        task = LoopTask(
            task_id="test-complete",
            name="Complete Test",
            description="Test",
            agent_id="jarvis",
            payload={}
        )
        queue.enqueue(task)
        queue.dequeue(limit=1)

        queue.complete("test-complete", {"result": "success"})
        # Should be removed or marked completed
        stats = queue.get_stats()
        assert stats["completed"] >= 1

    def test_retry_then_dead_letter(self, queue):
        task = LoopTask(
            task_id="test-retry",
            name="Retry Test",
            description="Test",
            agent_id="jarvis",
            payload={},
            max_retries=2
        )
        queue.enqueue(task)

        # Fail twice
        queue.dequeue(limit=1)
        queue.fail("test-retry", "error 1")

        queue.dequeue(limit=1)
        queue.fail("test-retry", "error 2")

        # Third fail should go to dead letter
        queue.dequeue(limit=1)
        queue.fail("test-retry", "error 3")

        stats = queue.get_stats()
        assert stats["dead_letter"] == 1


class TestLoopController:
    """Test loop controller operations."""

    @pytest.fixture
    def queue(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        queue = TaskQueue(db_path)
        yield queue
        os.unlink(db_path)

    @pytest.fixture
    def controller(self, queue):
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = LoopController(queue, checkpoint_dir=tmpdir)
            controller.configure(checkpoint_interval=5, iteration_timeout=5.0)
            yield controller

    @pytest.mark.asyncio
    async def test_start_stop(self, controller):
        # Set minimal callbacks
        async def observe(i): return {"observation": f"obs-{i}"}
        async def plan(i, obs): return {"plan": f"plan-{i}"}
        async def act(i, plan): return {"action": f"act-{i}"}
        async def reflect(i, act): return {"reflection": f"reflect-{i}"}

        controller.set_callbacks(observe, plan, act, reflect)
        controller.configure(max_iterations=3)

        await controller.start()
        await asyncio.sleep(0.5)
        await controller.stop()

        assert controller._completed == 3
        assert controller.iteration == 3

    @pytest.mark.asyncio
    async def test_pause_resume(self, controller):
        iteration_count = 0

        async def observe(i): return {}
        async def plan(i, obs): return {}
        async def act(i, plan):
            nonlocal iteration_count
            iteration_count += 1
            await asyncio.sleep(0.05)
        async def reflect(i, act): return {}

        controller.set_callbacks(observe, plan, act, reflect)
        controller.configure(max_iterations=10, paused_sleep_interval=0.05)

        await controller.start()
        await asyncio.sleep(0.2)
        await controller.pause()
        paused_iteration = controller.iteration
        await asyncio.sleep(0.1)
        await controller.resume()
        await asyncio.sleep(0.3)
        await controller.stop()

        assert controller.iteration > paused_iteration


class TestCheckpoint:
    """Test checkpoint save/load."""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield CheckpointManager(tmpdir, compress=True)

    def test_save_load(self, manager):
        checkpoint = LoopCheckpoint(
            checkpoint_id="test-cp",
            iteration=5,
            timestamp=1234567890.0,
            loop_state={"test": "state"},
            pending_tasks=[],
            running_tasks=[],
            completed_count=10,
            failed_count=1
        )

        path = manager.save(checkpoint, tags=["test"])
        assert os.path.exists(path)

        loaded = manager.load(os.path.basename(path))
        assert loaded is not None
        assert loaded.iteration == 5
        assert loaded.completed_count == 10

    def test_latest_checkpoint(self, manager):
        for i in range(3):
            cp = LoopCheckpoint(
                checkpoint_id=f"cp-{i}",
                iteration=i,
                timestamp=1000.0 + i,
                loop_state={},
                pending_tasks=[],
                running_tasks=[],
                completed_count=i,
                failed_count=0
            )
            manager.save(cp)

        latest = manager.load_latest()
        assert latest is not None
        assert latest.iteration == 2


class TestLoopRecovery:
    """Test crash recovery."""

    @pytest.fixture
    def queue_and_recovery(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = TaskQueue(db_path)
            manager = CheckpointManager(tmpdir)
            recovery = LoopRecovery(queue, manager)
            yield queue, recovery, manager
        os.unlink(db_path)

    def test_recovery_restores_tasks(self, queue_and_recovery):
        queue, recovery, manager = queue_and_recovery

        # Create a checkpoint with pending tasks
        task = LoopTask(
            task_id="recover-1",
            name="Recover Task",
            description="Test",
            agent_id="jarvis",
            payload={"data": "test"},
            status=TaskStatus.RUNNING  # Was running when crashed
        )

        cp = LoopCheckpoint(
            checkpoint_id="recovery-cp",
            iteration=10,
            timestamp=time.time(),
            loop_state={},
            pending_tasks=[task.to_dict()],
            running_tasks=[],
            completed_count=5,
            failed_count=1
        )
        manager.save(cp)

        # Recover
        result = recovery.recover()
        assert result["recovered"] is True
        assert result["restored_tasks"] == 1
        assert result["completed_count"] == 5

        # Task should be back in queue as PENDING
        stats = queue.get_stats()
        assert stats["pending"] == 1


class TestIntegration:
    """Integration tests with real JARVIS components."""

    @pytest.mark.asyncio
    async def test_full_cycle(self):
        """Test full observe-plan-act-reflect cycle with mocked JARVIS."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = TaskQueue(db_path)
            controller = LoopController(queue, checkpoint_dir=tmpdir)

            # Mock JARVIS components
            call_log = []

            async def observe(iteration):
                call_log.append(("observe", iteration))
                return {"world_state": "observed"}

            async def plan(iteration, observation):
                call_log.append(("plan", iteration))
                return {"tasks": ["task1", "task2"]}

            async def act(iteration, plan):
                call_log.append(("act", iteration))
                return {"executed": True}

            async def reflect(iteration, action_result):
                call_log.append(("reflect", iteration))
                return {"improved": True}

            controller.set_callbacks(observe, plan, act, reflect)
            controller.configure(max_iterations=2, checkpoint_interval=1, min_iteration_interval=0.01)

            await controller.start()
            await asyncio.sleep(0.1)  # Give loop time to run iterations
            await controller.stop()

            # Verify all phases called
            assert len(call_log) == 8  # 4 phases × 2 iterations

        os.unlink(db_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])