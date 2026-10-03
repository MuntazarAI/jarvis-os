"""Host-side Android socket endpoint for the device fabric.

``AndroidSocketHost`` owns a ``FabricServer`` bound to the Android pairing,
authentication, and message-dispatch rules. It plugs into the existing
abstractions without changing them:

- lifecycle/trust: ``AndroidNodeAdapter`` (register/pair/trust/heartbeat)
- authorization: ``DeviceRouter.authorize`` at dispatch time
- result finalization: ``DeviceRouter.finish`` on the correlated reply
- auth bootstrap: ``PairingManager`` (single-use codes) then
  ``DeviceAuthenticator`` challenge-response (HMAC-SHA256, rotating)
- framing/listening: ``FabricServer`` (duplex, synchronous request/reply)

Wire protocol (all frames are validated ``FabricMessage`` JSON):

  client -> host   HELLO                {device_id?, node_id?}
  host   -> client HELLO_REPLY          {host_node, protocol_version}
  client -> host   pair_request         {device_id, code}
  host   -> client pair_result          {ok, pending_token? | error}
  client -> host   pair_status          {device_id, pending_token}
  host   -> client pair_result          {ok:false, pending} |
                                        {ok:true, device_secret, device_id}
  client -> host   auth_challenge       {device_id}
  host   -> client auth_challenge       {device_id, challenge}
  client -> host   heartbeat            {telemetry...} + auth proof
  host   -> client command_request      bare command wire (+ host proof)
  client -> host   command_result       correlated reply to command_request
  client -> host   event                typed android event
  either -> either ERROR                {ok:false, error}

The device secret is transmitted exactly once (inside the approved
``pair_result``) and never logged. Afterwards every device message must
carry HMAC proof (``auth={challenge, response}``); challenges rotate on
each successful verification, so replays fail. Host commands carry
``auth={proof}`` (HMAC of the secret over the message id) so the phone
can verify its paired host — mutual authentication from one secret.

Inbound dispatch is serialized under a host lock: the registry/adapter
are single-threaded designs, and personal-scale concurrency serializes
without loss.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from typing import Any

from ..core.types import now

from .android import (
    ANDROID_EVENTS,
    SAFE_COMMANDS,
    AndroidError,
    AndroidNodeAdapter,
    PairingError,
    validate_command,
)
from .model import PROTOCOL_VERSION, TrustState
from .protocol import FabricMessage, MessageType, make_error
from .socket_transport import (
    AuthError,
    DeviceAuthenticator,
    FabricServer,
)
from .transport import TransportError

HOST_NODE = "core"
PENDING_TOKEN_BYTES = 16
STATUS_FILENAME = "device-transport.json"

#: Bare command wire names the Kotlin client accepts in the
#: ``capability`` field of a COMMAND_REQUEST (its allowlist uses the
#: suffix form: get_battery, vibrate, ...). The host strips the
#: ``device.`` prefix before sending; anything not in this set is
#: refused rather than sent dead on the wire.
ANDROID_WIRE_NAMES = frozenset(
    name.split(".", 1)[1] for name in SAFE_COMMANDS
)


def read_host_status(home: Any) -> dict[str, Any]:
    """Read the listener rendezvous file written by a running host.

    Returns {running, port, pid, peers, updated_at, live} where live is
    True only when the recorded pid is still alive (os.kill(pid, 0)).
    Never raises: missing/stale/corrupt file -> {"running": False, ...}.
    """
    from pathlib import Path
    path = Path(home) / STATUS_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"running": False, "live": False, "detail": "no host running"}
    if not isinstance(raw, dict):
        return {"running": False, "live": False, "detail": "no host running"}
    pid = raw.get("pid", 0)
    try:
        alive = isinstance(pid, int) and pid > 0 and (os.kill(pid, 0) is None)
    except (OSError, ProcessLookupError, PermissionError):
        alive = False
    except Exception:
        alive = False
    raw["live"] = bool(alive)
    if not alive:
        raw["running"] = False
    return raw


class AndroidTransportError(RuntimeError):
    """Raised for host-side transport misuse."""


class AndroidSocketHost:
    def __init__(self, adapter: AndroidNodeAdapter, *,
                 server: FabricServer | None = None,
                 authenticator: DeviceAuthenticator | None = None,
                 host: str = "", port: int = 0,
                 timeout_s: float = 15.0) -> None:
        self.adapter = adapter
        self.authenticator = (
            authenticator
            or DeviceAuthenticator(adapter.fabric.home / "device-keys.json")
        )
        self._pending_approvals: dict[str, tuple[str, float]] = {}  # token -> (device_id, issued_at)
        self._pending_ttl_s = 600.0  # matches the pairing-code TTL
        self._lock = threading.Lock()
        self.server = server or FabricServer(
            self._on_message, host=host, port=port, timeout_s=timeout_s,
        )
        # Let adapter.send_command delegate to this host when the device
        # has a live socket lane. Plain attribute (not ctor param) so the
        # adapter works unchanged without a host.
        adapter.socket_host = self  # type: ignore[attr-defined]

    # -- lifecycle ------------------------------------------------------

    @property
    def status_path(self):  # type: ignore[no-untyped-def]
        return self.adapter.fabric.home / STATUS_FILENAME

    def start(self) -> int:
        port = self.server.start()
        self._write_status_file()
        return port

    def stop(self) -> None:
        self.server.stop()
        try:
            if self.status_path.exists():
                self.status_path.unlink()
        except OSError:
            pass

    def _write_status_file(self) -> None:
        """Publish listener state for short-lived CLI readers.

        The CLI spawns a fresh process per invocation, so it cannot query
        a running host in-process. This small JSON file (port/pid/peers)
        is the rendezvous; readers check pid liveness via os.kill(pid, 0).
        """
        payload = {
            "running": True,
            "port": self.server.bound_port,
            "pid": os.getpid(),
            "peers": sorted(self.server.status().get("peers", {})),
            "updated_at": now(),
        }
        try:
            tmp = self.status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
            tmp.replace(self.status_path)
        except OSError:
            pass

    @property
    def port(self) -> int:
        return self.server.bound_port

    # -- dispatch --------------------------------------------------------

    def _on_message(self, message: FabricMessage, peer: str) -> FabricMessage | None:
        with self._lock:
            return self._dispatch(message, peer)

    def _dispatch(self, message: FabricMessage, peer: str) -> FabricMessage | None:
        mtype = message.message_type
        if mtype == MessageType.HELLO.value:
            return self._hello(message, peer)
        if mtype == MessageType.PAIR_REQUEST.value:
            return self._pair_request(message)
        if mtype == MessageType.PAIR_STATUS.value:
            return self._pair_status(message, peer)
        if mtype == MessageType.AUTH_CHALLENGE.value:
            return self._auth_challenge(message)
        # Everything below requires HMAC proof of a bound device.
        device_id = self._authed_device(message, peer)
        if device_id is None:
            # Explicit marker: the phone must stop retrying credentials
            # (wrong secret, revoked trust, unknown device) but keep the
            # socket for transient failures, which use plain errors.
            reply = make_error(message.sender_node, HOST_NODE,
                               "authentication required",
                               correlation_id=message.message_id)
            payload = dict(reply.payload if isinstance(reply.payload, dict) else {})
            payload["auth_failed"] = True
            reply.payload = payload
            return reply
        if mtype == MessageType.HEARTBEAT.value:
            return self._heartbeat(device_id, message)
        if mtype == MessageType.EVENT.value:
            return self._ingest(device_id, message)
        if mtype == MessageType.COMMAND_RESULT.value:
            return self._result(device_id, message)
        return make_error(message.sender_node, HOST_NODE,
                          f"unsupported message: {mtype}",
                          correlation_id=message.message_id)

    # -- bootstrap ---------------------------------------------------------

    def _hello(self, message: FabricMessage, peer: str) -> FabricMessage:
        payload = message.payload if isinstance(message.payload, dict) else {}
        node_id = str(payload.get("node_id", "") or message.sender_node)
        if node_id:
            self.server.bind_node(peer, node_id)
        return FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id,
            payload={"ok": True, "hello": True, "host_node": HOST_NODE,
                     "protocol_version": PROTOCOL_VERSION},
        )

    def _sweep_pending(self) -> None:
        """Drop expired pending-approval tokens (bounded memory)."""
        cutoff = now() - self._pending_ttl_s
        stale = [t for t, (_, issued) in self._pending_approvals.items()
                 if issued < cutoff]
        for token in stale:
            del self._pending_approvals[token]

    def _pair_request(self, message: FabricMessage) -> FabricMessage:
        payload = message.payload if isinstance(message.payload, dict) else {}
        device_id = str(payload.get("device_id", ""))
        code = str(payload.get("code", ""))
        node_id = str(payload.get("node_id", "") or message.sender_node)
        try:
            # Code verification only — trust stays pending until a human
            # approves via trust_android.
            state = self.adapter.pair_request_approval(device_id, code,
                                                       node_id=node_id)
        except (PairingError, AndroidError) as exc:
            return make_error(message.sender_node, HOST_NODE,
                              f"pairing failed: {exc}",
                              correlation_id=message.message_id)
        token = secrets.token_hex(PENDING_TOKEN_BYTES)
        self._sweep_pending()
        self._pending_approvals[token] = (device_id, now())
        return FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id,
            payload={"ok": True, "pair": "pending",
                     "pending_token": token,
                     "trust": state.get("trust", ""),
                     "detail": "waiting for explicit host approval"},
        )

    def _pair_status(self, message: FabricMessage,
                     peer: str) -> FabricMessage:
        payload = message.payload if isinstance(message.payload, dict) else {}
        device_id = str(payload.get("device_id", ""))
        token = str(payload.get("pending_token", ""))
        self._sweep_pending()
        bound = self._pending_approvals.get(token)
        if not token or bound is None or bound[0] != device_id:
            return make_error(message.sender_node, HOST_NODE,
                              "unknown or reused pending token",
                              correlation_id=message.message_id)
        # Refresh from disk: approval may have come from a short-lived CLI
        # process (trust_android) while this host runs. load() merges
        # per-device state and never deletes, so this is safe mid-session.
        try:
            self.adapter.fabric.registry.load()
        except Exception:
            pass
        try:
            device = self.adapter.fabric.registry.require(device_id)
        except Exception:
            return make_error(message.sender_node, HOST_NODE,
                              "unknown device",
                              correlation_id=message.message_id)
        if device.trust != TrustState.TRUSTED:
            return FabricMessage(
                sender_node=HOST_NODE, recipient_node=message.sender_node,
                message_type=MessageType.EVENT.value,
                correlation_id=message.message_id,
                payload={"ok": False, "pair": "pending",
                         "detail": "waiting for explicit host approval"},
            )
        # Approved: issue the device secret exactly once.
        del self._pending_approvals[token]
        secret = self.authenticator.issue(device_id)
        self.server.bind_node(peer, device.node_id or message.sender_node,
                              device_id=device_id)
        self._write_status_file()
        try:
            self.adapter._remember(f"Android node paired: {device.name}")
        except Exception:
            pass
        return FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id,
            payload={"ok": True, "pair": "approved", "device_id": device_id,
                     "device_secret": secret},
        )

    def _auth_challenge(self, message: FabricMessage) -> FabricMessage:
        payload = message.payload if isinstance(message.payload, dict) else {}
        device_id = str(payload.get("device_id", ""))
        try:
            challenge = self.authenticator.begin_challenge(device_id)
        except AuthError:
            return make_error(message.sender_node, HOST_NODE,
                              "unknown device",
                              correlation_id=message.message_id)
        return FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id,
            payload={"ok": True, "device_id": device_id,
                     "challenge": challenge},
        )

    # -- authenticated lane -----------------------------------------------

    def _authed_device(self, message: FabricMessage,
                       peer: str) -> str | None:
        auth = message.auth if isinstance(message.auth, dict) else {}
        challenge = str(auth.get("challenge", ""))
        response = str(auth.get("response", ""))
        if not challenge or not response:
            return None
        payload = message.payload if isinstance(message.payload, dict) else {}
        device_id = str(payload.get("device_id", ""))
        if not device_id:
            _, bound = self.server.node_for_peer(peer)
            device_id = bound
        if not device_id:
            return None
        try:
            fresh = self.authenticator.verify_and_rotate(device_id, challenge,
                                                         response)
        except AuthError:
            return None
        if fresh is None:
            return None
        message.auth["next_challenge"] = fresh
        try:
            device = self.adapter.fabric.registry.require(device_id)
        except Exception:
            return None
        if device.trust != TrustState.TRUSTED:
            return None
        self.server.bind_node(peer, message.sender_node or device.node_id,
                              device_id=device_id)
        # An HMAC-proven socket peer IS connected: reuse the adapter's
        # presence path (mark_online + drain) exactly once per session.
        if not self.adapter.is_connected(device_id):
            try:
                self.adapter.connect(device_id)
            except (AndroidError, PairingError):
                return None
        return device_id

    def _heartbeat(self, device_id: str,
                   message: FabricMessage) -> FabricMessage:
        payload = message.payload if isinstance(message.payload, dict) else {}
        telemetry = {k: v for k, v in payload.items() if k != "device_id"}
        try:
            info = self.adapter.heartbeat(device_id, telemetry)
        except (AndroidError, PairingError) as exc:
            return make_error(message.sender_node, HOST_NODE,
                              f"heartbeat refused: {exc}",
                              correlation_id=message.message_id)
        out: dict[str, Any] = {"ok": True,
                               "lifecycle": info.get("lifecycle", "")}
        nxt = (message.auth or {}).get("next_challenge")
        if nxt:
            out["next_challenge"] = nxt
        return FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id, payload=out,
        )

    def _ingest(self, device_id: str, message: FabricMessage) -> FabricMessage:
        payload = message.payload if isinstance(message.payload, dict) else {}
        name = str(payload.get("event", ""))
        if name not in ANDROID_EVENTS:
            return make_error(message.sender_node, HOST_NODE,
                              f"unknown event: {name}",
                              correlation_id=message.message_id)
        data = {k: v for k, v in payload.items()
                if k not in ("event", "device_id")}
        try:
            result = self.adapter.ingest_event(device_id, name,
                                               payload=data)
        except (AndroidError, PairingError) as exc:
            return make_error(message.sender_node, HOST_NODE,
                              f"event refused: {exc}",
                              correlation_id=message.message_id)
        return FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id,
            payload={"ok": True, "dots": result.get("dots", [])},
        )

    def _result(self, device_id: str, message: FabricMessage) -> FabricMessage:
        # Unsolicited results (no live request lane) are still recorded
        # through the router so nothing executes silently.
        payload = message.payload if isinstance(message.payload, dict) else {}
        router = self.adapter.fabric.router
        try:
            device = self.adapter.fabric.registry.require(device_id)
        except Exception:
            return make_error(message.sender_node, HOST_NODE,
                              "unknown device",
                              correlation_id=message.message_id)
        reply = FabricMessage(
            sender_node=message.sender_node, recipient_node=HOST_NODE,
            message_type=MessageType.COMMAND_RESULT.value,
            correlation_id=(message.correlation_id
                            or str(payload.get("for", ""))),
            capability=str(payload.get("capability", "")),
            payload=dict(payload),
        )
        stub = FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.COMMAND_REQUEST.value,
            capability=str(payload.get("capability", "")),
            payload={"device_id": device_id},
        )
        router.finish("socket-host", device,
                      str(payload.get("capability", "")), stub, reply)
        return FabricMessage(
            sender_node=HOST_NODE, recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id,
            payload={"ok": True, "recorded": True},
        )

    # -- host-initiated dispatch --------------------------------------------

    def has_lane(self, device_id: str) -> bool:
        """True when the device currently holds a live socket lane.

        The lane must carry the HMAC-bound device_id, not merely a
        hello-claimed node_id: an unauthenticated client can claim any
        node name, so node-only matches are never routable.
        """
        try:
            device = self.adapter.fabric.registry.require(device_id)
        except Exception:
            return False
        lane = self.server.peer_for_node(device.node_id or device.device_id)
        return lane is not None and lane.device_id == device_id

    def send_command(self, actor: str, device_id: str, command: str,
                     args: dict[str, Any] | None = None, *,
                     approval_token: str = "",
                     timeout_s: float = 15.0) -> dict[str, Any]:
        """Authorize via the router, deliver over the socket lane, and wait
        for the correlated ``command_result``. Returns the finished result.

        Takes the typed ``device.*`` command (like adapter.send_command).
        Authorization runs on the declared ``device.*`` capability; the
        wire carries the bare command name the Kotlin allowlist accepts.
        """
        from .android import AndroidCommandError
        router = self.adapter.fabric.router
        try:
            checked = validate_command(command, args)
        except AndroidCommandError as exc:
            return router._deny(actor, device_id, command,
                                dict(args or {}), [str(exc)])
        capability = checked["capability"]
        wire = checked["command"].split(".", 1)[1]
        if wire not in ANDROID_WIRE_NAMES:
            return router._deny(actor, device_id, command,
                                checked["args"],
                                [f"command has no Android wire name: {command}"])
        gate = router.authorize(actor, device_id, capability,
                                args=checked["args"],
                                approval_token=approval_token)
        if not gate["authorized"]:
            return router._deny(actor, device_id, command,
                                checked["args"], gate["reasons"],
                                decision=gate.get("decision"),
                                approval_token=gate.get("approval_token"))
        device = gate["device"]
        lane = self.server.peer_for_node(device.node_id or device.device_id)
        if lane is None or lane.device_id != device_id:
            # No HMAC-bound lane: a hello-only lane claiming this node_id
            # is not routable (spoofable by any unauthenticated client).
            return router._deny(actor, device_id, command,
                                 checked["args"],
                                 ["device has no live socket lane"])
        message = router.build_command_message(actor, device, capability,
                                               checked["args"])
        # The Kotlin allowlist matches bare command names; the declared
        # device.* capability stays in the audit trail via finish().
        message.capability = wire
        message.validate()
        # Mutual auth: prove host knowledge of the device secret so the
        # phone can verify this command came from its paired host.
        try:
            message.auth = {"proof": self.authenticator.prove(
                device_id, message.message_id)}
        except AuthError:
            return router._deny(actor, device_id, command,
                                checked["args"],
                                ["device has no authentication key"])
        try:
            reply = self.server.request(lane.peer, message,
                                        timeout_s=timeout_s)
        except TransportError as exc:
            return router._deny(actor, device_id, command,
                                checked["args"],
                                [f"lane delivery failed: {exc}"])
        return router.finish(actor, device, capability, message, reply)

    def status(self) -> dict[str, Any]:
        info = self.server.status()
        info["pending_approvals"] = len(self._pending_approvals)
        return info
