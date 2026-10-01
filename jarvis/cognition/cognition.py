"""Perception, understanding, attention, executive function, reflection."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.types import Modality, Observation, now


# -- perception ----------------------------------------------------------
@dataclass
class Perception:
    observations: list[Observation] = field(default_factory=list)

    def perceive_text(self, text: str, source: str = "user") -> Observation:
        obs = Observation(kind="text", content=text, modality=Modality.TEXT.value,
                          source=source)
        self.observations.append(obs)
        return obs

    def perceive_system(self, content: str, kind: str = "system_state") -> Observation:
        obs = Observation(kind=kind, content=content, modality=Modality.SYSTEM.value,
                          source="system", confidence=0.95)
        self.observations.append(obs)
        return obs

    def perceive_sensor(self, sensor: str, reading: str, confidence: float = 0.75) -> Observation:
        obs = Observation(kind="sensor", content=f"{sensor}: {reading}",
                          modality=Modality.SENSOR.value, source=sensor,
                          confidence=confidence, metadata={"sensor": sensor})
        self.observations.append(obs)
        return obs

    def perceive_document(self, path: str, excerpt: str) -> Observation:
        obs = Observation(kind="document", content=excerpt, modality=Modality.DOCUMENT.value,
                          source="file", metadata={"path": path})
        self.observations.append(obs)
        return obs

    def latest(self, n: int = 10) -> list[Observation]:
        return self.observations[-n:]

    def by_modality(self, modality: str) -> list[Observation]:
        return [o for o in self.observations if o.modality == modality]

    def clear(self) -> None:
        self.observations.clear()


# -- understanding -------------------------------------------------------
INTENT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("question", re.compile(r"\b(what|why|how|when|where|who|which|is|are|can|could|do|does)\b.*\?", re.I)),
    ("command", re.compile(r"^(please\s+)?(run|open|close|start|stop|delete|create|build|show|list|check|deploy|restart|install|search|remember|forget|schedule|calculate|compute|remind|tell|set|write|send|fetch|find)\b", re.I)),
    ("greeting", re.compile(r"^(hi|hey|hello|good\s?(morning|afternoon|evening)|yo)\b", re.I)),
    ("farewell", re.compile(r"^(bye|goodbye|good\s?night|see you)\b", re.I)),
    ("confirmation", re.compile(r"^(yes|yeah|yep|no|nope|cancel|stop)\.?$", re.I)),
]

ENTITY_PATTERNS: dict[str, re.Pattern] = {
    "date": re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|next\s+\w+day|tomorrow|today|yesterday)\b", re.I),
    "time": re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?|\d+\s*(?:seconds?|minutes?|hours?|days?)\s+(?:ago|from now))\b", re.I),
    "path": re.compile(r"(?<![\w/])(~?/(?:[\w.\-]+/)*[\w.\-]+|[\w.\-]+\.(?:py|md|txt|json|yaml|toml|sh))"),
    "number": re.compile(r"\b\d+(?:\.\d+)?\b"),
    "quoted": re.compile(r"[\"“']([^\"”']{1,80})[\"”']"),
}


@dataclass
class Understanding:
    intent: str = "statement"
    intent_confidence: float = 0.5
    entities: dict[str, list[str]] = field(default_factory=dict)
    situation: str = "unknown"
    temporal_refs: list[str] = field(default_factory=list)
    task_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "entities": self.entities,
            "situation": self.situation,
            "temporal_refs": self.temporal_refs,
            "task_hints": self.task_hints,
        }


class Understander:
    """Intent recognition, entity extraction, situation awareness."""

    def understand(self, text: str, context: dict[str, Any] | None = None) -> Understanding:
        context = context or {}
        intent, score = self._intent(text)
        entities = self._entities(text)
        return Understanding(
            intent=intent,
            intent_confidence=score,
            entities=entities,
            situation=self._situation(text, context),
            temporal_refs=entities.get("date", []) + entities.get("time", []),
            task_hints=self._task_hints(text),
        )

    @staticmethod
    def _intent(text: str) -> tuple[str, float]:
        stripped = text.strip()
        for name, pattern in INTENT_PATTERNS:
            if pattern.search(stripped):
                return name, 0.8
        if stripped.endswith("?"):
            return "question", 0.7
        if len(stripped.split()) <= 4 and stripped and stripped[0].isupper():
            return "command", 0.55
        return "statement", 0.5

    @staticmethod
    def _entities(text: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for name, pattern in ENTITY_PATTERNS.items():
            found = pattern.findall(text)
            flat = [f if isinstance(f, str) else f[0] for f in found]
            if flat:
                seen: dict[str, None] = {}
                for item in flat:
                    seen.setdefault(item.strip(), None)
                out[name] = list(seen)
        names = re.findall(r"\b(?:[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*)\b", text)
        if names:
            out["names"] = list(dict.fromkeys(names))
        return out

    @staticmethod
    def _situation(text: str, context: dict[str, Any]) -> str:
        active = str(context.get("active_app", "")).lower()
        low = text.lower()
        if any(w in low for w in ("deploy", "error", "bug", "fix", "test", "code")):
            return "working"
        if any(w in low for w in ("game", "play", "score")):
            return "gaming"
        if any(w in low for w in ("sleep", "tired", "good night")):
            return "resting"
        if "focus" in str(context.get("mode", "")).lower():
            return "focused_work"
        if active:
            return f"using_{active}"
        return "unknown"

    @staticmethod
    def _task_hints(text: str) -> list[str]:
        hints: list[str] = []
        low = text.lower()
        if re.search(r"\b(remind|remember|schedule|later|tomorrow|deadline)\b", low):
            hints.append("scheduling_or_memory")
        if re.search(r"\b(run|execute|deploy|install|delete|restart)\b", low):
            hints.append("system_action")
        if re.search(r"\b(find|search|look up|what is|explain)\b", low):
            hints.append("research")
        if re.search(r"\b(write|create|build|implement|fix)\b.*\b(code|script|function|app)\b", low):
            hints.append("coding")
        return hints


# -- attention -----------------------------------------------------------
@dataclass
class AttentionState:
    focus: str = ""
    budget_used: float = 0.0
    budget_total: float = 1.0
    ignored: list[str] = field(default_factory=list)
    noticed: list[str] = field(default_factory=list)
    focus_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "focus": self.focus,
            "budget_used": round(self.budget_used, 4),
            "ignored": self.ignored,
            "noticed": self.noticed,
            "focus_mode": self.focus_mode,
        }


class AttentionController:
    """Salience/novelty/anomaly-gated attention with a spendable budget."""

    NOVELTY_WORDS = {"error", "failed", "urgent", "alert", "critical", "warning",
                     "deploy", "deadline", "tomorrow", "breaking"}

    def __init__(self, budget: float = 1.0) -> None:
        self.state = AttentionState(budget_total=budget)

    def attend(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Score items by salience; spend budget; return what gets noticed."""
        scored = [(self._salience(i), i) for i in items]
        scored.sort(key=lambda pair: -pair[0])
        noticed: list[dict[str, Any]] = []
        for score, item in scored:
            cost = 1.0 / max(1, len(items))
            if self.state.focus_mode and score < 0.6:
                self.state.ignored.append(str(item.get("id", item)))
                continue
            if self.state.budget_used + cost > self.state.budget_total and score < 0.8:
                self.state.ignored.append(str(item.get("id", item)))
                continue
            self.state.budget_used += cost
            self.state.noticed.append(str(item.get("id", item)))
            noticed.append({**item, "salience": round(score, 4)})
        if noticed:
            self.state.focus = str(noticed[0].get("id", ""))
        return noticed

    def _salience(self, item: dict[str, Any]) -> float:
        text = f"{item.get('title', '')} {item.get('text', '')}".lower()
        score = 0.3
        hits = sum(1 for w in self.NOVELTY_WORDS if w in text)
        score += min(0.4, hits * 0.15)
        score += 0.2 * float(item.get("priority", 0.5))
        if item.get("is_anomaly"):
            score += 0.25
        if item.get("is_novel"):
            score += 0.15
        return min(1.0, score)

    def reset(self, budget: float | None = None) -> None:
        if budget is not None:
            self.state.budget_total = budget
        self.state.budget_used = 0.0
        self.state.ignored.clear()
        self.state.noticed.clear()

    def cognitive_load(self, active_tasks: int, pending_items: int) -> dict[str, Any]:
        load = min(1.0, active_tasks * 0.25 + pending_items * 0.05 + self.state.budget_used * 0.5)
        return {
            "load": round(load, 3),
            "overloaded": load > 0.85,
            "distracted": len(self.state.noticed) > 7,
            "recommendation": "shed load: defer low-salience items"
            if load > 0.85 else "nominal",
        }


