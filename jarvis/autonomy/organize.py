"""Bounded file organization under standing grants (Autonomy 1.0).

plan() inspects one directory and proposes moves by deterministic
extension rules (no LLM, no renaming in v1 — original names kept).
execute() performs each move only after BOTH checks pass:

  1. standing-grant coverage (capability media.organize, scope, op)
  2. PolicyEngine.evaluate (risk/approval/egress/emergency-stop)

Either check may stop the run with an honest report. Every move is
verified (dest exists, src gone); failures halt that file, never the
evidence trail. No deletion, no upload, no chmod, no execution.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

CATEGORIES: dict[str, str] = {
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images",
    ".gif": "Images", ".webp": "Images", ".svg": "Images",
    ".mp4": "Videos", ".mkv": "Videos", ".mov": "Videos",
    ".avi": "Videos",
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio",
    ".ogg": "Audio",
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".txt": "Documents", ".md": "Documents", ".csv": "Documents",
    ".zip": "Archives", ".tar": "Archives", ".gz": "Archives",
    ".7z": "Archives",
    ".py": "Code", ".js": "Code", ".ts": "Code", ".json": "Code",
    ".sh": "Code", ".yaml": "Code", ".yml": "Code", ".toml": "Code",
}

MAX_FILES = 100
CAPABILITY = "media.organize"


def plan(directory: str | Path, *, max_files: int = MAX_FILES,
         ) -> dict[str, Any]:
    """Propose moves. Pure inspection, no mutation, bounded."""
    root = Path(directory).expanduser()
    moves: list[dict[str, str]] = []
    skipped: list[str] = []
    if not root.is_dir():
        return {"moves": [], "skipped": ["not a directory"],
                "root": str(root)}
    try:
        entries = sorted(root.iterdir())
    except OSError as exc:
        return {"moves": [], "skipped": [f"{type(exc).__name__}"],
                "root": str(root)}
    for item in entries[:max_files + 25]:
        if len(moves) >= max_files:
            skipped.append("file cap reached")
            break
        try:
            if not item.is_file() or item.is_symlink():
                skipped.append(f"{item.name}: not a regular file")
                continue
            category = CATEGORIES.get(item.suffix.lower())
            if category is None:
                skipped.append(f"{item.name}: uncategorized")
                continue
            moves.append({"src": str(item), "category": category,
                          "name": item.name})
        except OSError:
            skipped.append(f"{item.name}: unreadable")
    return {"moves": moves, "skipped": skipped, "root": str(root)}


def execute(plan_result: dict[str, Any], *, actor: str,
            policy: Any, tools: Any) -> dict[str, Any]:
    """Run a plan. Each move needs grant coverage AND policy approval
    sight; either may refuse. Returns per-file outcomes + verification."""
    from ..core.types import ActionPlan
    from ..policy.policy import PolicyEngine
    if not isinstance(policy, PolicyEngine):
        return {"moved": [], "refused": [], "failed": [],
                "verified": 0, "started_at": time.time(),
                "finished_at": time.time(),
                "error": "policy authority missing"}
    report: dict[str, Any] = {
        "moved": [], "refused": [], "failed": [], "verified": 0,
        "started_at": time.time()}
    for move in plan_result.get("moves", [])[:MAX_FILES]:
        src, category = move["src"], move["category"]
        dest_dir = str(Path(plan_result["root"]) / category)
        ok, reason = policy.authorize_standing(
            actor, CAPABILITY, "path", src, "move") \
            if hasattr(policy, "authorize_standing") else (False, "")
        if not ok:
            report["refused"].append(
                {"src": src, "reason": f"grant: {reason}"})
            continue
        assessment = policy.evaluate(
            actor, ActionPlan(action="filesystem_move",
                              args={"src": src, "dest_dir": dest_dir},
                              required_permissions=["fs.write"]))
        if not assessment.allow:
            report["refused"].append(
                {"src": src,
                 "reason": "policy: " + "; ".join(
                     assessment.reasons)[:160]})
            continue
        if assessment.requires_approval:
            report["refused"].append(
                {"src": src, "reason": "policy: approval required"})
            continue
        try:
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            result = tools.call("filesystem_move", src=src,
                                dest_dir=dest_dir)
        except Exception as exc:
            result = None
            report["failed"].append(
                {"src": src, "error": f"{type(exc).__name__}"})
            continue
        if result is not None and result.ok:
            out = result.output or {}
            if Path(str(out.get("dest", ""))).is_file() and not \
                    Path(str(out.get("src", src))).exists():
                report["moved"].append(
                    {"src": src, "dest": out.get("dest", "")})
                report["verified"] += 1
            else:
                report["failed"].append(
                    {"src": src, "error": "verification mismatch"})
        else:
            report["failed"].append(
                {"src": src,
                 "error": str(getattr(result, "error", "failed"))[:160]})
    report["finished_at"] = time.time()
    return report


__all__ = ["CATEGORIES", "MAX_FILES", "CAPABILITY", "plan", "execute"]
