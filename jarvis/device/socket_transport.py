"""Real network transport for the device fabric.

Length-prefixed JSON framing over TCP, usable for LAN, hostnames, and
Tailscale names alike — the transport never assumes an address family or
subnet. Layout::

    +------------------+---------------------------+
    | u32 BE length N  | N bytes UTF-8 JSON        |
    +------------------+---------------------------+

Bounds: frames larger than ``MAX_FRAME_BYTES`` (256 KiB) are rejected
before allocation completes; payloads are additionally bound by the
protocol's own 64 KiB rule on validation.

Roles:

- ``SocketTransport`` — client side (Android node, tests). Blocking
  request/reply ``send()`` implementing the ``Transport`` interface, so
  ``DeviceRouter`` works unchanged.
- ``FabricServer`` — host side listener. Accepts connections on a
  listener thread, reads frames on one thread per connection, validates
  every message, dispatches to a handler, and writes the reply.
- ``DeviceAuthenticator`` — challenge-response authentication
  (HMAC-SHA256 over a per-device secret). Secrets live in a 0600
  ``device-keys.json`` file, are never transmitted, never logged, and
  only hashed outcomes reach the audit trail.

Pairing over the socket reuses ``PairingManager`` (single-use 6-digit
codes): ``pair_request`` confirms the code and returns a pending token;
the user approves via CLI trust; the client polls ``pair_status`` and
receives its device secret exactly once. Wrong/expired/reused codes fail;
replays fail (single-use + challenge freshness).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import struct
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from ..core.types import now
from .identity import UNVERIFIED_TRANSPORTS
from .protocol import FabricMessage, MessageType, ProtocolError, make_error
from .transport import Transport, TransportError

HEADER = struct.Struct("!I")
MAX_FRAME_BYTES = 256 * 1024
DEFAULT_TIMEOUT_S = 15.0
MAX_CONNECTIONS = 16
CHALLENGE_BYTES = 32
KEY_FILE_MODE = 0o600


class FramingError(ValueError):
    """Raised when a frame violates size/shape bounds."""


class AuthError(ValueError):
    """Raised for authentication failures (no secret detail inside)."""


def encode_frame(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise FramingError(f"frame too large: {len(raw)} bytes")
    return HEADER.pack(len(raw)) + raw


def decode_frames(buffer: bytearray, limit: int = 0) -> list[dict[str, Any]]:
    """Pull complete frames off the front of buffer. Malformed -> raise.

    ``limit`` caps how many frames are pulled (0 = no cap); unpulled
    bytes stay buffered for the next call. Callers that process one
    message per loop iteration must pass ``limit=1`` — otherwise
    pipelined frames are silently discarded.
    """
    out: list[dict[str, Any]] = []
    while True:
        if limit and len(out) >= limit:
            return out
        if len(buffer) < HEADER.size:
            return out
        (size,) = HEADER.unpack_from(buffer)
        if size > MAX_FRAME_BYTES:
            raise FramingError(f"frame too large: {size} bytes")
        if len(buffer) < HEADER.size + size:
            return out
        raw = bytes(buffer[HEADER.size:HEADER.size + size])
        del buffer[:HEADER.size + size]
        try:
            item = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FramingError(f"bad frame payload: {exc}") from exc
        if not isinstance(item, dict):
            raise FramingError("frame payload must be an object")
        out.append(item)


def _read_frame(conn: socket.socket, buffer: bytearray,
                timeout_s: float) -> dict[str, Any]:
    conn.settimeout(timeout_s)
    while True:
        frames = decode_frames(buffer, limit=1)
        if frames:
            return frames[0]
        try:
            chunk = conn.recv(65536)
        except socket.timeout as exc:
            raise TransportError("read timed out") from exc
        except OSError as exc:
            raise TransportError("connection lost") from exc
        if not chunk:
            raise TransportError("connection closed by peer")
        buffer += chunk


class SocketTransport(Transport):
    """Blocking TCP client transport implementing ``Transport``.

    Without ``on_request`` (default), ``send()`` is strict request/reply
    on the calling thread. With ``on_request`` set, a background reader
    thread runs instead: replies complete outstanding ``send()`` calls by
    correlation id, and unsolicited server requests go to ``on_request``
    (its return value is sent back as the reply). The latter is the mode
    a real node uses — the host pushes COMMAND_REQUEST frames at will.
    """

    name = "socket"
    network_name = None

    def __init__(self, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self.peer: str = ""
        self.sent_count = 0
        self._on_request: Callable[[FabricMessage], FabricMessage | None] | None = None
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._pending: dict[str, dict[str, Any]] = {}
        self._pending_cap = 32

    def connect(self, host: str, port: int, *,
                timeout_s: float | None = None,
                on_request: Callable[[FabricMessage], FabricMessage | None] | None = None) -> None:
        if self._sock is not None:
            raise TransportError("already connected")
        wait = timeout_s if timeout_s is not None else self.timeout_s
        sock = socket.create_connection((host, port), timeout=wait)
        # Fail fast on dead peers instead of hanging forever.
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._buffer = bytearray()
        self.peer = f"{host}:{port}"
        if on_request is not None:
            self._on_request = on_request
            self._reader_stop.clear()
            self._reader = threading.Thread(target=self._reader_loop,
                                            name="fabric-client-reader",
                                            daemon=True)
            self._reader.start()

    def _reader_loop(self) -> None:
        assert self._sock is not None
        while not self._reader_stop.is_set():
            try:
                item = _read_frame(self._sock, self._buffer, 1.0)
            except TransportError:
                if self._reader_stop.is_set():
                    return
                continue
            try:
                message = FabricMessage.from_dict(item).validate()
            except ProtocolError:
                continue  # malformed server frames never crash the node
            with self._lock:
                slot = self._pending.get(message.correlation_id or "")
            if slot is not None:
                slot["reply"] = item
                slot["event"].set()
                continue
            if self._on_request is None:
                continue
            try:
                reply = self._on_request(message)
            except Exception:
                reply = None
            if reply is None:
                continue
            reply.correlation_id = reply.correlation_id or message.message_id
            try:
                with self._lock:
                    if self._sock is None:
                        return
                    self._sock.sendall(encode_frame(reply.to_dict()))
            except (OSError, FramingError, ProtocolError):
                return

    def send(self, message: FabricMessage) -> FabricMessage | None:
        message.validate()
        if self._reader is not None:
            return self._send_duplex(message)
        with self._lock:
            if self._sock is None:
                raise TransportError("not connected")
            try:
                self._sock.sendall(encode_frame(message.to_dict()))
                reply = _read_frame(self._sock, self._buffer, self.timeout_s)
            except (OSError, FramingError) as exc:
                self.close()
                raise TransportError(f"send failed: {exc}") from exc
        self.sent_count += 1
        try:
            return FabricMessage.from_dict(reply).validate()
        except ProtocolError as exc:
            raise TransportError(f"bad reply: {exc}") from exc

    def _send_duplex(self, message: FabricMessage) -> FabricMessage:
        slot: dict[str, Any] = {"event": threading.Event(), "reply": None}
        with self._lock:
            if self._sock is None:
                raise TransportError("not connected")
            if len(self._pending) >= self._pending_cap:
                raise TransportError("too many outstanding requests")
            self._pending[message.message_id] = slot
            try:
                self._sock.sendall(encode_frame(message.to_dict()))
            except OSError as exc:
                self._pending.pop(message.message_id, None)
                raise TransportError(f"send failed: {exc}") from exc
        if not slot["event"].wait(self.timeout_s):
            with self._lock:
                self._pending.pop(message.message_id, None)
            raise TransportError("reply timed out")
        self.sent_count += 1
        try:
            return FabricMessage.from_dict(slot["reply"]).validate()
        except ProtocolError as exc:
            raise TransportError(f"bad reply: {exc}") from exc

    def close(self) -> None:
        self._reader_stop.set()
        sock, self._sock = self._sock, None
        self.peer = ""
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        reader, self._reader = self._reader, None
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2.0)

    def status(self) -> dict[str, Any]:
        info = super().status()
        info["connected"] = self._sock is not None
        info["peer"] = self.peer
        info["sent"] = self.sent_count
        return info


PeerHandler = Callable[[FabricMessage, str], FabricMessage | None]
AuthChecker = Callable[[FabricMessage, str], bool]


class ServerPeer:
    """One accepted connection: duplex request/reply plus inbound dispatch."""

    def __init__(self, peer: str, conn: socket.socket) -> None:
        self.peer = peer
        self.conn = conn
        self.node_id = ""
        self.device_id = ""
        self.lock = threading.Lock()
        self.pending: dict[str, dict[str, Any]] = {}
        self.pending_cap = 32
        self.connected_at = now()
        self.last_seen = self.connected_at
        self.messages = 0

    def request(self, message: FabricMessage,
                timeout_s: float) -> FabricMessage:
        """Send a request on this connection, await the correlated reply."""
        message.validate()
        slot: dict[str, Any] = {"event": threading.Event(), "reply": None}
        with self.lock:
            if len(self.pending) >= self.pending_cap:
                raise TransportError("peer has too many outstanding requests")
            self.pending[message.message_id] = slot
            try:
                self.conn.sendall(encode_frame(message.to_dict()))
            except OSError as exc:
                self.pending.pop(message.message_id, None)
                raise TransportError(f"peer send failed: {exc}") from exc
        if not slot["event"].wait(timeout_s):
            with self.lock:
                self.pending.pop(message.message_id, None)
            raise TransportError("peer reply timed out")
        reply = slot["reply"]
        try:
            return FabricMessage.from_dict(reply).validate()
        except ProtocolError as exc:
            raise TransportError(f"bad peer reply: {exc}") from exc

    def _complete(self, correlation_id: str,
                  frame: dict[str, Any]) -> bool:
        with self.lock:
            slot = self.pending.get(correlation_id)
        if slot is None:
            return False
        slot["reply"] = frame
        slot["event"].set()
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer": self.peer,
            "node_id": self.node_id,
            "device_id": self.device_id,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "messages": self.messages,
            "outstanding": len(self.pending),
        }


class FabricServer:
    """Host-side TCP listener with full-duplex validated messaging.

    Inbound frames without a matching correlation id go to ``handler`` and
    get a reply. Frames whose correlation id matches an outstanding
    ``request()`` complete it instead. ``auth`` — when set — runs *before*
    the handler; rejected messages get an ``error`` reply and the failure
    is counted, never logged with secrets.
    """

    def __init__(self, handler: PeerHandler, *, host: str = "",
                 port: int = 0, auth: AuthChecker | None = None,
                 max_connections: int = MAX_CONNECTIONS,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.handler = handler
        self.host = host
        self.port = port
        self.auth = auth
        self.max_connections = max_connections
        self.timeout_s = timeout_s
        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._conn_threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.peers: dict[str, ServerPeer] = {}
        self.accepted = 0
        self.rejected = 0
        self.handled = 0

    @property
    def bound_port(self) -> int:
        if self._sock is None:
            return 0
        return self._sock.getsockname()[1]

    def start(self) -> int:
        if self._sock is not None:
            return self.bound_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(self.max_connections)
        sock.settimeout(0.5)
        self._sock = sock
        self._stop.clear()
        self._accept_thread = threading.Thread(target=self._accept_loop,
                                               name="fabric-accept",
                                               daemon=True)
        self._accept_thread.start()
        return self.bound_port

    def request(self, peer: str, message: FabricMessage,
                  timeout_s: float | None = None) -> FabricMessage:
        """Host-initiated request to a connected peer (duplex)."""
        with self._lock:
            target = self.peers.get(peer)
        if target is None:
            raise TransportError(f"peer not connected: {peer}")
        try:
            return target.request(message,
                                  timeout_s if timeout_s is not None
                                  else self.timeout_s)
        except TransportError:
            self.drop_peer(peer)
            raise

    def peer_for_node(self, node_id: str) -> ServerPeer | None:
        # Prefer the most recently seen lane: a reconnecting device leaves
        # a stale lane behind until the dead socket is reaped.
        best: ServerPeer | None = None
        with self._lock:
            for target in self.peers.values():
                if target.node_id == node_id and (
                        best is None or target.last_seen >= best.last_seen):
                    best = target
        return best

    def node_for_peer(self, peer: str) -> tuple[str, str]:
        """Return (node_id, device_id) bound to a peer lane, or ("", "")."""
        with self._lock:
            target = self.peers.get(peer)
            if target is None:
                return "", ""
            return target.node_id, target.device_id

    def bind_node(self, peer: str, node_id: str, device_id: str = "") -> bool:
        with self._lock:
            target = self.peers.get(peer)
            if target is None:
                return False
            target.node_id = node_id
            if device_id:
                target.device_id = device_id
            return True

    def drop_peer(self, peer: str) -> bool:
        with self._lock:
            target = self.peers.pop(peer, None)
        if target is None:
            return False
        try:
            target.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            target.conn.close()
        except OSError:
            pass
        return True

    def sweep_idle(self, idle_timeout_s: float) -> list[str]:
        """Drop connections silent longer than the timeout. Returns peers."""
        stale: list[str] = []
        cutoff = now() - idle_timeout_s
        with self._lock:
            for peer, target in self.peers.items():
                if target.last_seen < cutoff and not target.pending:
                    stale.append(peer)
        for peer in stale:
            self.drop_peer(peer)
        return stale

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        for thread in self._conn_threads:
            thread.join(timeout=2.0)
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)
            self._accept_thread = None
        with self._lock:
            self.peers = {}

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                if len(self.peers) >= self.max_connections:
                    self.rejected += 1
                    try:
                        conn.close()
                    except OSError:
                        pass
                    continue
                peer = f"{addr[0]}:{addr[1]}"
                self.peers[peer] = ServerPeer(peer, conn)
                self.accepted += 1
            thread = threading.Thread(target=self._serve, args=(conn, peer),
                                      name=f"fabric-conn-{peer}", daemon=True)
            with self._lock:
                self._conn_threads.append(thread)
            thread.start()

    def _serve(self, conn: socket.socket, peer: str) -> None:
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                try:
                    item = _read_frame(conn, buffer, self.timeout_s)
                except TransportError:
                    break
                except FramingError:
                    # Poisoned buffer (oversize/garbage): count and drop
                    # the connection cleanly instead of killing the thread.
                    self.rejected += 1
                    break
                try:
                    message = FabricMessage.from_dict(item).validate()
                except ProtocolError as exc:
                    self.rejected += 1
                    try:
                        conn.sendall(encode_frame(make_error(
                            "", "core", f"rejected: {exc}",
                        ).to_dict()))
                    except OSError:
                        break
                    continue
                with self._lock:
                    target = self.peers.get(peer)
                if target is not None and message.correlation_id:
                    # Reply to a host-initiated duplex request.
                    if target._complete(message.correlation_id, item):
                        target.last_seen = now()
                        continue
                if self.auth is not None:
                    try:
                        allowed = self.auth(message, peer)
                    except Exception:
                        allowed = False
                    if not allowed:
                        self.rejected += 1
                        try:
                            conn.sendall(encode_frame(make_error(
                                message.sender_node, "core",
                                "authentication failed",
                                correlation_id=message.message_id,
                            ).to_dict()))
                        except OSError:
                            break
                        continue
                try:
                    reply = self.handler(message, peer)
                except Exception as exc:  # handler bugs must not kill the server
                    reply = make_error(message.sender_node, "core",
                                       f"handler failed: {exc}",
                                       correlation_id=message.message_id)
                self.handled += 1
                if target is not None:
                    target.messages += 1
                    target.last_seen = now()
                if reply is not None:
                    reply.correlation_id = reply.correlation_id or message.message_id
                    try:
                        if target is not None:
                            with target.lock:
                                conn.sendall(encode_frame(reply.to_dict()))
                        else:
                            conn.sendall(encode_frame(reply.to_dict()))
                    except (OSError, FramingError, ProtocolError):
                        break
        finally:
            with self._lock:
                self.peers.pop(peer, None)
            try:
                conn.close()
            except OSError:
                pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            peers = {k: v.to_dict() for k, v in self.peers.items()}
        return {
            "transport": "socket-server",
            "listening": self._sock is not None,
            "port": self.bound_port,
            "peers": peers,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "handled": self.handled,
        }


class DeviceAuthenticator:
    """Challenge-response auth with per-device secrets.

    Secrets are generated server-side, stored in a 0600 JSON file, shown
    to the approver exactly once, and never transmitted or logged. Proof
    is HMAC-SHA256(secret, server-challenge); challenges are single-use
    with a short TTL, so replays fail.
    """

    def __init__(self, path: str | Path, *, challenge_ttl_s: float = 60.0) -> None:
        self.path = Path(path)
        self.challenge_ttl_s = challenge_ttl_s
        self._secrets: dict[str, str] = {}
        self._challenges: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self.load()

    def issue(self, device_id: str) -> str:
        """Create (or rotate) a device secret. Returns it ONCE for delivery."""
        secret = secrets.token_urlsafe(32)
        with self._lock:
            self._secrets[device_id] = secret
        self.save()
        return secret

    def revoke_key(self, device_id: str) -> bool:
        with self._lock:
            removed = self._secrets.pop(device_id, None) is not None
        if removed:
            self.save()
        return removed

    def has_key(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._secrets

    def begin_challenge(self, device_id: str) -> str:
        """Server-side: mint a challenge for a device (rotates if stale)."""
        with self._lock:
            if device_id not in self._secrets:
                raise AuthError("unknown device")
        return self.outstanding(device_id)

    @staticmethod
    def answer(secret: str, challenge: str) -> str:
        """Client-side: prove possession without revealing the secret."""
        return hmac.new(secret.encode("utf-8"), challenge.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def outstanding(self, device_id: str) -> str:
        """Get-or-mint the current challenge awaiting proof."""
        with self._lock:
            pending = self._challenges.get(device_id)
            if pending is not None:
                challenge, issued_at = pending
                if now() - issued_at <= self.challenge_ttl_s:
                    return challenge
            challenge = secrets.token_hex(CHALLENGE_BYTES)
            self._challenges[device_id] = (challenge, now())
            return challenge

    def verify_and_rotate(self, device_id: str, challenge: str,
                          response: str) -> str | None:
        """Constant-time proof check. On success the challenge is rotated
        (single-use: replays fail) and the fresh challenge is returned for
        chaining the next message. On failure returns None."""
        with self._lock:
            secret = self._secrets.get(device_id)
            pending = self._challenges.get(device_id)
        if secret is None or pending is None:
            return None
        expected_challenge, issued_at = pending
        if now() - issued_at > self.challenge_ttl_s:
            return None
        if not hmac.compare_digest(challenge, expected_challenge):
            return None
        expected = hmac.new(secret.encode("utf-8"),
                            expected_challenge.encode("utf-8"),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(response, expected):
            return None
        fresh = secrets.token_hex(CHALLENGE_BYTES)
        with self._lock:
            self._challenges[device_id] = (fresh, now())
        return fresh

    # Kept for compatibility; prefer verify_and_rotate (single-use).
    def verify(self, device_id: str, challenge: str,
               response: str) -> bool:
        return self.verify_and_rotate(device_id, challenge,
                                       response) is not None

    def prove(self, device_id: str, challenge: str) -> str:
        """Host-side: prove knowledge of the device secret (mutual auth)."""
        with self._lock:
            secret = self._secrets.get(device_id)
        if not secret:
            raise AuthError("unknown device")
        return self.answer(secret, challenge)

    def auth_checker(self, resolve_device: Callable[[str], str]) -> AuthChecker:
        """Build a ``FabricServer`` auth callback.

        ``resolve_device`` maps ``message.sender_node`` -> device_id (or ""
        when unknown). Pairing/poll messages for not-yet-trusted nodes must
        be allowed by the caller's own gate; this checker only verifies
        HMAC proof carried in ``message.auth``.
        """
        def _check(message: FabricMessage, peer: str) -> bool:
            device_id = resolve_device(message.sender_node)
            if not device_id:
                return False
            auth = message.auth if isinstance(message.auth, dict) else {}
            challenge = str(auth.get("challenge", ""))
            response = str(auth.get("response", ""))
            if not challenge or not response:
                return False
            return self.verify(device_id, challenge, response)
        return _check

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".device-keys-",
                                   dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"secrets": self._secrets}, handle,
                          indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        try:
            os.chmod(self.path, KEY_FILE_MODE)
        except OSError:
            pass

    def load(self) -> int:
        if not self.path.exists():
            return 0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(raw, dict):
            return 0
        with self._lock:
            for device_id, secret in (raw.get("secrets") or {}).items():
                if isinstance(secret, str) and secret:
                    self._secrets[device_id] = secret
        return len(self._secrets)


def is_verified_transport(name: str) -> bool:
    """True when a transport can prove sender identity (not in-process)."""
    return name not in UNVERIFIED_TRANSPORTS


def verified_auth_context(method: str, *, by: str = "",
                          note: str = "") -> dict[str, Any]:
    from .identity import AuthContext
    return AuthContext(method=method, verified=True, verified_by=by,
                       verified_at=now(), note=note[:200]).to_dict()


__all__ = [
    "AuthError",
    "DeviceAuthenticator",
    "FabricServer",
    "FramingError",
    "ServerPeer",
    "SocketTransport",
    "CHALLENGE_BYTES",
    "DEFAULT_TIMEOUT_S",
    "MAX_CONNECTIONS",
    "MAX_FRAME_BYTES",
    "decode_frames",
    "encode_frame",
    "is_verified_transport",
    "verified_auth_context",
]
