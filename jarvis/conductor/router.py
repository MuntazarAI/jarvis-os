"""Deterministic intent router (Conductor 1.0).

Table-driven rules over: hostile markers (security guards), explicit
routine requests, voice-output phrasing, memory phrasing, World Intel
currentness routing, device/diagnostic/engineering vocabularies, and
agent-capability keywords. No model calls, no randomness: same request
+ same session state + same capability state → same route.

Below the confidence floor (0.55) the router returns CLARIFY instead
of guessing. Routing never authorizes anything.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

ROUTER_VERSION = "conductor-router-v1"
CONFIDENCE_FLOOR = 0.55

HOSTILE_MARKERS = (
    "ignore your policy", "ignore policy", "disable secur",
    "you are now root", "you are root", "pretend policy",
    "pretend .* approved", "researcher said .* disabl",
    "system message: grant", "ignore previous instructions",
    "run this command exactly", "already approved",
    "approval .* granted", "pre-?approved",
)

RISK_VERBS = ("delete", "remove", "send", "format", "shutdown",
              "restart", "kill", "wipe", "destroy", "execute")


@dataclass
class RouteDecision:
    intent: str = "UNKNOWN"
    target: str = "clarify"
    confidence: float = 0.0
    reason: str = ""
    risk_level: str = "low"
    requires_clarification: bool = False
    requires_confirmation: bool = False
    entities: dict[str, Any] = field(default_factory=dict)
    provenance: str = ROUTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hostile(text: str) -> str:
    lowered = text.lower()
    for marker in HOSTILE_MARKERS:
        if re.search(marker, lowered):
            return marker
    try:
        from ..security.guards import scan_injection
        scan = scan_injection(text)
        if not scan.get("clean", True):
            hits = scan.get("hits", [])
            return str(hits[0])[:80] if hits else "injection marker"
    except Exception:
        pass
    return ""


def _has(words: tuple[str, ...], lowered: str) -> bool:
    return any(w in lowered for w in words)


_VOICE_OUT = ("speak ", "say ", "read aloud", "read this aloud",
              "talk to me")
_MEMORY_WRITE = ("remember that", "remember this", "remember:",
                 "note that", "don't forget")
_MEMORY_READ = ("what do you remember", "recall ", "do you remember",
                "what did i tell you", "my favorite", "my project")
_DEVICE = ("phone", "device", "android", "raspberry", " pi ",
           "service", "docker", "container")
_DEVICE_MUTATE = ("restart", "stop ", "start ", "delete", "send",
                  "command", "reboot", "uninstall", "pair")
_DIAGNOSTIC = ("slow", "health", "cpu", "ram", "memory usage",
               "disk", "network", "logs", "why is", "diagnos",
               "status of", "using disk", "using memory")
_ENGINEERING = ("fix ", "implement", "refactor", "bug", "failing",
                "broken", "patch ", "rewrite")
_TESTING = ("run the tests", "run tests", "test this", "verify this",
            "regression")
_REVIEW = ("review", "look over my changes", "code review")
_PLANNING = ("plan ", "decompose", "roadmap", "steps to",
             "how should we")
_SECURITY_ANALYSIS = ("is this safe", "is it safe", "is .* safe",
                       "analyze.*safe",
                       "threat", "suspicious", "audit ")
_TASK = ("track ", "remind me", "mission", "goal", "todo",
         "add a task")


def route(text: str, *, session_context: str = "",
          capabilities: tuple[str, ...] = ()) -> RouteDecision:
    """Classify one request. Pure function (no I/O except guards)."""
    raw = (text or "").strip()
    if not raw:
        return RouteDecision(intent="EMPTY", target="clarify",
                             confidence=1.0, reason="empty request",
                             risk_level="low",
                             requires_clarification=True)
    lowered = raw.lower()
    words = set(re.findall(r"[a-z0-9]+", lowered))

    hostile = _hostile(raw)
    if hostile:
        return RouteDecision(
            intent="SECURITY", target="security",
            confidence=0.95, reason=f"hostile marker: {hostile}",
            risk_level="high", requires_confirmation=True)

    if lowered in ("help", "?") or lowered.startswith("help "):
        return RouteDecision(intent="HELP", target="help",
                             confidence=0.95, reason="help request",
                             risk_level="low")
    if lowered in ("status", "health") or lowered == "how are you":
        return RouteDecision(intent="STATUS", target="status",
                             confidence=0.9, reason="status request",
                             risk_level="low")

    if _has(_VOICE_OUT, lowered) and len(raw) > 8:
        return RouteDecision(intent="VOICE_OUTPUT", target="voice",
                             confidence=0.85,
                             reason="explicit speech request",
                             risk_level="low")

    if _has(_MEMORY_WRITE, lowered):
        remainder = re.sub(r".*?(remember that|remember this|remember:"
                           r"|note that|don't forget)\s*", "", lowered
                           ).strip()
        if len(remainder) < 3:
            return RouteDecision(
                intent="MEMORY_WRITE", target="memory",
                confidence=0.9, reason="memory write without content",
                risk_level="low", requires_clarification=True)
        return RouteDecision(intent="MEMORY_WRITE", target="memory",
                             confidence=0.9, reason="memory write",
                             risk_level="low",
                             entities={"content": raw})

    if _has(_MEMORY_READ, lowered):
        return RouteDecision(intent="MEMORY_READ", target="memory",
                             confidence=0.85, reason="memory query",
                             risk_level="low")

    if _has(_DEVICE, lowered):
        mutating = _has(_DEVICE_MUTATE, lowered)
        return RouteDecision(
            intent="DEVICE_ACTION" if mutating else "DEVICE_READ",
            target="device", confidence=0.8,
            reason="device vocabulary",
            risk_level="high" if mutating else "low",
            requires_confirmation=mutating)

    if _has(_DIAGNOSTIC, lowered):
        return RouteDecision(intent="DIAGNOSTIC", target="diagnostic",
                             confidence=0.8, reason="diagnostic wording",
                             risk_level="low")

    if _has(_PLANNING, lowered):
        return RouteDecision(intent="PLANNING", target="agents",
                             confidence=0.8, reason="planning wording",
                             risk_level="low")

    if _has(_TESTING, lowered):
        return RouteDecision(intent="TESTING", target="agents",
                             confidence=0.85, reason="testing request",
                             risk_level="low",
                             entities={"team": "coding"})

    if _has(_REVIEW, lowered):
        return RouteDecision(intent="CODE_REVIEW", target="agents",
                             confidence=0.85, reason="review request",
                             risk_level="low")

    if _has(_ENGINEERING, lowered):
        if "failing" in lowered or "fail" in lowered or \
                "bug" in lowered:
            return RouteDecision(
                intent="DEBUGGING", target="agents", confidence=0.8,
                reason="failure wording", risk_level="low",
                entities={"team": "debugging"})
        return RouteDecision(intent="SOFTWARE_ENGINEERING",
                             target="agents", confidence=0.75,
                             reason="engineering wording",
                             risk_level="medium")

    if any(re.search(pattern, lowered)
           for pattern in _SECURITY_ANALYSIS):
        return RouteDecision(intent="SECURITY_ANALYSIS", target="agents",
                             confidence=0.8, reason="safety question",
                             risk_level="low")

    if _has(_TASK, lowered):
        return RouteDecision(intent="TASK", target="tasks",
                             confidence=0.75, reason="task wording",
                             risk_level="low")

    # World Intel currentness routing (existing infrastructure).
    try:
        from ..worldintel.routing import route as currentness
        routed = currentness(raw)
        mapping = {"CURRENT": ("WORLD_CURRENT", 0.8),
                   "HISTORICAL": ("WORLD_CURRENT", 0.75),
                   "RESEARCH": ("RESEARCH", 0.8),
                   "MIXED": ("WORLD_CURRENT", 0.7),
                   "LOCAL": ("WORLD_CURRENT", 0.7)}
        label = routed.get("route", "")
        if label in mapping:
            intent, confidence = mapping[label]
            return RouteDecision(
                intent=intent, target="world", confidence=confidence,
                reason="currentness: "
                + "; ".join(routed.get("reasons", [])),
                risk_level="low")
    except Exception:
        pass

    # Pronoun follow-ups resolve only with session context.
    if session_context and (
            lowered.startswith(("and ", "now ", "then ")) or
            any(p in words for p in ("it", "that", "those", "them"))):
        return RouteDecision(intent="FOLLOW_UP", target="cycle",
                             confidence=0.6,
                             reason="session-context follow-up",
                             risk_level="low")

    # Short ambiguous destructive requests: never guess.
    if any(v in lowered for v in RISK_VERBS) and len(words) < 6:
        return RouteDecision(intent="AMBIGUOUS", target="clarify",
                             confidence=0.9,
                             reason="ambiguous high-risk request",
                             risk_level="high",
                             requires_clarification=True)

    # Greetings need no routing object: say hello back via the cycle.
    # Single greeting word, or greeting + max one extra word ("hi jarvis").
    if len(words) <= 2 and re.match(
            r"(hi+|hello+|hey+|yo|good\s?(morning|evening|"
            r"afternoon)|howdy|greetings)\b", lowered.strip()):
        return RouteDecision(intent="CHAT", target="cycle",
                             confidence=0.95, reason="greeting",
                             risk_level="low")

    if len(words) < 3:
        return RouteDecision(intent="AMBIGUOUS", target="clarify",
                             confidence=0.85,
                             reason="too short to route",
                             risk_level="low",
                             requires_clarification=True)

    # Default: conversational cycle (knowledge/chat handled there).
    return RouteDecision(intent="CHAT", target="cycle", confidence=0.6,
                         reason="default conversational route",
                         risk_level="low")


__all__ = ["RouteDecision", "route", "ROUTER_VERSION",
           "CONFIDENCE_FLOOR"]
