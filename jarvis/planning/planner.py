"""MissionPlanner: turns conclusions into typed, policy-gated action proposals.

The planner NEVER executes. It produces ``{"action", "args"}`` dicts that
the IntelligenceLoop submits to PolicyEngine. Execution happens only via
the loop's executor after explicit approval.
"""

from __future__ import annotations

from typing import Any


class MissionPlanner:
    """Deterministic conclusion -> action planner with an explicit registry."""

    def __init__(self) -> None:
        self._rules: list[tuple[str, str, dict[str, Any]]] = []
        self.plans_made = 0

    def register(self, conclusion_contains: str, action: str,
                 args: dict[str, Any] | None = None) -> None:
        """Map a conclusion keyword to a typed action template."""
        if not conclusion_contains or not action:
            raise ValueError("rule needs a keyword and an action")
        self._rules.append((conclusion_contains.lower(), action, dict(args or {})))

    def plan(self, context: dict[str, Any]) -> dict[str, Any]:
        conclusion = context.get("conclusion") or {}
        text = ""
        if isinstance(conclusion, dict):
            text = str(conclusion.get("summary", conclusion.get("decision", ""))).lower()
        else:
            text = str(conclusion).lower()
        for keyword, action, args in self._rules:
            if keyword in text:
                self.plans_made += 1
                return {"action": action, "args": dict(args),
                        "reason": f"matched rule '{keyword}'"}
        self.plans_made += 1
        return {"action": "", "args": {}, "reason": "no rule matched (observe only)"}

    def rules(self) -> list[dict[str, Any]]:
        return [{"keyword": k, "action": a, "args": dict(args)}
                for k, a, args in self._rules]

    def status(self) -> dict[str, Any]:
        return {"rules": len(self._rules), "plans_made": self.plans_made}
