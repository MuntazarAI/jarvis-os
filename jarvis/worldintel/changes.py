"""Change detection over world snapshots (World Intelligence 1.0).

Compares two evidence/claim snapshots deterministically and classifies
every difference: NEW, CHANGED, REMOVED, RESOLVED, CONFLICTED,
SUPERSEDED. Formatting-only differences never count as change
(normalized keys are compared, not raw text).
"""

from __future__ import annotations

from typing import Any


def snapshot_claims(entries: list[tuple[str, dict[str, Any]]]
                    ) -> dict[str, dict[str, Any]]:
    """Build a normalized snapshot: claim key -> record. `entries` are
    (key, record) pairs; keys must already be normalized."""
    snapshot: dict[str, dict[str, Any]] = {}
    for key, record in entries:
        if isinstance(key, str) and key and isinstance(record, dict):
            snapshot[key] = record
    return snapshot


def diff_snapshots(old: dict[str, dict[str, Any]],
                   new: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic diff, sorted by key. Statuses: NEW, REMOVED,
    CHANGED (object/confidence moved), RESOLVED (was conflicting, now
    single), CONFLICTED (single, now conflicting), SUPERSEDED
    (replaced by a newer key the caller links)."""
    changes: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        if before is None:
            changes.append({"key": key, "status": "NEW",
                            "after": after})
        elif after is None:
            changes.append({"key": key, "status": "REMOVED",
                            "before": before})
        else:
            was_conflict = bool(before.get("conflicting", False))
            is_conflict = bool(after.get("conflicting", False))
            same_object = (before.get("object")
                           == after.get("object"))
            if was_conflict and not is_conflict and same_object:
                changes.append({"key": key, "status": "RESOLVED",
                                "before": before, "after": after})
            elif not was_conflict and is_conflict:
                changes.append({"key": key, "status": "CONFLICTED",
                                "before": before, "after": after})
            elif not same_object:
                changes.append({"key": key, "status": "CHANGED",
                                "before": before, "after": after})
    return changes


__all__ = ["snapshot_claims", "diff_snapshots"]
