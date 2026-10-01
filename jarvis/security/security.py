"""Secrets vault, sessions, consent and privacy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import new_id, now


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


class SecretVault:
    """Local encrypted-at-rest store. Key from env or generated (0600 file)."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.key_file = self.home / ".vault.key"
        self.store_file = self.home / "secrets.json"
        self._lock = threading.RLock()
        self.key = self._load_or_create_key()
        self._secrets: dict[str, dict[str, Any]] = self._load()
        self.access_log: list[dict[str, Any]] = []

    def _load_or_create_key(self) -> bytes:
        env = os.environ.get("JARVIS_VAULT_KEY")
        if env:
            return hashlib.sha256(env.encode()).digest()
        if self.key_file.exists():
            return bytes.fromhex(self.key_file.read_text().strip())
        key = secrets.token_bytes(32)
        self.key_file.write_text(key.hex())
        try:
            os.chmod(self.key_file, 0o600)
        except OSError:
            pass
        return key

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.store_file.exists():
            return {}
        try:
            return json.loads(self.store_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        with self._lock:
            self.store_file.write_text(json.dumps(self._secrets, indent=2))
            try:
                os.chmod(self.store_file, 0o600)
            except OSError:
                pass

    def _seal(self, plaintext: str) -> str:
        raw = plaintext.encode()
        sealed = _xor(raw, self.key)
        mac = hmac.new(self.key, sealed, hashlib.sha256).hexdigest()
        return base64.b64encode(sealed).decode() + "." + mac

    def _open(self, blob: str) -> str:
        try:
            encoded, mac = blob.rsplit(".", 1)
        except ValueError:
            raise ValueError("corrupt secret blob")
        sealed = base64.b64decode(encoded)
        if not hmac.compare_digest(mac, hmac.new(self.key, sealed, hashlib.sha256).hexdigest()):
            raise ValueError("secret integrity check failed")
        return _xor(sealed, self.key).decode()

    def put(self, name: str, value: str, expires_in: float | None = None) -> None:
        with self._lock:
            self._secrets[name] = {
                "blob": self._seal(value),
                "created": now(),
                "expires_at": now() + expires_in if expires_in else None,
            }
            self._save()

    def get(self, name: str, actor: str = "jarvis") -> str | None:
        with self._lock:
            entry = self._secrets.get(name)
            if not entry:
                return None
            if entry.get("expires_at") and entry["expires_at"] <= now():
                del self._secrets[name]
                self._save()
                return None
            value = self._open(entry["blob"])
            self.access_log.append({"name": name, "actor": actor, "at": now()})
            return value

    def delete(self, name: str) -> bool:
        with self._lock:
            if name not in self._secrets:
                return False
            del self._secrets[name]
            self._save()
            return True

    def rotate(self, name: str, value: str) -> bool:
        with self._lock:
            if name not in self._secrets:
                return False
            self.put(name, value)
            return True

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._secrets)


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: new_id("sess"))
    user: str = "user"
    created: float = field(default_factory=now)
    last_active: float = field(default_factory=now)
    expires_at: float = field(default_factory=lambda: now() + 86400)
    permissions: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    branched_from: str = ""

    def touch(self) -> None:
        self.last_active = now()

    @property
    def expired(self) -> bool:
        return now() >= self.expires_at


class SessionEngine:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(self, user: str = "user", permissions: list[str] | None = None,
               ttl: float = 86400.0) -> Session:
        sess = Session(user=user, permissions=permissions or [],
                       expires_at=now() + ttl)
        with self._lock:
            self._sessions[sess.session_id] = sess
        return sess

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None
            if sess.expired:
                del self._sessions[session_id]
                return None
            sess.touch()
            return sess

    def branch(self, session_id: str) -> Session | None:
        with self._lock:
            parent = self._sessions.get(session_id)
            if not parent:
                return None
            child = Session(user=parent.user, permissions=list(parent.permissions),
                            context=dict(parent.context), branched_from=session_id)
            self._sessions[child.session_id] = child
            return child

    def end(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def active(self) -> list[Session]:
        with self._lock:
            live = []
            for sid in list(self._sessions):
                sess = self._sessions[sid]
                if sess.expired:
                    del self._sessions[sid]
                else:
                    live.append(sess)
            return live


class ConsentEngine:
    """Per-data, per-device, per-sensor consent with retention policies."""

    SCOPES = ("camera", "microphone", "memory", "sharing", "sensors", "location")

    def __init__(self) -> None:
        self.grants: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []

    def grant(self, scope: str, actor: str = "user",
              expires_in: float | None = None) -> None:
        if scope not in self.SCOPES:
            raise ValueError(f"unknown consent scope: {scope}")
        self.grants[scope] = {"by": actor, "at": now(),
                              "expires_at": now() + expires_in if expires_in else None}
        self.history.append({"scope": scope, "decision": "granted",
                             "by": actor, "at": now()})

    def revoke(self, scope: str, actor: str = "user") -> None:
        self.grants.pop(scope, None)
        self.history.append({"scope": scope, "decision": "revoked",
                             "by": actor, "at": now()})

    def allowed(self, scope: str) -> bool:
        grant = self.grants.get(scope)
        if not grant:
            return False
        if grant.get("expires_at") and grant["expires_at"] <= now():
            self.grants.pop(scope, None)
            return False
        return True

    def require(self, scope: str) -> None:
        if not self.allowed(scope):
            raise PermissionError(f"consent required for: {scope}")

    def export(self) -> dict[str, Any]:
        return {"grants": {k: {**v} for k, v in self.grants.items()},
                "history": list(self.history)}
