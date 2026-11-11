"""Policy engine and risk assessment: every action gated before execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import JarvisConfig
from ..core.types import ActionPlan, RiskLevel, now

POLICY_GRANTS_FILENAME = "policy-grants.json"
POLICY_AUDIT_FILENAME = "policy-audit.json"

# Approval arguments are operator-facing. Keep them readable but bounded,
# and redact secret-shaped keys/values before they leave the policy layer.
_SECRET_ARG_KEY_HINTS = (
    "password", "passwd", "secret", "token", "credential", "api_key",
    "apikey", "private_key", "privatekey", "auth", "passphrase",
    "seed_phrase", "session", "cookie", "ssn",
)
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|apikey|"
    r"authorization|passphrase)\b(\s*[:=]\s*)([^\s,;]+)")
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_URL_USERINFO_RE = re.compile(r"(?i)\b(https?://)[^/@\s]+@")


def sanitize_approval_args(args: Any, *, max_depth: int = 3,
                           max_items: int = 20,
                           max_text: int = 200) -> Any:
    """Return a bounded, secret-scrubbed view of approval-bound arguments.

    The operator must see what they are approving, but raw arguments can
    contain passwords, tokens, keys, or very large payloads. This keeps
    structure and useful values while redacting secret-shaped keys,
    ``key=value`` credentials, bearer tokens, and URL userinfo.
    """
    from ..perception.contract import redact_secret_spans

    def _text(value: str) -> str:
        clean = _SECRET_ASSIGN_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}[redacted]", value)
        clean = _BEARER_RE.sub(
            lambda m: f"{m.group(1)}[redacted]", clean)
        clean = _URL_USERINFO_RE.sub(
            lambda m: f"{m.group(1)}[redacted]@", clean)
        clean, _ = redact_secret_spans(clean)
        if len(clean) > max_text:
            clean = clean[:max_text] + "…[truncated]"
        return clean

    def _walk(value: Any, depth: int) -> Any:
        if depth > max_depth:
            return "[redacted: nesting]"
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= max_items:
                    out["…"] = f"[{len(value) - max_items} more keys]"
                    break
                name = str(key)[:64]
                if any(hint in name.lower()
                       for hint in _SECRET_ARG_KEY_HINTS):
                    out[name] = "[redacted]"
                else:
                    out[name] = _walk(item, depth + 1)
            return out
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            out = [_walk(item, depth + 1) for item in items[:max_items]]
            if len(items) > max_items:
                out.append(f"…[{len(items) - max_items} more items]")
            return out
        if isinstance(value, str):
            return _text(value)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return _text(str(value))

    return _walk(args if args is not None else {}, 0)


@dataclass
class PolicyDecision:
    allow: bool
    risk: float
    risk_level: RiskLevel
    requires_approval: bool
    reasons: list[str] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)
    decided_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "risk": round(self.risk, 4),
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "reasons": self.reasons,
            "mitigations": self.mitigations,
        }


class RateLimiter:
    """Token-bucket rate limiter per actor and action."""

    def __init__(self, max_calls: int = 30, window_s: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.RLock()

    def _key(self, actor: str, action: str) -> str:
        return f"{actor}:{action}"

    def allow(self, actor: str, action: str) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        key = self._key(actor, action)
        now_ts = time.time()
        with self._lock:
            calls = self._buckets.get(key, [])
            # Remove expired
            calls = [t for t in calls if now_ts - t < self.window_s]
            if len(calls) >= self.max_calls:
                oldest = calls[0]
                return False, self.window_s - (now_ts - oldest)
            calls.append(now_ts)
            self._buckets[key] = calls
            return True, 0.0


class RiskEngine:
    """Impact × probability × reversibility scoring with blast-radius checks."""

    DESTRUCTIVE_VERBS = {"delete", "rm ", "format", "wipe", "drop", "shutdown",
                         "kill -9", "chmod -r", "chown -r", "mkfs", "dd "}

    def __init__(self, config: JarvisConfig | None = None) -> None:
        self.config = config or JarvisConfig()

    def assess(self, action: str, args: dict[str, Any] | None = None,
               context: dict[str, Any] | None = None) -> PolicyDecision:
        args = args or {}
        context = context or {}
        risk, reasons = 0.05, []
        low = action.lower()

        for verb in self.DESTRUCTIVE_VERBS:
            if verb in low:
                risk = max(risk, 0.95)
                reasons.append(f"destructive verb detected: {verb.strip()}")
        if "delete" in low and "system" in low:
            risk = max(risk, 0.9)
            reasons.append("system file deletion")
        words = set(re.findall(r"[a-z0-9_]+", low))
        if "install" in low or words & {"apt", "pip", "npm", "dnf", "apk"}:
            risk = max(risk, 0.5)
            reasons.append("software installation changes system state")
        if any(k in low for k in ("network", "ssh", "curl", "wget", "fetch")):
            risk = max(risk, 0.4)
            reasons.append("network egress")
        if "write" in low or "create" in low:
            risk = max(risk, 0.5)
            reasons.append("filesystem mutation")

        tool_name = low.split()[0] if low else ""
        # Safe tools that should not be flagged as scan/inventory
        safe_tools = {"system_probe", "terminal_run", "filesystem_read", "filesystem_write",
                      "python_run", "web_fetch", "open_url", "clipboard_read", "clipboard_write",
                      "window_list", "screen_capture", "screen_understand", "git_status",
                      "mouse_move", "mouse_click", "press_keys", "type_text", "window_focus",
                      "filesystem_move", "code_security_scan", "capture_read"}
        if tool_name in safe_tools:
            pass
        else:
            inv_scan_keywords = ("inventory", "scan", "audit", "probe", "enumerate", "nmap")
            tool_parts = tool_name.split("_")
            if any(
                k == tool_name
                or tool_name.startswith(k + "_")
                or k in tool_parts
                for k in inv_scan_keywords
            ):
                risk = max(risk, 0.65)
                reasons.append("network/system inventory or scan")

        blocked = [str(p) for p in self.config.policy.block_high_risk_paths]
        haystack = f"{action} {args}"
        for path in blocked:
            expanded = str(Path(path).expanduser())
            if expanded in haystack or path in haystack:
                risk = 1.0
                reasons.append(f"blocked path: {path}")

        if context.get("unverified_input"):
            risk = min(1.0, risk + 0.15)
            reasons.append("unverified external input in arguments")
        if context.get("quiet_hours"):
            risk = min(1.0, risk + 0.1)
            reasons.append("quiet hours — prefer deferring non-urgent actions")

        reversibility = 1.0 if risk < 0.4 else 0.3
        blast = self._blast_radius(action, args)
        risk = min(1.0, risk * (1.0 + 0.2 * blast))
        if reversibility < 0.5 and risk > 0.4:
            reasons.append("action may not be reversible")

        level = (
            RiskLevel.SAFE if risk < 0.1 else RiskLevel.LOW if risk < 0.35
            else RiskLevel.MEDIUM if risk < 0.6 else RiskLevel.HIGH
            if risk < 0.85 else RiskLevel.DESTRUCTIVE
        )
        threshold = self.config.policy.require_approval_above_risk
        return PolicyDecision(
            allow=risk < 1.0,
            risk=round(risk, 4),
            risk_level=level,
            requires_approval=risk >= threshold,
            reasons=reasons or ["routine low-risk action"],
            mitigations=self._mitigations(level, risk),
        )

    @staticmethod
    def _blast_radius(action: str, args: dict[str, Any]) -> float:
        text = f"{action} {args}".lower()
        if any(w in text for w in ("/etc", "/usr", "/boot", "c:\\windows", "system32")):
            return 1.0
        if any(w in text for w in ("home", "~", "documents", "projects")):
            return 0.5
        if "tmp" in text or "temp" in text:
            return 0.2
        return 0.3

    @staticmethod
    def _mitigations(level: RiskLevel, risk: float) -> list[str]:
        if level in (RiskLevel.HIGH, RiskLevel.DESTRUCTIVE):
            return ["require explicit user approval", "dry-run first",
                    "snapshot state for rollback", "record full audit trail"]
        if level == RiskLevel.MEDIUM:
            return ["confirm scope before executing", "record audit trail"]
        if risk >= 0.3:
            return ["record audit trail"]
        return []


class PolicyEngine:
    """Permission policies, privacy boundaries, approval workflow, audit."""

    def __init__(self, config: JarvisConfig | None = None, *,
                 grant_store_path: str | Path | None = None) -> None:
        self.config = config or JarvisConfig()
        self.risk = RiskEngine(self.config)
        self.grants: dict[str, set[str]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.grant_store_path = Path(grant_store_path) \
            if grant_store_path else None
        self._grants_mtime: float = 0.0
        self._grants_error: str = ""
        if self.grant_store_path is not None:
            self._load_grants()
        self._load_approvals()
        self._standing = None
        # In-process serialisation on top of the file lock: two threads
        # in one process must not interleave a check-then-write.
        self._lock = threading.RLock()
        # Rate limiting: 30 calls/minute per actor:action by default
        self.rate_limiter = RateLimiter(
            max_calls=self.config.policy.rate_limit_calls,
            window_s=self.config.policy.rate_limit_window_s,
        )

    def bind_standing_grants(self, store: Any) -> None:
        """Attach a StandingGrantStore. Reversible via bind_standing_grants(None)."""
        self._standing = store

    def _approvals_path(self):
        try:
            return Path(self.config.paths.home) / "policy-approvals.json"
        except Exception:
            return None

    def _approval_lock_path(self) -> Path | None:
        path = self._approvals_path()
        if path:
            return path.with_suffix(path.suffix + ".lock")
        return None

    def _grant_lock_path(self) -> Path | None:
        if self.grant_store_path is None:
            return None
        return self.grant_store_path.with_name(
            self.grant_store_path.name + ".lock")

    @staticmethod
    def _flock_best_effort(path: Path):
        """Cross-process exclusive lock; degrades gracefully."""
        import contextlib

        @contextlib.contextmanager
        def locked():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            try:
                import fcntl
            except ImportError:
                yield
                return
            try:
                with open(path, "a+b") as handle:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        try:
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
            except OSError:
                yield
        return locked()

    def _grant_mutation(self):
        """Lock, reload, mutate (caller), persist. Cross-process atomic."""
        import contextlib

        @contextlib.contextmanager
        def mutate():
            lock = self._grant_lock_path()
            if lock is None:
                with self._lock:
                    yield
                    self._save_grants()
                return
            with self._lock:
                with self._flock_best_effort(lock):
                    self._load_grants()
                    yield
                    self._save_grants()
        return mutate()

    def _approval_mutation(self):
        """Lock, reload, mutate (caller), persist. Cross-process atomic.

        Yields a small outcome dict. ``outcome["persisted"]`` is true only
        if the post-mutation write succeeded; callers that spend authority
        must check it before reporting success.
        """
        import contextlib

        @contextlib.contextmanager
        def mutate():
            outcome = {"persisted": False}
            lock = self._approval_lock_path()
            if lock is None:
                with self._lock:
                    yield outcome
                    outcome["persisted"] = self._save_approvals()
                return
            with self._lock:
                with self._flock_best_effort(lock):
                    self._load_approvals()
                    yield outcome
                    outcome["persisted"] = self._save_approvals()
        return mutate()

    def _load_grants(self) -> None:
        """Replace memory with disk state (revokes propagate).

        Accepts both store formats: the flat one ({"actor": [perms]})
        and the versioned one ({"version": 1, "grants": {...}}).
        A corrupt store never parses into authority: it raises the error
        flag and the checks fail closed.
        """
        if not self.grant_store_path or not self.grant_store_path.exists():
            return
        try:
            mtime = self.grant_store_path.stat().st_mtime
            if mtime == self._grants_mtime:
                return
            raw = json.loads(self.grant_store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._grants_error = f"{type(exc).__name__}: {exc}"[:160]
            return
        if not isinstance(raw, dict):
            self._grants_error = "ValueError: grant store root is not an object"
            return
        source = raw.get("grants")
        if not isinstance(source, dict):
            source = {k: v for k, v in raw.items() if k != "version"}
        fresh: dict[str, set[str]] = {}
        for actor, perms in source.items():
            if not isinstance(actor, str) or not isinstance(perms, list):
                continue
            fresh[actor] = {str(p) for p in perms if isinstance(p, str)}
        self.grants = fresh
        self._grants_mtime = mtime
        self._grants_error = ""

    def _maybe_reload_grants(self) -> None:
        """Pick up revokes made by another writer."""
        path = self.grant_store_path
        if path is None:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime != self._grants_mtime:
            self._load_grants()

    def _load_approvals(self) -> None:
        """Load approvals from durable storage.

        Accepts both store formats: the flat one ({token: entry}) and
        the versioned one ({"version": 1, "approvals": {...}}). Both are
        read and merged -- an entry is never dropped because the file
        carries a wrapper key as well.
        """
        path = self._approvals_path()
        if not path or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        source: dict[str, Any] = {}
        nested = raw.get("approvals")
        if isinstance(nested, dict):
            source.update(nested)
        for token, entry in raw.items():
            if token in ("version", "approvals"):
                continue
            source.setdefault(token, entry)
        fresh: dict[str, Any] = {}
        for token, entry in source.items():
            if not isinstance(token, str) or not isinstance(entry, dict):
                continue
            fresh[token] = entry
        self.approvals = fresh

    def _save_grants(self) -> None:
        if not self.grant_store_path:
            return
        try:
            self.grant_store_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".grants-",
                                       dir=str(self.grant_store_path.parent),
                                       text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({a: sorted(p) for a, p in self.grants.items()},
                              handle, indent=2)
                os.replace(tmp, self.grant_store_path)
                self.grant_store_path.chmod(0o600)
                self._grants_mtime = self.grant_store_path.stat().st_mtime
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception as exc:
            self._grants_error = f"grant save failed: {type(exc).__name__}"

    def grant(self, actor: str, permission: str) -> None:
        with self._grant_mutation():
            self.grants.setdefault(actor, set()).add(permission)

    def revoke(self, actor: str, permission: str) -> None:
        with self._grant_mutation():
            if actor in self.grants:
                self.grants[actor].discard(permission)
                if not self.grants[actor]:
                    del self.grants[actor]

    def list_grants(self, actor: str | None = None) -> dict[str, list[str]]:
        if actor is not None:
            return {actor: sorted(self.grants.get(actor, set()))}
        return {a: sorted(p) for a, p in self.grants.items()}

    def get_grant(self, actor: str) -> list[str]:
        return sorted(self.grants.get(actor, set()))

    def has_permission(self, actor: str, permission: str) -> bool:
        """Single permission check (same rules as is_granted)."""
        return self.is_granted(actor, permission)

    def is_granted(self, actor: str, permission: str) -> bool:
        """Durable-aware single permission check. Fail closed on error."""
        self._maybe_reload_grants()
        if self._grants_error:
            return False
        held = self.grants.get(actor, set())
        return "*" in held or permission in held

    def permitted(self, actor: str, required: list[str]) -> tuple[bool, list[str]]:
        """Durable-aware multi-permission check. Fail closed on error."""
        self._maybe_reload_grants()
        if self._grants_error:
            return False, ["policy grant store unreadable (fail closed)"]
        held = self.grants.get(actor, set())
        if "*" in held:
            return True, []
        missing = [p for p in required if p not in held]
        return (not missing), missing

    def authorize_standing(self, actor: str, permission: str,
                       scope_kind: str = "capability",
                       resource: str = "", operation: str = "") -> tuple[bool, str]:
        """Standing-grant check as authorization INPUT.

        Security-sensitive permissions always require live approval, and
        an engaged emergency stop beats every stored grant.
        """
        if self._standing is None:
            return False, "no standing grant store bound"
        # Security-sensitive permissions always require live approval
        if permission.startswith("sec."):
            return False, "security tools require live approval"
        if self._emergency_stop():
            return False, "EMERGENCY STOP engaged"
        try:
            return self._standing.authorize(
                actor, permission, scope_kind, resource, operation)
        except Exception as exc:
            return False, f"grant check failed: {type(exc).__name__}"

    def evaluate(self, actor: str, plan: ActionPlan) -> PolicyDecision:
        """Evaluate an action plan against policy.

        1. Rate limit check
        2. Risk assessment
        3. Permission check (grants + standing grants)
        4. Approval requirement
        """
        # Rate limit
        allowed, retry_after = self.rate_limiter.allow(actor, plan.action)
        if not allowed:
            return PolicyDecision(
                allow=False,
                risk=1.0,
                risk_level=RiskLevel.DESTRUCTIVE,
                requires_approval=False,
                reasons=[f"rate limit exceeded for {actor}:{plan.action} "
                         f"(retry in {retry_after:.0f}s)"],
                mitigations=["wait for rate limit window to reset"],
            )

        # Risk assessment
        decision = self.risk.assess(plan.action, plan.args, plan.context)

        # Permission check
        missing = [p for p in plan.required_permissions
                   if not self.is_granted(actor, p)]
        # Standing grants are authorization INPUT, not a bypass: they never
        # clear a permission check inside evaluate(). Scope and operation
        # are checked in authorize_standing().
        if missing:
            decision.allow = False
            decision.risk = max(decision.risk, 0.8)
            decision.risk_level = RiskLevel.HIGH if decision.risk < 0.85 else RiskLevel.DESTRUCTIVE
            decision.requires_approval = True
            decision.reasons.append(
                f"actor '{actor}' lacks permissions: {missing}")
            decision.mitigations.append("grant required permissions")

        # The tool's declared risk floors the text assessment: a tool
        # marked HIGH can never score 0.05 just because its name is benign.
        floor = plan.risk.numeric if isinstance(plan.risk, RiskLevel) else 0.0
        if floor > decision.risk:
            decision.risk = round(floor, 4)
            decision.risk_level = RiskLevel.from_score(floor)
            decision.reasons.append(f"tool declares {plan.risk.value} risk")
            if floor >= self.config.policy.require_approval_above_risk:
                decision.requires_approval = True

        # Local-only egress restriction
        if self.config.policy.local_only and self._is_egress(plan):
            decision.reasons.append("local-only mode: external egress restricted")
            if decision.risk < 0.5:
                decision.risk = 0.5
                decision.requires_approval = True

        # Emergency stop check
        if self._emergency_stop():
            decision.allow = False
            decision.risk = 1.0
            decision.risk_level = RiskLevel.DESTRUCTIVE
            decision.requires_approval = False
            decision.reasons.append("EMERGENCY STOP engaged — all actions blocked")
            decision.mitigations = []

        # Audit
        self._audit(actor, plan, decision)
        return decision

    def _audit(self, actor: str, plan: ActionPlan,
               decision: PolicyDecision) -> None:
        entry = {
            "at": now(),
            "actor": actor,
            "action": plan.action,
            "args": sanitize_approval_args(plan.args),
            "required_permissions": plan.required_permissions,
            "decision": decision.to_dict(),
            "emergency_stop": self.config.policy.emergency_stop,
        }
        self.audit.append(entry)
        if len(self.audit) > 10000:
            self.audit = self.audit[-10000:]
        self._persist_audit()

    def _persist_audit(self) -> None:
        try:
            path = Path(self.config.paths.home) / POLICY_AUDIT_FILENAME
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".audit-",
                                       dir=str(path.parent),
                                       text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.audit, handle, indent=2, default=str)
                os.replace(tmp, path)
                path.chmod(0o600)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception:
            pass

    def create_approval(self, actor: str, plan: ActionPlan) -> str:
        """Create a single-use approval token for a high-risk action."""
        token = hashlib.sha256(f"{actor}{plan.action}{now()}".encode()).hexdigest()[:32]
        self.approvals[token] = {
            "actor": actor,
            "action": plan.action,
            "args": plan.args,
            "created": now(),
            "used": False,
            "status": "pending",
            "expires_at": now() + 300.0,  # 5 min TTL
        }
        self._persist_approvals()
        return token

    # Backward compatibility methods for tests
    def request_approval(self, actor: str, plan: ActionPlan,
                         _risk: Any = None) -> str:
        """Legacy alias for create_approval."""
        return self.create_approval(actor, plan)

    def approve(self, token: str, by: str = "cli") -> bool:
        """Legacy: mark approval as approved by CLI."""
        with self._approval_mutation():
            full_token = self._find_approval(token)
            if not full_token:
                return False
            entry = self.approvals.get(full_token)
            if not entry:
                return False
            if entry.get("status") == "approved":
                return False
            entry["approved_by"] = by
            entry["approved_at"] = now()
            entry["status"] = "approved"
        return True

    def peek_approval(self, token: str, actor: str, action: str,
                      args: dict[str, Any] | None = None) -> bool:
        """Check if an approval is valid WITHOUT consuming it.

        Used by DeviceRouter to verify approval binding before consuming.
        Returns True only if: token exists, is approved, not used, matches actor/action/args, and not expired.
        """
        self._load_approvals()
        full_token = self._find_approval(token)
        if not full_token:
            return False
        entry = self.approvals.get(full_token)
        if not entry:
            return False
        if entry.get("used"):
            return False
        if entry.get("status") != "approved":
            return False
        if entry["actor"] != actor:
            return False
        if entry["expires_at"] <= now():
            return False
        # Verify action matches
        approved_action = entry.get("action", entry.get("plan", {}).get("action", ""))
        if approved_action != action:
            return False
        # Verify args match (None means empty dict for comparison)
        approved_args = entry.get("args", entry.get("plan", {}).get("args", {}))
        check_args = args if args is not None else {}
        if check_args != approved_args:
            return False
        return True

    def redeem(self, token: str, actor: str, action: str,
               args: dict[str, Any] | None = None) -> bool:
        """Legacy: consume approval token with argument verification.

        The check-and-spend runs under one lock, so two callers racing
        for the same token cannot both win.
        """
        outcome: dict[str, Any] = {"persisted": False, "ok": False,
                                   "entry": None}
        with self._approval_mutation() as outcome:
            full_token = self._find_approval(token)
            if not full_token:
                return False
            entry = self.approvals.get(full_token)
            if not entry:
                return False
            if entry.get("used"):
                return False
            if entry.get("status") != "approved":
                return False
            if entry["actor"] != actor:
                return False
            if entry["expires_at"] <= now():
                return False
            # Verify action matches
            approved_action = entry.get("action", entry.get("plan", {}).get("action", ""))
            if approved_action != action:
                return False
            # Verify args match (None means empty dict for comparison)
            approved_args = entry.get("args", entry.get("plan", {}).get("args", {}))
            check_args = args if args is not None else {}
            if check_args != approved_args:
                return False
            entry["used"] = True
            entry["status"] = "consumed"
            entry["consumed_at"] = now()
            outcome["entry"] = entry
            outcome["ok"] = True
        if not outcome["ok"]:
            return False
        if not outcome["persisted"]:
            # The spend did not reach disk: undo it in memory too.
            entry = outcome["entry"]
            if entry is not None:
                entry["used"] = False
                entry["status"] = "approved"
                entry.pop("consumed_at", None)
            return False
        return True

    def list_approvals(self, status: str = "all") -> list[dict[str, Any]]:
        """Legacy: list approvals by status. Returns truncated approval IDs
        with sanitized arguments."""
        from .policy import sanitize_approval_args
        out = []
        for token, entry in self.approvals.items():
            if status == "pending" and entry.get("used"):
                continue
            if status == "used" and not entry.get("used"):
                continue
            raw_args = entry.get("args", entry.get("plan", {}).get("args", {}))
            out.append({
                "approval_id": token[:12] + "…",  # truncated for display
                "actor": entry.get("actor", "?"),
                "action": entry.get("action", entry.get("plan", {}).get("action", "")),
                "args": sanitize_approval_args(raw_args),
                "created": entry.get("created", entry.get("requested_at", 0)),
                "status": entry.get("status", "pending"),
                "expires_at": entry.get("expires_at"),
            })
        return out

    def approved(self, token: str) -> bool:
        """Legacy: check if approval was approved (not just pending or spent)."""
        full_token = self._find_approval(token)
        if not full_token:
            return False
        entry = self.approvals.get(full_token)
        return entry and entry.get("status") == "approved" and not entry.get("used")

    def deny(self, token: str, by: str = "cli", reason: str = "") -> bool:
        """Legacy: deny/consume an approval token."""
        with self._approval_mutation():
            full_token = self._find_approval(token)
            if not full_token:
                return False
            entry = self.approvals.get(full_token)
            if not entry:
                return False
            entry["denied"] = True
            entry["denied_by"] = by
            entry["denied_at"] = now()
            entry["deny_reason"] = reason
            entry["status"] = "denied"
            entry["used"] = True
        return True

    def _find_approval(self, token_or_prefix: str) -> str | None:
        """Find approval token by full token or prefix (4+ chars)."""
        if token_or_prefix in self.approvals:
            return token_or_prefix
        if len(token_or_prefix) >= 4:
            for token in self.approvals:
                if token.startswith(token_or_prefix):
                    return token
        return None

    def _persist_approvals(self) -> bool:
        """Persist approvals to durable storage. Returns True on success."""
        path = self._approvals_path()
        if not path:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".approvals-",
                                       dir=str(path.parent),
                                       text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.approvals, handle, indent=2, default=str)
                os.replace(tmp, path)
                path.chmod(0o600)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            return True
        except Exception:
            return False

    # Backward compatibility alias
    _save_approvals = _persist_approvals

    def consume_approval(self, actor: str, token: str) -> bool:
        """Validate and consume a single-use approval token."""
        outcome: dict[str, Any] = {"persisted": False, "ok": False,
                                   "entry": None}
        with self._approval_mutation() as outcome:
            full_token = self._find_approval(token)
            if not full_token:
                return False
            entry = self.approvals.get(full_token)
            if not entry:
                return False
            if entry.get("used"):
                return False
            if entry["actor"] != actor:
                return False
            if entry["expires_at"] <= now():
                return False
            entry["used"] = True
            entry["status"] = "consumed"
            entry["consumed_at"] = now()
            outcome["entry"] = entry
            outcome["ok"] = True
        if not outcome["ok"]:
            return False
        if not outcome["persisted"]:
            entry = outcome["entry"]
            if entry is not None:
                entry["used"] = False
                entry["status"] = "approved"
                entry.pop("consumed_at", None)
            return False
        return True

    def emergency_stop(self, engaged: bool = True) -> None:
        """Engage or release the stop in memory (no file, no restart)."""
        self.config.policy.emergency_stop = engaged

    def _check_emergency_stop_file(self) -> bool:
        """Check the emergency stop file and update config if present."""
        try:
            path = Path(self.config.paths.home) / self.config.policy.emergency_stop_file
            if path.exists() and path.read_text().strip():
                self.config.policy.emergency_stop = True
                return True
        except Exception:
            pass
        return False

    def _emergency_stop(self) -> bool:
        """Internal method for subsystems to check emergency stop status."""
        self._check_emergency_stop_file()
        return self.config.policy.emergency_stop

    def emergency_stop_engaged(self) -> bool:
        """Public, read-only e-stop predicate for durable/security layers."""
        try:
            return self._emergency_stop()
        except Exception:
            return True  # fail closed when state cannot be read

    def engage_stop(self) -> Path:
        """Engage the stop for every process, now and after a restart."""
        target = Path(self.config.paths.home) / self.config.policy.emergency_stop_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"engaged at {now()}\n")
        self.config.policy.emergency_stop = True
        return target

    def release_stop(self) -> bool:
        """Release the stop: clear the flag and remove the stop file."""
        self.config.policy.emergency_stop = False
        target = Path(self.config.paths.home) / self.config.policy.emergency_stop_file
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        return True

    def privacy_check(self, secret_type: str, destination: str) -> tuple[bool, str]:
        """Check if a secret type is allowed to be sent to a destination."""
        allowed = destination in ("vault", "local", "internal")
        return (allowed, "allowed" if allowed else "external destination not allowed")

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Most recent audit entries, newest last."""
        return self.audit[-limit:]

    @staticmethod
    def _is_egress(plan: ActionPlan) -> bool:
        text = f"{plan.action} {plan.args}".lower()
        return any(w in text for w in ("http", "curl", "ssh ", "upload", "publish", "send"))

    def conflicts(self) -> list[dict[str, Any]]:
        """Return list of policy conflicts for status reporting."""
        return []