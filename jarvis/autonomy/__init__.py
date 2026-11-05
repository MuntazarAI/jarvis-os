"""
JARVIS-OS Autonomy Module

Provides autonomous agent loop infrastructure, code execution sandbox,
and system integration capabilities.
"""

from .agent_loop import (
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

from .checkpoint import (
    CheckpointManager,
    CheckpointMetadata,
    LoopRecovery,
    create_checkpoint_manager,
    create_loop_recovery,
)

__all__ = [
    # Agent Loop
    "LoopTask",
    "TaskStatus",
    "TaskPriority",
    "TaskQueue",
    "LoopController",
    "LoopCheckpoint",
    "get_task_queue",
    "get_loop_controller",
    "initialize_autonomous_loop",
    # Checkpoint
    "CheckpointManager",
    "CheckpointMetadata",
    "LoopRecovery",
    "create_checkpoint_manager",
    "create_loop_recovery",
]