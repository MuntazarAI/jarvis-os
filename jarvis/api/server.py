"""HTTP API: REST + WebSocket event stream over the standard library."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..core.loop import Jarvis


def _bearer_ok(provided: str, expected: str) -> bool:
    import hmac
    want = f"Bearer {expected}"
    if len(provided) != len(want):
        return False
    return hmac.compare_digest(provided, want)


def _ws_token_ok(path: str, expected: str) -> bool:
    """WebSocket auth via ?token= (browsers cannot set headers on WS
    upgrades). Empty server token means open (same as REST)."""
    if not expected:
        return True
    import hmac
    import urllib.parse
    try:
        params = urllib.parse.parse_qs(
            urllib.parse.urlsplit(path).query)
        provided = params.get("token", [""])[0]
    except Exception:
        return False
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


class JarvisAPI:
    """REST endpoints plus a WebSocket broadcast of bus events."""

    def __init__(self, jarvis: Jarvis, host: str = "127.0.0.1", port: int = 8765,
                 token: str = "") -> None:
        self.jarvis = jarvis
        self.host = host
        self.port = port
        self.token = token
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._sockets: list[Any] = []
        self._sockets_lock = threading.Lock()
        jarvis.bus.subscribe("*", self._broadcast, name="ws-fanout")
        from ..worldintel.ratelimit import RateLimiter
        world = getattr(jarvis.config, "world", None)
        self._research_limiter = RateLimiter(
            max_calls=int(getattr(world, "api_rate_limit_n", 10)
                          if world else 10),
            window_s=float(getattr(world, "api_rate_window_s", 60.0)
                           if world else 60.0))
        # Approval decisions are authority acts: bound them per client
        # even for legitimate token holders (no brute-forcing tokens).
        self._approval_limiter = RateLimiter(max_calls=10,
                                             window_s=60.0)

    # -- routing -----------------------------------------------------------
    def handle(self, method: str, path: str, body: bytes,
               headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        # The board page itself is a static shell with NO data in it —
        # all data comes from /api/board, which stays token-gated
        # below. Gating the shell too would hide the token prompt
        # itself (chicken-and-egg: the login box locked behind login).
        if method == "GET" and path.split("?", 1)[0] == "/board":
            from .board import BOARD_HTML
            return 200, {"__html__": BOARD_HTML}
        if method == "GET" and path.split("?", 1)[0] == "/remote":
            from .remote import REMOTE_HTML
            return 200, {"__html__": REMOTE_HTML}
        if method == "GET" and path.split("?", 1)[0] == "/office":
            from .office_page import OFFICE_HTML
            return 200, {"__html__": OFFICE_HTML}
        if self.token and not _bearer_ok(
                headers.get("authorization", ""), self.token):
            return 401, {"error": "unauthorized"}
        try:
            if method == "GET" and path == "/health":
                return 200, {"status": "ok", "cycle": self.jarvis.cycle}
            if method == "GET" and path == "/status":
                return 200, self.jarvis.status()
            if method == "POST" and path == "/cycle":
                payload = json.loads(body.decode() or "{}")
                text = str(payload.get("input", ""))
                if not text:
                    return 400, {"error": "missing 'input'"}
                result = self.jarvis.cycle_once(text)
                return 200, result.to_dict()
            if method == "GET" and path == "/memory":
                return 200, self.jarvis.palace.stats()
            if method == "GET" and path == "/events":
                return 200, {"types": self.jarvis.events.types(),
                             "count": self.jarvis.events.count()}
            if method == "GET" and path.split("?", 1)[0] == "/api/board":
                from .board import build_board
                return 200, build_board(self.jarvis)
            if method == "GET" and path.split("?", 1)[0] == "/api/experience":
                from .experience import build_experience
                return 200, build_experience(self.jarvis)
            if method == "GET" and path.split("?", 1)[0] == "/experience":
                from .experience_page import EXPERIENCE_HTML
                return 200, {"__html__": EXPERIENCE_HTML}
            # NOTE: query strings are stripped for API routes only;
            # legacy routes above keep exact-match behavior.
            api_path = path.split("?", 1)[0].rstrip("/") or "/"
            if method == "GET" and api_path == "/api/missions/control":
                from ..missions.hud import HudContext, build_snapshot
                snapshot = build_snapshot(HudContext(
                    missions=self.jarvis.missions,
                    dots=self.jarvis.dots,
                    tasks=self.jarvis.tasks,
                    notifier=getattr(self.jarvis, "notifier", None),
                    policy=self.jarvis.policy,
                    system_state=self.jarvis.world.system_state
                    if hasattr(self.jarvis.world, "system_state") else None,
                    emergency_engaged=lambda: self.jarvis.policy._emergency_stop()
                    if hasattr(self.jarvis.policy, "_emergency_stop") else False,
                    proposals=self.jarvis.missions))
                return 200, snapshot
            if method == "GET" and api_path == "/api/missions/proposals":
                manager = self.jarvis.missions
                return 200, {"proposals": [
                    p.to_dict() for p in manager.list_proposals()]}
            if method == "GET" and api_path.startswith("/api/missions/proposals/"):
                pid = api_path.rsplit("/", 1)[-1]
                proposal = self.jarvis.missions.get_proposal(pid)
                if proposal is None:
                    return 404, {"error": f"unknown proposal: {pid}"}
                return 200, proposal.to_dict()
            if method == "GET" and api_path.startswith("/api/missions/"):
                mid = api_path.rsplit("/", 1)[-1]
                info = self.jarvis.missions.inspect(mid)
                if info is None:
                    return 404, {"error": f"unknown mission: {mid}"}
                return 200, info
            if method == "POST" and api_path == "/api/approvals/decision":
                return self._approval_decision(body, headers)
            if method == "POST" and api_path.startswith("/api/tasks/"):
                return self._task_action(api_path, body)
            if method == "POST" and path == "/mentalist":
                payload = json.loads(body.decode() or "{}")
                text = str(payload.get("input", ""))
                mode = self.jarvis.mentalist
                mode.observe(text, kind="text", source="api")
                mode.hypothesize([f"interpretation A: {text[:60]}",
                                  f"interpretation B (alternative): {text[:60]}"])
                return 200, {"report": mode.render()}
            if method == "GET" and api_path == "/api/world/health":
                from ..worldintel.cache import EvidenceCache
                from ..worldintel.health import check as world_check
                from ..worldintel.sources import SourceRegistry
                home = str(self.jarvis.config.paths.home)
                report = world_check(
                    self.jarvis.config.world.__dict__,
                    SourceRegistry(), EvidenceCache(home))
                return 200, report
            if method == "POST" and api_path == "/api/world/research":
                payload = json.loads(body.decode() or "{}")
                text = str(payload.get("input", ""))
                if not text:
                    return 400, {"error": "missing 'input'"}
                client_key = str(headers.get("authorization", "")
                                  or "anonymous")[:120]
                gate = self._research_limiter.check(client_key)
                if not gate["allowed"]:
                    from ..worldintel.telemetry import TELEMETRY
                    TELEMETRY.record(
                        "world.api.throttled", status="ok",
                        query_len=len(text),
                        correlation_id=client_key[:64],
                        detail=gate["reason"])
                    return 429, {"error": gate["reason"],
                                 "retry_after_s": gate["retry_after_s"]}
                from ..worldintel.cache import EvidenceCache
                from ..worldintel.research import Researcher
                from ..worldintel.sources import SourceRegistry
                from ..worldintel.worldsync import sync_answer
                home = str(self.jarvis.config.paths.home)
                cfg = self.jarvis.config.world
                researcher = Researcher(
                    SourceRegistry(),
                    EvidenceCache(home,
                                  max_entries=cfg.cache_entries),
                    max_searches=cfg.max_searches,
                    max_evidence=cfg.max_evidence,
                    budget_s=cfg.budget_s)
                answer = researcher.research(
                    text, active_project=cfg.default_project,
                    topics=list(cfg.topics))
                synced = sync_answer(
                    answer, registry=self.jarvis.world_registry,
                    graph=self.jarvis.graph)
                result = answer.to_dict()
                result["synced"] = synced
                return 200, result
            return 404, {"error": f"no route {method} {path}"}
        except json.JSONDecodeError:
            return 400, {"error": "invalid JSON"}
        except Exception as exc:
            return 500, {"error": f"{type(exc).__name__}: {exc}"}

    # -- operator endpoints (authenticated; validated; audited) --------

    def _approval_decision(self, body: bytes,
                           headers: dict[str, str]
                           ) -> tuple[int, dict[str, Any]]:
        """Decide one pending approval via its single-use token.

        Authority still lives in PolicyEngine: this only carries the
        decision. The approval token itself is the credential (never
        echoed back); the bearer token gates the endpoint. Rate-limited
        against token guessing. Every decision lands in the EventStore.
        """
        import re
        try:
            payload = json.loads(body.decode() or "{}")
        except Exception:
            return 400, {"error": "invalid JSON"}
        if not isinstance(payload, dict):
            return 400, {"error": "object body required"}
        token = str(payload.get("token", ""))[:128]
        approve = payload.get("approve")
        by = str(payload.get("by", "user"))[:40] or "user"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", token):
            return 400, {"error": "malformed approval token"}
        if not isinstance(approve, bool):
            return 400, {"error": "'approve' must be boolean"}
        gate = self._approval_limiter.check(
            str(headers.get("authorization", "") or "anonymous")[:120])
        if not gate["allowed"]:
            return 429, {"error": gate["reason"],
                         "retry_after_s": gate["retry_after_s"]}
        policy = getattr(self.jarvis, "policy", None)
        action = ""
        try:
            records = getattr(policy, "approvals", None)
            if isinstance(records, dict):
                entry = records.get(token)
                if isinstance(entry, dict):
                    action = str(entry.get("action", ""))[:120]
        except Exception:
            action = ""
        try:
            ok = bool(policy.approve(token, by) if approve
                      else policy.deny(token, by))
        except Exception as exc:
            return 500, {"error": f"{type(exc).__name__}"}
        try:
            self.jarvis.events.record(
                "approval.decided",
                {"action": action, "approved": bool(approve and ok),
                 "by": by, "token_hint": token[:8] + "…"})
        except Exception:
            pass
        if not ok:
            return 200, {"ok": False,
                         "reason": "unknown or already redeemed"}
        return 200, {"ok": True, "approved": bool(approve)}

    def _task_action(self, api_path: str, body: bytes
                     ) -> tuple[int, dict[str, Any]]:
        """Operator actions on durable tasks (pause/resume/cancel/
        recover/advance). Same runner the CLI and service use; policy
        (e-stop) is re-checked on every call. Terminal-state violations
        return 409, unknown ids 404 — never silent."""
        import re
        from .board import _scrub
        parts = api_path.split("/")
        if len(parts) != 5 or not parts[3] or not parts[4]:
            return 404, {"error": "no route"}
        task_id, verb = parts[3], parts[4]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", task_id):
            return 400, {"error": "malformed task id"}
        if verb not in ("advance", "pause", "resume", "cancel",
                        "recover"):
            return 404, {"error": "no route"}
        try:
            payload = json.loads(body.decode() or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            return 400, {"error": "invalid JSON"}
        try:
            from ..durable import (DurableRunner, TaskStore,
                                   mesh_executor)
            from ..durable.store import TaskStoreError
            home = str(self.jarvis.config.paths.home)
            runner = DurableRunner(
                TaskStore(home), executor=mesh_executor(self.jarvis),
                policy=getattr(self.jarvis, "policy", None),
                events=getattr(self.jarvis, "events", None))
            if runner.store.corrupt:
                return 500, {"error": "task store fail-closed"}
            if verb == "advance":
                runner.advance(task_id)
            elif verb == "pause":
                runner.pause(task_id)
            elif verb == "resume":
                runner.resume(task_id)
            elif verb == "cancel":
                runner.cancel(task_id, reason=str(
                    payload.get("reason", ""))[:300])
            elif verb == "recover":
                policy = getattr(self.jarvis, "policy", None)
                ok = True
                try:
                    check = getattr(policy, "emergency_stop_engaged",
                                    None)
                    ok = not bool(check()) if callable(check) else True
                except Exception:
                    ok = True
                runner.recover(task_id, policy_ok=ok)
            task = runner.store.get(task_id)
            if task is None:
                return 404, {"error": "unknown task"}
            return 200, _scrub({"task_id": task.task_id,
                                "state": task.state.value,
                                "title": task.title})
        except TaskStoreError as exc:
            text = str(exc)
            if "unknown task" in text:
                return 404, {"error": "unknown task"}
            return 409, {"error": text[:200]}
        except Exception as exc:
            return 500, {"error": f"{type(exc).__name__}"}

    # -- websocket -----------------------------------------------------------
    def _broadcast(self, event: Any) -> None:
        with self._sockets_lock:
            sockets = list(self._sockets)
        dead = []
        for sock in sockets:
            try:
                self._ws_send(sock, {"type": event.type, "payload": event.payload,
                                     "seq": event.seq})
            except OSError:
                dead.append(sock)
        if dead:
            with self._sockets_lock:
                self._sockets = [s for s in self._sockets if s not in dead]

    @staticmethod
    def _ws_send(sock: Any, message: dict[str, Any]) -> None:
        import struct
        data = json.dumps(message, default=str).encode()
        header = bytes([0x81])
        size = len(data)
        if size < 126:
            header += struct.pack("B", size)
        elif size < 65536:
            header += struct.pack("!BH", 126, size)
        else:
            header += struct.pack("!BQ", 127, size)
        sock.sendall(header + data)

    @staticmethod
    def _ws_accept(key: str) -> str:
        # TRIAGED (self-review pattern:weak-crypto): SHA-1 here is
        # mandated by RFC 6455 §1.3 for the WebSocket handshake, not a
        # password hash. Not negotiable, not a finding.
        magic = "258EAFA5-E914-47DA-95CA-C5940E9E065"
        digest = hashlib.sha1((key + magic).encode()).digest()
        return base64.b64encode(digest).decode()

    # -- serving ---------------------------------------------------------------
    def serve_forever(self) -> None:
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "jarvis-os/0.1"

            def _headers(self, code: int, ctype: str = "application/json",
                           extra: dict[str, str] | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()

            def log_message(self, *args: Any) -> None:  # keep quiet
                pass

            def do_GET(self) -> None:  # noqa: N802
                if self.headers.get("Upgrade", "").lower() == "websocket":
                    self._ws()
                    return
                code, payload = api.handle("GET", self.path, b"",
                                           {k.lower(): v for k, v in self.headers.items()})
                nocache = {"Cache-Control": "no-store"}
                if isinstance(payload, dict) and "__html__" in payload:
                    raw = payload["__html__"].encode()
                    self._headers(code, "text/html; charset=utf-8",
                                  nocache)
                    self.wfile.write(raw)
                    return
                body = json.dumps(payload, default=str).encode()
                bare = self.path.split("?", 1)[0]
                self._headers(code, "application/json",
                              nocache if bare in ("/api/board",
                                                  "/api/experience")
                              else None)
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else b""
                code, payload = api.handle("POST", self.path, body,
                                           {k.lower(): v for k, v in self.headers.items()})
                raw = json.dumps(payload, default=str).encode()
                self._headers(code)
                self.wfile.write(raw)

            def _ws(self) -> None:
                if not _ws_token_ok(self.path, api.token or ""):
                    self._headers(403)
                    return
                key = self.headers.get("Sec-WebSocket-Key", "")
                if not key:
                    self._headers(400)
                    return
                accept = api._ws_accept(key)
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                sock = self.request
                with api._sockets_lock:
                    api._sockets.append(sock)
                try:
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                except OSError:
                    pass
                finally:
                    with api._sockets_lock:
                        if sock in api._sockets:
                            api._sockets.remove(sock)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
