"""Deterministic cycle snapshots: capture, replay, compare.

A snapshot records everything needed to replay a cognitive cycle for
debugging WITHOUT re-executing side effects: replay re-runs the pure
stages (normalize..policy) and compares decisions, but never calls the
action executor. Secrets are scrubbed at capture time.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from .loop import CycleRecord, IntelligenceLoop

SECRET_KEYS = ("password", "secret", "token", "credential", "api_key", "private_key")


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(s in k.lower() for s in SECRET_KEYS) else scrub(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…[truncated]"
    return value


@dataclass
class CycleSnapshot:
    snapshot_id: str
    cycle: dict[str, Any]
    input_event: Any
    context_hints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id,
                "cycle": copy.deepcopy(self.cycle),
                "input_event": scrub(self.input_event),
                "context_hints": scrub(self.context_hints)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, indent=2, sort_keys=True)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CycleSnapshot":
        return CycleSnapshot(
            snapshot_id=str(data.get("snapshot_id", "")),
            cycle=dict(data.get("cycle", {})),
            input_event=data.get("input_event"),
            context_hints=dict(data.get("context_hints", {})),
        )


def capture(record: CycleRecord, input_event: Any,
            context_hints: dict[str, Any] | None = None) -> CycleSnapshot:
    import uuid
    return CycleSnapshot(
        snapshot_id=f"snap-{uuid.uuid4().hex[:12]}",
        cycle=scrub(record.to_dict()),
        input_event=scrub(input_event),
        context_hints=scrub(dict(context_hints or {})),
    )


def replay(snapshot: CycleSnapshot, loop: IntelligenceLoop) -> CycleRecord:
    """Re-run the cycle's pure stages with the executor DISABLED.

    Temporarily unbinds the executor so replay can never cause side
    effects, even if the snapshot's policy decision was 'allow'.
    """
    real_executor = loop.executor
    loop.executor = None
    try:
        return loop.cycle_once(copy.deepcopy(snapshot.input_event))
    finally:
        loop.executor = real_executor


def compare(original: CycleRecord, replayed: CycleRecord) -> dict[str, Any]:
    """Compare decisions between an original and a replayed cycle."""
    def decisions(record: CycleRecord) -> dict[str, Any]:
        stages = {s.stage: s for s in record.stages}
        return {
            "failed_stage": record.failed_stage,
            "action_taken": record.action_taken,
            "policy_allowed": record.policy_allowed,
            "plan_detail": (stages.get("plan").detail if "plan" in stages else {}),
            "policy_detail": (stages.get("policy").detail if "policy" in stages else {}),
        }
    left, right = decisions(original), decisions(replayed)
    mismatches = sorted(k for k in left if left[k] != right[k])
    return {"match": not mismatches, "mismatches": mismatches,
            "original": left, "replayed": right}
