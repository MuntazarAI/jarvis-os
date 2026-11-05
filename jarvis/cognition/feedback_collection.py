"""Feedback Collection - M37.

Builds on:
- PersistentMemory (jarvis/memory/persistent.py) for feedback storage
- TaskEvaluation (jarvis/cognition/task_evaluation.py) for evaluation data
- TaskReasoningEngine (jarvis/cognition/task_evaluation.py) for reasoning traces

Provides:
- User feedback collection on task results (thumbs up/down, ratings)
- Correction collection for incorrect responses
- Satisfaction tracking over time
- Feedback analytics and trends
- Feedback-driven improvement suggestions
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from ..memory.persistent import PersistentMemory, get_persistent_memory
from ..cognition.task_evaluation import (
    TaskEvaluation,
    TaskReasoningEngine,
    get_task_reasoning_engine,
)


@dataclass
class UserFeedback:
    """User feedback on a task or response."""
    feedback_id: str
    task_id: str
    task_name: str
    user_id: str
    rating: float  # 0-5 scale
    helpful: bool  # thumbs up/down equivalent
    comment: str | None = None
    correction: str | None = None  # user-provided correction
    category: str = "general"  # accuracy, relevance, tone, completeness, etc.
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "user_id": self.user_id,
            "rating": self.rating,
            "helpful": self.helpful,
            "comment": self.comment,
            "correction": self.correction,
            "category": self.category,
            "created_at": self.created_at,
        }


@dataclass
class FeedbackSummary:
    """Aggregated feedback statistics."""
    total_feedback: int
    average_rating: float
    helpful_rate: float  # fraction of helpful ratings
    by_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    recent_feedback: list[dict[str, Any]] = field(default_factory=list)
    common_issues: list[str] = field(default_factory=list)
    improvement_opportunities: list[str] = field(default_factory=list)


class FeedbackCollector:
    """Collects and manages user feedback on JARVIS task performance."""

    def __init__(self, persistent_memory: PersistentMemory | None = None,
                 task_reasoning_engine: TaskReasoningEngine | None = None):
        self.pm = persistent_memory or PersistentMemory()
        self.tre = task_reasoning_engine or TaskReasoningEngine()
        self.feedback: dict[str, UserFeedback] = {}
        self.task_feedback: dict[str, list[str]] = {}  # task_id -> [feedback_ids]
        self.created_at = time.time()
        self.stats = {
            "feedback_collected": 0,
            "feedback_by_category": {},
            "average_rating": 0.0,
        }

    def collect_feedback(self,
                         task_id: str,
                         task_name: str,
                         user_id: str,
                         rating: float,
                         helpful: bool,
                         comment: str | None = None,
                         correction: str | None = None,
                         category: str = "general") -> str:
        """Collect user feedback on a task result.

        Args:
            task_id: Unique task identifier
            task_name: Human-readable task name
            user_id: User identifier
            rating: Rating 0-5
            helpful: Whether the response was helpful
            comment: Optional user comment
            correction: Optional user correction (what the correct answer should be)
            category: Feedback category (accuracy, relevance, tone, completeness, etc.)

        Returns:
            Feedback ID
        """
        feedback_id = f"fb-{hashlib.sha256(f'{task_id}|{user_id}|{time.time()}'.encode()).hexdigest()[:12]}"

        feedback = UserFeedback(
            feedback_id=feedback_id,
            task_id=task_id,
            task_name=task_name,
            user_id=user_id,
            rating=max(0.0, min(5.0, rating)),
            helpful=helpful,
            comment=comment,
            correction=correction,
            category=category,
            created_at=time.time(),
        )

        self.feedback[feedback_id] = feedback

        # Track by task
        if task_id not in self.task_feedback:
            self.task_feedback[task_id] = []
        self.task_feedback[task_id].append(feedback_id)

        # Also store in persistent memory
        self.pm.store(
            content=f"User feedback: {task_name} - rating {rating}/5, helpful={helpful}",
            tier="evaluation",
            room="Feedback",
            kind="feedback",
            source="user",
            origin="user",
            confidence=feedback.rating / 5.0,
            related_entities=[task_id, user_id],
            metadata={
                "feedback_id": feedback_id,
                "task_id": task_id,
                "task_name": task_name,
                "rating": feedback.rating,
                "helpful": feedback.helpful,
                "category": category,
            },
        )

        self.stats["feedback_collected"] += 1
        self.stats["feedback_by_category"][category] = (
            self.stats["feedback_by_category"].get(category, 0) + 1
        )

        # Update average rating
        all_ratings = [f.rating for f in self.feedback.values()]
        self.stats["average_rating"] = sum(all_ratings) / len(all_ratings)

        return feedback_id

    def get_feedback(self, feedback_id: str) -> UserFeedback | None:
        """Get feedback by ID."""
        return self.feedback.get(feedback_id)

    def get_feedback_for_task(self, task_id: str) -> list[UserFeedback]:
        """Get all feedback for a task."""
        feedback_ids = self.task_feedback.get(task_id, [])
        return [self.feedback[fid] for fid in feedback_ids if fid in self.feedback]

    def get_feedback_for_user(self, user_id: str) -> list[UserFeedback]:
        """Get all feedback from a user."""
        return [f for f in self.feedback.values() if f.user_id == user_id]

    def get_feedback_for_category(self, category: str) -> list[UserFeedback]:
        """Get all feedback for a category."""
        return [f for f in self.feedback.values() if f.category == category]

    def get_summary(self) -> FeedbackSummary:
        """Get aggregated feedback statistics."""
        if not self.feedback:
            return FeedbackSummary(
                total_feedback=0,
                average_rating=0.0,
                helpful_rate=0.0,
            )

        total = len(self.feedback)
        avg_rating = sum(f.rating for f in self.feedback.values()) / total
        helpful_count = sum(1 for f in self.feedback.values() if f.helpful)
        helpful_rate = helpful_count / total

        # Group by category
        by_category: dict[str, dict[str, Any]] = {}
        for f in self.feedback.values():
            cat = f.category
            if cat not in by_category:
                by_category[cat] = {"count": 0, "avg_rating": 0.0, "helpful_count": 0}
            by_category[cat]["count"] += 1
            by_category[cat]["avg_rating"] += f.rating
            if f.helpful:
                by_category[cat]["helpful_count"] += 1

        for cat in by_category:
            cat_data = by_category[cat]
            cat_data["avg_rating"] = cat_data["avg_rating"] / cat_data["count"]
            cat_data["helpful_rate"] = cat_data["helpful_count"] / cat_data["count"]

        # Recent feedback
        recent = sorted(self.feedback.values(), key=lambda f: f.created_at, reverse=True)[:10]
        recent_feedback = [f.to_dict() for f in recent]

        # Common issues (low-rated feedback)
        low_rated = [f for f in self.feedback.values() if f.rating <= 2.0]
        common_issues = list(set(f.comment for f in low_rated if f.comment))[:5]

        # Improvement opportunities
        improvement_opportunities = []
        if helpful_rate < 0.8:
            improvement_opportunities.append("Improve response helpfulness")
        low_accuracy = [f for f in self.feedback.values()
                        if f.category == "accuracy" and f.rating <= 3.0]
        if len(low_accuracy) > 2:
            improvement_opportunities.append("Improve response accuracy")
        low_relevance = [f for f in self.feedback.values()
                         if f.category == "relevance" and f.rating <= 3.0]
        if len(low_relevance) > 2:
            improvement_opportunities.append("Improve response relevance")

        return FeedbackSummary(
            total_feedback=total,
            average_rating=round(avg_rating, 2),
            helpful_rate=round(helpful_rate, 2),
            by_category=by_category,
            recent_feedback=recent_feedback,
            common_issues=common_issues,
            improvement_opportunities=improvement_opportunities,
        )

    def get_feedback_stats(self) -> dict[str, Any]:
        """Get feedback statistics as a flat dict."""
        summary = self.get_summary()
        return {
            "total_feedback": summary.total_feedback,
            "average_rating": summary.average_rating,
            "helpful_rate": summary.helpful_rate,
            "by_category": summary.by_category,
            "improvement_opportunities": summary.improvement_opportunities,
        }


# Global feedback collector instance
_feedback_collector: FeedbackCollector | None = None


def get_feedback_collector(
    persistent_memory: PersistentMemory | None = None,
    task_reasoning_engine: TaskReasoningEngine | None = None,
) -> FeedbackCollector:
    """Get or create the global FeedbackCollector instance."""
    global _feedback_collector
    if _feedback_collector is None:
        _feedback_collector = FeedbackCollector(
            persistent_memory=persistent_memory,
            task_reasoning_engine=task_reasoning_engine,
        )
    return _feedback_collector


__all__ = [
    "UserFeedback",
    "FeedbackSummary",
    "FeedbackCollector",
    "get_feedback_collector",
]
