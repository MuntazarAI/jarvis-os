"""Training Infrastructure - M21-M22.

Training loop with:
- Gradient accumulation
- Learning rate scheduling (warmup + cosine decay)
- Checkpointing and recovery
- Evaluation on validation data
- Fine-tuning: SFT, LoRA, QLoRA, DPO, Distillation

Pure Python CPU training (no GPU required).
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
from .finetuning import (
    FineTuningMethod,
    LoRAConfig,
    FineTuningConfig,
    FineTuningResult,
    LoRALayer,
    FineTuningEngine,
)

__all__ = [
    # Pretraining (M21)
    "PretrainingConfig",
    "TrainingStepResult",
    "Checkpoint",
    "SimpleOptimizer",
    "LearningRateScheduler",
    "PretrainingTrainer",
    "create_pretraining_config",
    # Fine-tuning (M22)
    "FineTuningMethod",
    "LoRAConfig",
    "FineTuningConfig",
    "FineTuningResult",
    "LoRALayer",
    "FineTuningEngine",
]
