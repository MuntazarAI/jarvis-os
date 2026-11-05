"""Task Evaluation - M35.

Task evaluation framework built on:
- ReasoningEngine (M13) for reasoning traces
- WorldModel (M30) for state comparison
- PersistentMemory (M28) for evaluation storage
- TemporalKnowledge (M29) for temporal evaluation

Provides:
- Success criteria definition and evaluation
- Outcome assessment with confidence scoring
- Feedback collection and learning
- Performance benchmarking
- Evaluation history and trends
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..cognition.reasoning import ReasoningEngine, get_reasoning_engine
from ..memory.persistent import PersistentMemory, get_persistent_memory

if TYPE_CHECKING:
    from ..world.model import WorldModel


@dataclass
class SuccessCriterion:
    """A criterion for evaluating task success."""
    criterion_id: str
    name: str
    description: str
    metric_type: str  # "boolean", "numeric", "text", "boolean_combination"
    target_value: Any
    tolerance: float | None = None
    weight: float = 1.0
    is_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "name": self.name,
            "description": self.description,
            "metric_type": self.metric_type,
            "target_value": self.target_value,
            "tolerance": self.tolerance,
            "weight": self.weight,
            "is_required": self.is_required,
        }


@dataclass
class EvaluationResult:
    """Result of evaluating a task execution."""
    evaluation_id: str
    task_id: str
    task_name: str
    overall_score: float  # 0-1
    passed: bool
    criterion_results: list[dict[str, Any]] = field(default_factory=list)
    feedback: str = ""
    recommendations: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "criterion_results": self.criterion_results,
            "feedback": self.feedback,
            "recommendations": self.recommendations,
            "created_at": self.created_at,
        }


@dataclass
class TaskEvaluation:
    """Complete task evaluation with reasoning trace."""
    evaluation_id: str
    task_id: str
    task_name: str
    objective: str
    actual_outcome: str
    expected_outcome: str
    success: bool
    confidence: float
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reasoning_trace: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "objective": self.objective,
            "actual_outcome": self.actual_outcome,
            "expected_outcome": self.expected_outcome,
            "success": self.success,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "reasoning_trace": self.reasoning_trace,
            "created_at": self.created_at,
        }


class SuccessCriteriaBuilder:
    """Builds success criteria for task evaluation."""

    def __init__(self) -> None:
        self.criteria: dict[str, SuccessCriterion] = {}

    def add_criterion(self, criterion: SuccessCriterion) -> str:
        self.criteria[criterion.criterion_id] = criterion
        return criterion.criterion_id

    def add_boolean_criterion(self,
                              criterion_id: str,
                              name: str,
                              description: str,
                              target_value: bool = True,
                              weight: float = 1.0,
                              is_required: bool = True) -> str:
        """Add a boolean success criterion."""
        criterion = SuccessCriterion(
            criterion_id=criterion_id,
            name=name,
            description=description,
            metric_type="boolean",
            target_value=target_value,
            weight=weight,
            is_required=is_required,
        )
        self.criteria[criterion_id] = criterion
        return criterion_id

    def add_numeric_criterion(self,
                              criterion_id: str,
                              name: str,
                              description: str,
                              target_value: float,
                              tolerance: float | None = None,
                              weight: float = 1.0,
                              is_required: bool = True) -> str:
        """Add a numeric success criterion."""
        criterion = SuccessCriterion(
            criterion_id=criterion_id,
            name=name,
            description=description,
            metric_type="numeric",
            target_value=target_value,
            tolerance=tolerance,
            weight=weight,
            is_required=is_required,
        )
        self.criteria[criterion_id] = criterion
        return criterion_id

    def add_text_criterion(self,
                           criterion_id: str,
                           name: str,
                           description: str,
                           target_value: str,
                           weight: float = 1.0,
                           is_required: bool = True) -> str:
        """Add a text match success criterion."""
        criterion = SuccessCriterion(
            criterion_id=criterion_id,
            name=name,
            description=description,
            metric_type="text",
            target_value=target_value,
            weight=weight,
            is_required=is_required,
        )
        self.criteria[criterion_id] = criterion
        return criterion_id

    def get_criteria(self) -> list[SuccessCriterion]:
        return list(self.criteria.values())

    def clear(self) -> None:
        self.criteria.clear()


class TaskEvaluator:
    """Evaluates task execution against success criteria."""

    def __init__(self) -> None:
        self.builder = SuccessCriteriaBuilder()
        self.evaluations: dict[str, EvaluationResult] = {}
        self.created_at = time.time()
        self.stats = {
            "evaluations_performed": 0,
            "tasks_passed": 0,
            "tasks_failed": 0,
            "average_score": 0.0,
        }

    def evaluate(self,
                 task_id: str,
                 task_name: str,
                 actual_outcome: str,
                 expected_outcome: str,
                 criteria: list[SuccessCriterion] | None = None,
                 metadata: dict[str, Any] | None = None) -> EvaluationResult:
        """Evaluate a task execution against success criteria."""
        evaluation_id = f"eval-{hashlib.sha256(f'{task_id}|{time.time()}'.encode()).hexdigest()[:12]}"

        criteria = criteria or self.builder.get_criteria()
        criterion_results = []
        total_weight = 0.0
        weighted_score = 0.0
        all_required_passed = True

        for criterion in criteria:
            score, passed = self._evaluate_criterion(
                criterion, actual_outcome, expected_outcome
            )
            weight = criterion.weight
            total_weight += weight
            weighted_score += score * weight

            if criterion.is_required and not passed:
                all_required_passed = False

            criterion_results.append({
                "criterion_id": criterion.criterion_id,
                "name": criterion.name,
                "score": score,
                "passed": passed,
                "weight": weight,
                "metric_type": criterion.metric_type,
            })

        overall_score = (weighted_score / total_weight) if total_weight > 0 else 0.0
        passed = overall_score >= 0.5 and all_required_passed

        # Generate feedback
        feedback, recommendations = self._generate_feedback(
            criterion_results, overall_score, passed
        )

        result = EvaluationResult(
            evaluation_id=evaluation_id,
            task_id=task_id,
            task_name=task_name,
            overall_score=round(overall_score, 4),
            passed=passed,
            criterion_results=criterion_results,
            feedback=feedback,
            recommendations=recommendations,
        )

        self.evaluations[evaluation_id] = result
        self.stats["evaluations_performed"] += 1
        if passed:
            self.stats["tasks_passed"] += 1
        else:
            self.stats["tasks_failed"] += 1

        # Update running average
        n = self.stats["evaluations_performed"]
        self.stats["average_score"] = (
            (self.stats["average_score"] * (n - 1) + overall_score) / n
        )

        return result

    def _evaluate_criterion(self,
                            criterion: SuccessCriterion,
                            actual_outcome: str,
                            expected_outcome: str) -> tuple[float, bool]:
        """Evaluate a single criterion against actual and expected outcomes."""
        metric_type = criterion.metric_type
        target_value = criterion.target_value

        if metric_type == "boolean":
            expected_bool = bool(target_value)
            actual_bool = self._parse_boolean(actual_outcome)
            passed = actual_bool == expected_bool
            score = 1.0 if passed else 0.0

        elif metric_type == "numeric":
            expected_val = float(target_value)
            tolerance = criterion.tolerance or 0.0
            actual_val = self._parse_numeric(actual_outcome)
            if actual_val is None:
                score = 0.0
                passed = False
            else:
                diff = abs(actual_val - expected_val)
                if tolerance is not None:
                    passed = diff <= tolerance
                    score = max(0.0, 1.0 - diff / max(abs(expected_val), 1.0))
                else:
                    passed = diff == 0
                    score = 1.0 if passed else 0.0

        elif metric_type == "text":
            expected_text = str(target_value).lower().strip()
            actual_text = actual_outcome.lower().strip()
            if expected_text == actual_text:
                score = 1.0
                passed = True
            elif expected_text in actual_text or actual_text in expected_text:
                score = 0.7
                passed = True
            else:
                score = 0.0
                passed = False

        else:
            score = 0.0
            passed = False

        return score, passed

    def _parse_boolean(self, text: str) -> bool:
        """Parse boolean value from text."""
        lowered = text.lower().strip()
        truthy = {"true", "yes", "1", "success", "completed", "done", "passed"}
        falsy = {"false", "no", "0", "failure", "failed", "error", "not done"}
        if lowered in truthy:
            return True
        if lowered in falsy:
            return False
        return "success" in lowered or "complete" in lowered or "done" in lowered

    def _parse_numeric(self, text: str) -> float | None:
        """Parse numeric value from text."""
        import re
        match = re.search(r"-?\d+\.?\d*", text)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
        return None

    def _generate_feedback(self,
                           criterion_results: list[dict[str, Any]],
                           overall_score: float,
                           passed: bool) -> tuple[str, list[str]]:
        """Generate feedback and recommendations from evaluation results."""
        failed_criteria = [c for c in criterion_results if not c["passed"]]
        passed_criteria = [c for c in criterion_results if c["passed"]]

        if passed:
            feedback = f"Task passed with score {overall_score:.2f}. " \
                       f"{len(passed_criteria)}/{len(criterion_results)} criteria met."
            recommendations = [
                "Maintain current approach",
                "Consider optimizing for efficiency",
            ]
        else:
            feedback = f"Task failed with score {overall_score:.2f}. " \
                       f"{len(failed_criteria)}/{len(criterion_results)} criteria failed."
            recommendations = [
                "Review failed criteria and adjust approach",
                "Focus on required criteria that were not met",
                "Consider breaking task into smaller subtasks",
            ]

        return feedback, recommendations

    def get_evaluation(self, evaluation_id: str) -> EvaluationResult | None:
        return self.evaluations.get(evaluation_id)

    def get_stats(self) -> dict[str, Any]:
        return {
            "evaluations_performed": self.stats["evaluations_performed"],
            "tasks_passed": self.stats["tasks_passed"],
            "tasks_failed": self.stats["tasks_failed"],
            "average_score": round(self.stats["average_score"], 4),
            "pass_rate": (
                self.stats["tasks_passed"] / max(self.stats["evaluations_performed"], 1)
            ),
        }


class TaskReasoningEngine:
    """Combines reasoning engine with task evaluation for evidence-based
    task assessment.

    Uses ReasoningEngine to build reasoning traces about task outcomes,
    and TaskEvaluator to score outcomes against criteria.
    """

    def __init__(self,
                 reasoning_engine: ReasoningEngine | None = None,
                 evaluator: TaskEvaluator | None = None,
                 world_model: WorldModel | None = None,
                 persistent_memory: PersistentMemory | None = None):
        self.reasoning_engine = reasoning_engine or ReasoningEngine()
        self.evaluator = evaluator or TaskEvaluator()
        self.world_model = world_model
        self.pm = persistent_memory or PersistentMemory()
        self.created_at = time.time()
        self.stats = {
            "reasoning_evaluations": 0,
            "successful_evaluations": 0,
            "failed_evaluations": 0,
        }

    def evaluate_task(self,
                      task_id: str,
                      task_name: str,
                      objective: str,
                      actual_outcome: str,
                      expected_outcome: str,
                      criteria: list[SuccessCriterion] | None = None,
                      use_reasoning: bool = True) -> TaskEvaluation:
        """Evaluate a task with reasoning trace.

        Args:
            task_id: Unique task identifier
            task_name: Human-readable task name
            objective: What the task was supposed to achieve
            actual_outcome: What actually happened
            expected_outcome: What was expected to happen
            criteria: Success criteria (uses default if None)
            use_reasoning: Whether to build a reasoning trace

        Returns:
            TaskEvaluation with reasoning trace and evaluation result
        """
        import time as _time
        evaluation_id = f"tev-{hashlib.sha256(f'{task_id}|{_time.time()}'.encode()).hexdigest()[:12]}"

        # Step 1: Run evaluator
        eval_result = self.evaluator.evaluate(
            task_id=task_id,
            task_name=task_name,
            actual_outcome=actual_outcome,
            expected_outcome=expected_outcome,
            criteria=criteria or self.evaluator.builder.get_criteria(),
        )

        # Step 2: Build reasoning chain
        reasoning_steps = []
        chain = self.reasoning_engine.create_chain(
            goal=f"Evaluate task: {task_name}"
        )

        # Step 1: State the claim
        step1 = self.reasoning_engine.add_step(
            chain.chain_id,
            "observation",
            f"Task: {task_name}\nObjective: {objective}\nActual: {actual_outcome}\nExpected: {expected_outcome}",
            confidence=1.0,
        )

        # Step 2: Compare actual vs expected
        step2 = self.reasoning_engine.add_step(
            chain.chain_id,
            "inference",
            f"Comparing actual outcome ({actual_outcome[:100]}...) "
            f"with expected ({expected_outcome[:100]}...)",
            confidence=0.9,
            dependencies=[step1.step_id],
        )

        # Step 3: Apply criteria
        criteria_list = criteria or self.evaluator.builder.get_criteria()
        step3 = self.reasoning_engine.add_step(
            chain.chain_id,
            "verification",
            f"Evaluated against {len(criteria_list)} criteria. "
            f"Score: {eval_result.overall_score:.2f}, "
            f"Passed: {eval_result.passed}",
            confidence=eval_result.overall_score,
            dependencies=[step2.step_id],
        )

        # Step 4: Conclusion
        step4 = self.reasoning_engine.add_step(
            chain.chain_id,
            "conclusion",
            f"Task {'passed' if eval_result.passed else 'failed'} "
            f"with confidence {eval_result.overall_score:.2f}",
            confidence=eval_result.overall_score,
            dependencies=[step3.step_id],
        )

        reasoning_steps = [
            {
                "step_id": s.step_id,
                "step_type": s.step_type,
                "content": s.content,
                "confidence": s.confidence,
            }
            for s in chain.steps
        ]

        # Step 3: Build evidence from criteria
        evidence = []
        for cr in eval_result.criterion_results:
            evidence.append({
                "criterion": cr["name"],
                "score": cr["score"],
                "passed": cr["passed"],
                "metric_type": cr["metric_type"],
            })

        # Store evaluation in persistent memory
        self.pm.store(
            content=f"Task evaluation: {task_name} - {eval_result.feedback}",
            tier="evaluation",
            room="Task Evaluation",
            kind="task_evaluation",
            source="task_evaluator",
            confidence=eval_result.overall_score,
            related_entities=[task_id],
            metadata={
                "evaluation_id": evaluation_id,
                "task_id": task_id,
                "task_name": task_name,
                "success": eval_result.passed,
                "score": eval_result.overall_score,
            },
        )

        result = TaskEvaluation(
            evaluation_id=evaluation_id,
            task_id=task_id,
            task_name=task_name,
            objective=objective,
            actual_outcome=actual_outcome,
            expected_outcome=expected_outcome,
            success=eval_result.passed,
            confidence=eval_result.overall_score,
            evidence=evidence,
            reasoning_trace=reasoning_steps,
        )

        self.stats["reasoning_evaluations"] += 1
        if eval_result.passed:
            self.stats["successful_evaluations"] += 1
        else:
            self.stats["failed_evaluations"] += 1

        return result

    def evaluate_task_with_reasoning(self,
                                     task_id: str,
                                     task_name: str,
                                     objective: str,
                                     actual_outcome: str,
                                     expected_outcome: str,
                                     criteria: list[SuccessCriterion] | None = None) -> TaskEvaluation:
        """Alias for evaluate_task for clarity."""
        return self.evaluate_task(
            task_id=task_id,
            task_name=task_name,
            objective=objective,
            actual_outcome=actual_outcome,
            expected_outcome=expected_outcome,
            criteria=criteria,
            use_reasoning=True,
        )

    def get_evaluation(self, evaluation_id: str) -> EvaluationResult | None:
        return self.evaluator.get_evaluation(evaluation_id)

    def get_stats(self) -> dict[str, Any]:
        return {
            "reasoning_evaluations": self.stats["reasoning_evaluations"],
            "successful_evaluations": self.stats["successful_evaluations"],
            "failed_evaluations": self.stats["failed_evaluations"],
            "evaluator_stats": self.evaluator.get_stats(),
        }


# Global task evaluation instance
_task_evaluator: TaskEvaluator | None = None
_task_reasoning_engine: TaskReasoningEngine | None = None


def get_task_evaluator() -> TaskEvaluator:
    """Get or create the global TaskEvaluator instance."""
    global _task_evaluator
    if _task_evaluator is None:
        _task_evaluator = TaskEvaluator()
    return _task_evaluator


def get_task_reasoning_engine(
    reasoning_engine: ReasoningEngine | None = None,
    evaluator: TaskEvaluator | None = None,
    world_model: WorldModel | None = None,
    persistent_memory: PersistentMemory | None = None,
) -> TaskReasoningEngine:
    """Get or create the global TaskReasoningEngine instance."""
    global _task_reasoning_engine
    if _task_reasoning_engine is None:
        _task_reasoning_engine = TaskReasoningEngine(
            reasoning_engine=reasoning_engine,
            evaluator=evaluator,
            world_model=world_model,
            persistent_memory=persistent_memory,
        )
    return _task_reasoning_engine


__all__ = [
    "SuccessCriterion",
    "EvaluationResult",
    "TaskEvaluation",
    "SuccessCriteriaBuilder",
    "TaskEvaluator",
    "TaskReasoningEngine",
    "get_task_evaluator",
    "get_task_reasoning_engine",
]
