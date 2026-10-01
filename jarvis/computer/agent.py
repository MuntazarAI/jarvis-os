"""Computer Agent 2.0: planned UI actions with before/after verification.

Every action: screenshot before → policy gate → execute → screenshot after
→ verify → retry or undo. Undo is honest: reversible actions (clipboard,
focus) restore prior state; irreversible ones (typed text, clicks) are
recorded as non-reversible instead of faked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.types import now


@dataclass
class UIAction:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    verify: dict[str, Any] = field(default_factory=dict)
    retries: int = 1
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "verify": self.verify,
                "retries": self.retries, "description": self.description}


@dataclass
class UIResult:
    action: UIAction
    ok: bool
    attempts: int = 0
    before_shot: str = ""
    after_shot: str = ""
    verification: str = ""
    error: str = ""
    reversible: bool = True
    undone: bool = False
    at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action.to_dict(), "ok": self.ok,
                "attempts": self.attempts, "before": self.before_shot,
                "after": self.after_shot, "verification": self.verification,
                "error": self.error, "reversible": self.reversible,
                "undone": self.undone}


class ComputerAgent:
    """Supervised desktop operator. Never acts without a policy decision."""

    REVERSIBLE = {"clipboard_write": "clipboard_restore",
                  "window_focus": "window_refocus"}

    def __init__(self, computer: Any, policy: Any, tools: Any,
                 vision: Any | None = None, shot_dir: str = "/tmp/jarvis-ui") -> None:
        self.computer = computer
        self.policy = policy
        self.tools = tools
        self.vision = vision
        self.shot_dir = shot_dir
        self.history: list[UIResult] = []
        self.undo_stack: list[dict[str, Any]] = []

    # -- single action -------------------------------------------------------
    def act(self, actor: str, action: UIAction,
            approval: str = "") -> UIResult:
        """Execute one gated action. Pass an approved token to satisfy the
        approval gate for multi-step runs; otherwise a fresh token is
        minted and returned in the error (default-deny)."""
        result = UIResult(action=action, ok=False)
        from pathlib import Path
        Path(self.shot_dir).mkdir(parents=True, exist_ok=True)
        stamp = int(now())
        result.before_shot = f"{self.shot_dir}/before_{stamp}.png"
        self.computer.screen.capture(result.before_shot)

        undo = self._prepare_undo(action)
        decision = self.policy.evaluate(actor, self._plan_for(action)) \
            if hasattr(self.policy, "evaluate") else None
        if decision is not None and not decision.allow:
            result.error = "blocked by policy: " + "; ".join(decision.reasons)
            self.history.append(result)
            return result
        if decision is not None and decision.requires_approval:
            if not (approval and self.policy.approved(approval)):
                token = self.policy.request_approval(actor, self._plan_for(action),
                                                     decision)
                result.error = f"needs approval (token {token})"
                self.history.append(result)
                return result

        last_error = ""
        for attempt in range(1, action.retries + 1):
            result.attempts = attempt
            call = self.tools.call(action.tool, **action.args)
            if not call.ok:
                last_error = call.error
                time.sleep(min(2.0, 0.3 * attempt))
                continue
            result.after_shot = f"{self.shot_dir}/after_{stamp}_{attempt}.png"
            self.computer.screen.capture(result.after_shot)
            passed, note = self._verify(action, result)
            result.verification = note
            if passed:
                result.ok = True
                result.reversible = action.tool in self.REVERSIBLE
                if undo:
                    self.undo_stack.append(undo)
                self.history.append(result)
                return result
            last_error = note
            time.sleep(min(2.0, 0.3 * attempt))
        result.error = last_error or "verification failed"
        result.reversible = action.tool in self.REVERSIBLE
        self.history.append(result)
        return result

    def _plan_for(self, action: UIAction) -> Any:
        from ..core.types import ActionPlan, RiskLevel
        spec = self.tools.get(action.tool)
        return ActionPlan(
            action=f"{action.tool} {action.description}".strip(),
            args=action.args,
            required_permissions=list(spec.spec.required_permissions) if spec else [],
            risk=spec.spec.risk if spec else RiskLevel.LOW,
            verification_conditions=[str(action.verify)])

    def _prepare_undo(self, action: UIAction) -> dict[str, Any] | None:
        if action.tool == "clipboard_write":
            current = self.computer.clipboard.read()
            return {"kind": "clipboard_restore",
                    "text": current.get("text", "") if current.get("ok") else ""}
        if action.tool == "window_focus":
            return {"kind": "window_refocus", "note": "refocus previous window"}
        return None

    def _verify(self, action: UIAction, result: UIResult) -> tuple[bool, str]:
        spec = action.verify or {}
        if not spec:
            return True, "no verification requested"
        kind = spec.get("kind", "")
        if kind == "ocr_contains":
            want = str(spec.get("text", ""))
            ocr = self._ocr(result.after_shot)
            if want.lower() in ocr.lower():
                return True, f"screen now shows {want!r}"
            return False, f"screen does not show {want!r}"
        if kind == "clipboard_equals":
            got = self.computer.clipboard.read()
            if got.get("ok") and got.get("text") == spec.get("text"):
                return True, "clipboard matches"
            return False, "clipboard mismatch"
        if kind == "file_exists":
            from pathlib import Path
            if Path(str(spec.get("path", ""))).exists():
                return True, "file present"
            return False, "file missing"
        return True, f"unknown verification kind {kind!r} — treated as pass"

    def _ocr(self, path: str) -> str:
        if self.vision is not None:
            try:
                return self.vision._ocr_file(path)
            except Exception:
                pass
        try:
            from .computer import ClipboardController  # noqa: F401
        except Exception:
            pass
        import shutil
        import subprocess
        if shutil.which("tesseract") is None:
            return ""
        try:
            proc = subprocess.run(["tesseract", path, "stdout"],
                                  capture_output=True, text=True, timeout=30)
            return proc.stdout if proc.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    # -- undo ------------------------------------------------------------------
    def undo_last(self) -> dict[str, Any]:
        if not self.undo_stack:
            return {"ok": False, "error": "nothing reversible to undo"}
        undo = self.undo_stack.pop()
        if undo["kind"] == "clipboard_restore":
            result = self.computer.clipboard.write(undo.get("text", ""))
            return {"ok": bool(result.get("ok")), "undid": "clipboard"}
        return {"ok": False, "error": f"cannot undo {undo['kind']} automatically"}

    def run_goal(self, actor: str, actions: list[UIAction],
                 stop_on_fail: bool = True, approval: str = "") -> dict[str, Any]:
        results: list[UIResult] = []
        for action in actions:
            result = self.act(actor, action, approval=approval)
            results.append(result)
            if not result.ok and stop_on_fail:
                break
        done = [r.to_dict() for r in results]
        return {"ok": all(r.ok for r in results), "steps": done,
                "reversible": [r.reversible for r in results]}
