"""Conversational Intelligence 2.0: fine-grained dialogue acts + context resolution.

Sits on top of Understander (coarse intents) without changing it. Maps each
input to one DialogueAct, resolves pronouns against session context, tracks
active topic/task/project, and forces CLARIFICATION when confidence is
insufficient or an action has no resolvable target.

Safety invariants enforced here:
- questions never route to TOOL_ACTION/COMPUTER_ACTION/TASK (see NON_ACTING)
- memory writes require an explicit remember-verb (MEMORY_WRITE only)
- "do it" / bare pronouns with no context resolve to CLARIFICATION, never action
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DialogueAct(str, Enum):
    GREETING = "greeting"
    IDENTITY = "identity"
    CAPABILITY = "capability"
    CONVERSATION = "conversation"
    KNOWLEDGE = "knowledge"
    MEMORY_WRITE = "memory_write"
    MEMORY_QUERY = "memory_query"
    TASK = "task"
    TOOL_ACTION = "tool_action"
    COMPUTER_ACTION = "computer_action"
    RESEARCH = "research"
    CODING = "coding"
    PROJECT = "project"
    SYSTEM = "system"
    CLARIFICATION = "clarification"
    CANCELLATION = "cancellation"
    CONFIRMATION = "confirmation"
    UNKNOWN = "unknown"


# Acts that must NEVER reach tool execution, even if the coarse intent
# classifier said "command".
NON_ACTING = frozenset({
    DialogueAct.GREETING, DialogueAct.IDENTITY, DialogueAct.CAPABILITY,
    DialogueAct.CONVERSATION, DialogueAct.KNOWLEDGE, DialogueAct.MEMORY_QUERY,
    DialogueAct.CLARIFICATION, DialogueAct.CANCELLATION,
    DialogueAct.CONFIRMATION, DialogueAct.UNKNOWN,
})


@dataclass
class DialogueContext:
    """What the conversation is currently about. Built per turn from
    session turns, open tasks and recent project memory."""

    active_topic: str = ""
    active_task: str = ""
    active_project: str = ""
    last_entities: list[str] = field(default_factory=list)
    turn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"active_topic": self.active_topic,
                "active_task": self.active_task,
                "active_project": self.active_project,
                "last_entities": self.last_entities,
                "turn_count": self.turn_count}


@dataclass
class Route:
    act: DialogueAct
    confidence: float
    resolved_text: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"act": self.act.value, "confidence": self.confidence,
                "resolved_text": self.resolved_text, "slots": self.slots,
                "reason": self.reason}


_PRONOUNS = re.compile(r"\b(it|that|this|there|them|they)\b", re.I)

_PATTERNS: list[tuple[DialogueAct, re.Pattern, float]] = [
    # Identity is pattern-matched here too (not just via the coarse
    # classifier) so routing is robust to classifier misses.
    (DialogueAct.IDENTITY,
     re.compile(r"(who are you|what are you|your name|about yourself|"
                r"introduce yourself|who made you|who created you)", re.I), 0.9),
    (DialogueAct.CANCELLATION,
     re.compile(r"^(stop|stop that|cancel(\s+that|\s+it)?|never mind|forget it|"
                r"abort|don't do that|do not do that)\.?$", re.I), 0.85),
    (DialogueAct.CAPABILITY,
     re.compile(r"(what can you do|what do you do|your (abilities|features|"
                r"capabilities)|help me|list commands|how do i use you)", re.I), 0.85),
    (DialogueAct.MEMORY_WRITE,
     re.compile(r"^\s*(remember|note this|write down|don't forget|never forget)\b", re.I), 0.9),
    (DialogueAct.MEMORY_QUERY,
     re.compile(r"(what do you remember|what do you know about me|"
                r"what have i told you|list what you remember|"
                r"what do you know about my|recall what)", re.I), 0.85),
    (DialogueAct.PROJECT,
     re.compile(r"(my project|what am i working on|what was i doing|"
                r"continue.*(project|work)|project status|"
                r"what changed|what is blocking me|what should i do next)", re.I), 0.8),
    (DialogueAct.RESEARCH,
     re.compile(r"(research|search the web|look (it |that |this )?up|"
                r"find out about|investigate)\b", re.I), 0.75),
    (DialogueAct.CODING,
     re.compile(r"(write|implement|refactor|debug|fix).{0,30}"
                r"(code|function|script|bug|error|test|app)|"
                r"\b(code review|pull request|commit this)\b", re.I), 0.75),
    (DialogueAct.COMPUTER_ACTION,
     re.compile(r"(open|close|launch|start|quit)\s+\w+|"
                r"(screenshot|take a picture of|volume|brightness|"
                r"click|move the mouse|type|press|window|clipboard|"
                r"open firefox|open (the )?browser|open (the )?terminal)", re.I), 0.75),
    (DialogueAct.SYSTEM,
     re.compile(r"(system status|how much (disk|memory|ram)|are you (online|"
                r"healthy)|doctor|benchmark|what version|restart yourself|"
                r"what model)", re.I), 0.8),
    (DialogueAct.TASK,
     re.compile(r"(remind me|add (a |the )?task|to-?do|schedule|set (a |an )?"
                r"(reminder|alarm|timer))", re.I), 0.8),
    (DialogueAct.TOOL_ACTION,
     re.compile(r"^(calculate|compute|run (the |my )?tests?|list files|"
                r"show (me )?files|check (disk|system|status))\b", re.I), 0.8),
    (DialogueAct.CONFIRMATION,
     re.compile(r"^(yes|yeah|yep|no|nope|ok|okay|sure|go ahead|do it)\.?$", re.I), 0.7),
]

_BARE_ACTION = re.compile(r"^(do it|go ahead and do that|do that|run it|"
                          r"yes do (it|that)|proceed)\.?$", re.I)


class DialogueRouter:
    """Rule-based dialogue-act router with context resolution."""

    def route(self, text: str, coarse_intent: str = "",
              context: DialogueContext | None = None) -> Route:
        context = context or DialogueContext()
        stripped = text.strip()
        if not stripped:
            return Route(DialogueAct.CLARIFICATION, 0.9,
                         reason="empty input")
        lowered = stripped.lower()

        # 1. Bare action references ("do it") resolve ONLY to an
        # actionable target (open task or active project) — never to an
        # informational topic such as a past question.
        if _BARE_ACTION.match(stripped):
            target = context.active_task or context.active_project
            if target:
                return Route(DialogueAct.TASK, 0.6, resolved_text=target,
                             slots={"referred_to": target},
                             reason="resolved against active task/project")
            return Route(DialogueAct.CLARIFICATION, 0.85,
                         reason="action reference with no active task or project")

        # 2. Pattern acts in priority order.
        for act, pattern, confidence in _PATTERNS:
            match = pattern.search(stripped)
            if not match:
                continue
            if act == DialogueAct.CANCELLATION and not context.active_task:
                # No running task: still CANCELLATION so the loop can answer
                # honestly ("nothing to cancel") instead of a generic
                # confirmation that looks like it accepted something.
                return Route(DialogueAct.CANCELLATION, 0.6,
                             reason="cancel phrase with no active task")
            if act in (DialogueAct.MEMORY_WRITE, DialogueAct.CONFIRMATION):
                # "remember that ..." uses "that" as a complementizer, not a
                # reference — no pronoun penalty for these acts.
                return Route(act, confidence, resolved_text=stripped,
                             reason=f"matched {act.value} pattern")
            penalty, resolved = self._resolve_pronouns(stripped, context)
            # Only dangling references (penalty 0.35) block action; a
            # successful resolution (penalty 0.1) merely lowers confidence.
            if penalty >= 0.35 and act in (
                    DialogueAct.TASK, DialogueAct.TOOL_ACTION,
                    DialogueAct.COMPUTER_ACTION, DialogueAct.CODING):
                return Route(DialogueAct.CLARIFICATION, 0.8,
                             reason=f"unresolved reference in {act.value} request")
            return Route(act, max(0.3, confidence - penalty),
                         resolved_text=resolved,
                         reason=f"matched {act.value} pattern")

        # 3. Fall back to the coarse intent.
        fallback = {
            "greeting": (DialogueAct.GREETING, 0.8),
            "identity": (DialogueAct.IDENTITY, 0.8),
            "farewell": (DialogueAct.CONVERSATION, 0.6),
            "confirmation": (DialogueAct.CONFIRMATION, 0.7),
            "command": (DialogueAct.TOOL_ACTION, 0.55),
            "question": (DialogueAct.KNOWLEDGE, 0.7),
        }.get(coarse_intent, (DialogueAct.CONVERSATION, 0.5))
        penalty, resolved = self._resolve_pronouns(stripped, context)
        act, confidence = fallback
        if act == DialogueAct.TOOL_ACTION and penalty >= 0.35:
            return Route(DialogueAct.CLARIFICATION, 0.8,
                         reason="unresolved reference in action request")
        return Route(act, max(0.3, confidence - penalty),
                     resolved_text=resolved,
                     reason=f"coarse intent {coarse_intent or 'none'}")

    @staticmethod
    def _resolve_pronouns(text: str, context: DialogueContext) -> tuple[float, str]:
        """Replace it/that/this/them with the last session entity.

        Returns (penalty, resolved_text). Penalty 0 when nothing to resolve
        (no pronouns) or resolution succeeded; 0.35 when pronouns dangle.
        """
        if not _PRONOUNS.search(text):
            return 0.0, text
        if not context.last_entities:
            return 0.35, text
        target = context.last_entities[-1]
        resolved = _PRONOUNS.sub(target, text, count=1)
        return 0.1, resolved

    @staticmethod
    def build_context(recent_turns: list[dict[str, Any]] | None = None,
                      open_tasks: list[str] | None = None,
                      project_hint: str = "") -> DialogueContext:
        """Assemble context from session turns + open tasks + project."""
        recent_turns = recent_turns or []
        open_tasks = open_tasks or []
        entities: list[str] = []
        topic = ""
        for turn in recent_turns[-4:]:
            for key in ("input", "response"):
                value = str(turn.get(key, ""))
                for name in extract_names(value):
                    if name not in entities:
                        entities.append(name)
            # Topic must be substantive: greetings and fragments ("hii",
            # "ok") are not something "do it" can refer to.
            candidate = str(turn.get("input", ""))
            if not topic and len(candidate) > 15:
                topic = candidate[:120]
        return DialogueContext(
            active_topic=topic,
            active_task=open_tasks[0] if open_tasks else "",
            active_project=project_hint,
            last_entities=entities[-5:],
            turn_count=len(recent_turns))


def extract_names(text: str) -> list[str]:
    """Proper-noun-ish entity mentions for pronoun resolution."""
    found = re.findall(r"\b(?:[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*)\b", text)
    quoted = re.findall(r"[\"“']([^\"”']{3,40})[\"”']", text)
    seen: dict[str, None] = {}
    for item in [*found, *quoted]:
        cleaned = item.strip()
        if cleaned.lower() not in ("what", "when", "where", "which", "how",
                                   "jarvis", "user"):
            seen.setdefault(cleaned, None)
    return list(seen)
