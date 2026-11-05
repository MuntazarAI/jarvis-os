"""Training Infrastructure - M21 Small-Scale Pretraining.

Training loop with:
- Gradient accumulation
- Learning rate scheduling (warmup + cosine decay)
- Checkpointing and recovery
- Evaluation on validation data
- Pure Python CPU training (no GPU required)
"""

from .pretraining import (
    PretrainingConfig,
    TrainingStepResult,
    Checkpoint,
    SimpleOptimizer,
    LearningRateScheduler,
    PretrainingTrainer,
    create_pretraining_config,
)

__all__ = [
    "PretrainingConfig",
    "TrainingStepResult",
    "Checkpoint",
    "SimpleOptimizer",
    "LearningRateScheduler",
    "PretrainingTrainer",
    "create_pretraining_config",
]