# -- executive function --------------------------------------------------
@dataclass
class Goal:
    vision: str
    goal_id: str = ""
    milestones: list[str] = field(default_factory=list)
    progress: float = 0.0
    priority: int = 5
    deadline: float | None = None

    def __post_init__(self) -> None:
        if not self.goal_id:
            from ..core.types import new_id
            self.goal_id = new_id("goal")


class ExecutiveFunction:
    """Goals, Eisenhower priorities, decomposition, scheduling, delegation."""

    def __init__(self) -> None:
        self.goals: dict[str, Goal] = {}
        self.queue: list[dict[str, Any]] = []

    def add_goal(self, vision: str, milestones: list[str] | None = None,
                 priority: int = 5, deadline: float | None = None) -> Goal:
        goal = Goal(vision=vision, milestones=milestones or [],
                    priority=priority, deadline=deadline)
        self.goals[goal.goal_id] = goal
        return goal

    @staticmethod
    def eisenhower(urgent: bool, important: bool) -> str:
        if urgent and important:
            return "do_now"
        if important:
            return "schedule"
        if urgent:
            return "delegate"
        return "drop"

    def prioritize(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rank = {"do_now": 0, "schedule": 1, "delegate": 2, "drop": 3}
        decorated = [
            (rank[self.eisenhower(bool(t.get("urgent")), bool(t.get("important")))],
             -int(t.get("priority", 5)), i, t)
            for i, t in enumerate(tasks)
        ]
        decorated.sort()
        return [t for _, _, _, t in decorated]

    @staticmethod
    def decompose(goal: str) -> list[str]:
        """Break a goal into concrete subtasks using verb templates."""
        low = goal.lower()
        steps: list[str] = []
        if any(w in low for w in ("build", "create", "implement", "website", "app", "tool")):
            steps = [
                f"Define requirements for: {goal}",
                f"Scaffold structure for: {goal}",
                f"Implement core for: {goal}",
                f"Test: {goal}",
                f"Review and finalize: {goal}",
            ]
        elif any(w in low for w in ("learn", "study", "understand")):
            steps = [
                f"Gather materials for: {goal}",
                f"Study fundamentals of: {goal}",
                f"Practice: {goal}",
                f"Verify understanding of: {goal}",
            ]
        elif any(w in low for w in ("fix", "debug", "investigate")):
            steps = [
                f"Reproduce: {goal}",
                f"Isolate cause of: {goal}",
                f"Apply fix for: {goal}",
                f"Verify fix for: {goal}",
            ]
        else:
            steps = [f"Clarify: {goal}", f"Plan: {goal}", f"Execute: {goal}", f"Verify: {goal}"]
        return steps

    def schedule(self, action: str, at: float, repeat: str = "") -> dict[str, Any]:
        entry = {"action": action, "at": at, "repeat": repeat, "created": now()}
        self.queue.append(entry)
        self.queue.sort(key=lambda e: e["at"])
        return entry

    def due(self, at: float | None = None) -> list[dict[str, Any]]:
        stamp = at if at is not None else now()
        ready, self.queue = (
            [e for e in self.queue if e["at"] <= stamp],
            [e for e in self.queue if e["at"] > stamp],
        )
        return ready

    def allocate(self, cpu: float, memory_mb: float, gpu: bool = False) -> dict[str, Any]:
        total_cpu = os.cpu_count() or 4
        return {
            "cpu_share": min(1.0, cpu / total_cpu),
            "memory_mb": memory_mb,
            "gpu": gpu,
            "approved": cpu <= total_cpu and memory_mb <= 8192,
        }


# -- reflection ----------------------------------------------------------
class Reflector:
    """Post-action self-check, failure analysis, lessons."""

    def __init__(self) -> None:
        self.lessons: list[str] = []
        self.reviews: list[dict[str, Any]] = []

    def self_check(self, output: str) -> list[str]:
        issues: list[str] = []
        if not output.strip():
            issues.append("empty output")
        if re.search(r"\b(todo|fixme|placeholder|...)\b", output, re.I):
            issues.append("contains placeholder content")
        if output.count("(") != output.count(")"):
            issues.append("unbalanced parentheses — possible truncation")
        if len(output) > 20000:
            issues.append("output unusually long — consider summarizing")
        return issues

    def verify_result(self, result: Any, expectation: str) -> dict[str, Any]:
        text = str(result)
        matched = expectation.lower() in text.lower() if expectation else True
        return {"matched": matched, "expectation": expectation,
                "preview": text[:200]}

    def analyze_failure(self, action: str, error: str) -> dict[str, Any]:
        low = error.lower()
        if "permission" in low or "denied" in low or "eacces" in low:
            cause, fix = "permission", "request elevated approval or adjust policy"
        elif "not found" in low or "no such" in low:
            cause, fix = "missing_resource", "verify path/name before retry"
        elif "timeout" in low or "timed out" in low:
            cause, fix = "timeout", "retry with longer budget or smaller scope"
        elif "connection" in low or "network" in low:
            cause, fix = "connectivity", "check network state before retry"
        else:
            cause, fix = "unknown", "record context and ask for guidance"
        review = {"action": action, "error": error, "likely_cause": cause,
                  "suggested_fix": fix, "at": now()}
        self.reviews.append(review)
        return review

    def learn(self, lesson: str) -> None:
        if lesson not in self.lessons:
            self.lessons.append(lesson)

    def critique_plan(self, steps: list[str]) -> list[str]:
        notes: list[str] = []
        if len(steps) > 10:
            notes.append("plan is long — consider splitting into phases")
        seen: set[str] = set()
        for step in steps:
            key = step.lower()
            if key in seen:
                notes.append(f"duplicate step: {step}")
            seen.add(key)
        if not any("verif" in s.lower() or "test" in s.lower() for s in steps):
            notes.append("no verification step — add one")
        return notes
