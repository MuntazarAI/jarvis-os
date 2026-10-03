"""Simulation boundary + resource budgets (5.0).

Simulation operates ONLY on copied, hypothetical, or historical
state. It has no reference to transports, devices, cameras,
microphones, tools, or the network — structurally impossible to
escape by construction (it receives dicts, never live objects).

Budgets bound every cognitive cycle: time, steps, observations,
tools, retries, replans, retrieval, simulation. Exhaustion returns
a structured partial/timeout result; nothing hangs.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


class SimulationError(ValueError):
    """Simulation misuse (live objects, oversized state)."""


def _utcnow() -> float:
    return time.time()


@dataclass
class Simulation:
    simulation_id: str = ""
    question: str = ""
    base_state: dict[str, Any] = field(default_factory=dict)
    hypothetical_change: dict[str, Any] = field(default_factory=dict)
    predicted_state: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    expected_outcome: str = ""
    uncertainty: list[str] = field(default_factory=list)
    label: str = "HYPOTHETICAL"
    created_at: float = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.label != "HYPOTHETICAL":
            raise SimulationError("simulation label is fixed")
        if len(str(self.base_state)) > 65536:
            raise SimulationError("base state exceeds 64 KiB")


def _forbidden_live(value: Any, path: str = "state") -> None:
    """Reject anything that smells like a live subsystem handle."""
    if isinstance(value, dict):
        for key, item in list(value.items())[:50]:
            _forbidden_live(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value[:50]):
            _forbidden_live(item, f"{path}[{index}]")
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise SimulationError(
            f"live object rejected at {path}: "
            f"{type(value).__name__} (dicts of scalars only)")


class SimulationBoundary:
    """Copy-state hypotheticals. No live references cross this line."""

    def __init__(self, max_simulations: int = 20) -> None:
        self.max_simulations = max(1, max_simulations)
        self.history: list[Simulation] = []
        self.metrics: dict[str, int] = {"runs": 0, "rejected": 0}

    def run(self, question: str, base_state: dict[str, Any],
            change: dict[str, Any],
            predict: Callable[[dict[str, Any], dict[str, Any]],
                              dict[str, Any]] | None = None) -> Simulation:
        """Apply a hypothetical change to a state COPY and predict.

        ``predict`` is an optional pure function
        (base_copy, change) -> {predicted, risks, expected, uncertainty}.
        Default: shallow key-wise application.
        """
        if not isinstance(base_state, dict) or not isinstance(change, dict):
            self.metrics["rejected"] += 1
            raise SimulationError("simulation needs dict state and change")
        _forbidden_live(base_state, "base_state")
        _forbidden_live(change, "change")
        base_copy = {str(k)[:80]: v for k, v in
                     list(base_state.items())[:50]}
        change_copy = {str(k)[:80]: v for k, v in
                       list(change.items())[:20]}
        if predict is None:
            predicted = dict(base_copy)
            applied = []
            for key, value in change_copy.items():
                if key in predicted:
                    predicted[key] = value
                    applied.append(key)
            result = {
                "predicted": {k: str(v)[:200]
                              for k, v in list(predicted.items())[:30]},
                "risks": [f"unknown key {k}: no basis" for k in
                          change_copy if k not in base_copy],
                "expected": f"applied: {', '.join(applied) or 'nothing'}",
                "uncertainty": ["hypothetical only: not observed"],
            }
        else:
            try:
                result = predict(base_copy, change_copy)
            except Exception as exc:
                raise SimulationError(f"predict failed: {exc}"[:200])
            if not isinstance(result, dict):
                raise SimulationError("predict must return a dict")
        simulation = Simulation(
            simulation_id=f"sim-{int(_utcnow() * 1000) % 100000:05d}",
            question=question[:300], base_state=base_copy,
            hypothetical_change=change_copy,
            predicted_state=dict(result.get("predicted", {}) or {}),
            risks=[str(r)[:200] for r in
                   (result.get("risks", []) or [])][:10],
            expected_outcome=str(result.get("expected", ""))[:300],
            uncertainty=[str(u)[:200] for u in
                         (result.get("uncertainty", []) or [])][:10])
        self.history.append(simulation)
        del self.history[:-self.max_simulations]
        self.metrics["runs"] += 1
        return simulation


@dataclass
class Budget:
    name: str
    limit: float
    used: float = 0.0

    def consume(self, amount: float = 1.0) -> bool:
        """Returns False (without consuming) when exhausted."""
        if self.used + amount > self.limit:
            return False
        self.used += amount
        return True

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.used)


class ComputeBudget:
    """Bounded budgets for a cognitive cycle."""

    def __init__(self, *, time_s: float = 30.0, steps: int = 12,
                 observations: int = 5, tools: int = 6, retries: int = 2,
                 replans: int = 1, retrievals: int = 5,
                 simulations: int = 3) -> None:
        self.started = time.monotonic()
        self.budgets = {
            "time": Budget("time", max(1.0, time_s)),
            "steps": Budget("steps", max(1, steps)),
            "observations": Budget("observations",
                                   max(1, observations)),
            "tools": Budget("tools", max(1, tools)),
            "retries": Budget("retries", max(0, retries)),
            "replans": Budget("replans", max(0, replans)),
            "retrievals": Budget("retrievals", max(1, retrievals)),
            "simulations": Budget("simulations", max(1, simulations)),
        }

    def check_time(self) -> bool:
        elapsed = time.monotonic() - self.started
        budget = self.budgets["time"]
        budget.used = elapsed
        return not budget.exhausted

    def consume(self, name: str, amount: float = 1.0) -> bool:
        budget = self.budgets.get(name)
        if budget is None:
            return False
        if name == "time":
            return self.check_time()
        return budget.consume(amount)

    def exhausted(self) -> list[str]:
        self.check_time()
        return sorted(name for name, budget in self.budgets.items()
                      if budget.exhausted)

    def partial_result(self, reason: str = "") -> dict[str, Any]:
        return {"ok": False, "partial": True,
                "exhausted": self.exhausted(),
                "reason": (reason or "budget exhausted")[:200],
                "used": {name: round(budget.used, 2)
                         for name, budget in self.budgets.items()}}

    def status(self) -> dict[str, Any]:
        self.check_time()
        return {"budgets": {
            name: {"limit": budget.limit, "used": round(budget.used, 2),
                   "remaining": round(budget.remaining, 2)}
            for name, budget in self.budgets.items()}}


__all__ = [
    "Budget",
    "ComputeBudget",
    "Simulation",
    "SimulationBoundary",
    "SimulationError",
]
