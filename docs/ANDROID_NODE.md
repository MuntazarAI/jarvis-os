# Android JARVIS Node (3.9)

An Android phone joins the JARVIS device fabric as an ordinary node: it
registers, pairs explicitly, declares capabilities, sends heartbeats and
telemetry, receives strictly allowlisted commands, and emits a closed set
of typed events. Everything flows through the 3.8 fabric (`jarvis/device/`);
the phone is never special-cased.

## Architecture

```
Android phone (Kotlin, android/)          JARVIS core (Python, jarvis/device/)
┌──────────────────────────────┐          ┌───────────────────────────────────┐
│ FabricProtocol.kt            │  msgs    │ protocol.py (FabricMessage)       │
│ NodeIdentityStore.kt         │◄────────►│ model.py + identity.py            │
│ Capabilities.kt              │  caps    │ capabilities.py                   │
│ Telemetry.kt                 │  tele    │ telemetry.py                      │
│ Commands.kt (SAFE allowlist) │  cmds    │ router.py (PolicyEngine-gated)    │
│ FabricLink.kt + InProcessLink│  link    │ transport.py (in-process)         │
│ NodeService.kt (no autostart)│          │ android.py (AndroidNodeAdapter)   │
│ MainActivity.kt (honest UI)  │          └───────────────────────────────────┘
└──────────────────────────────┘
```

The Kotlin side mirrors the protocol with strict validation (unknown /
future-version messages are rejected, never guessed). The Python side
(`AndroidNodeAdapter` in `jarvis/device/android.py`) wraps `DeviceFabric`
and adds: pairing, permission negotiation, command queueing for offline
nodes, and event ingestion — all reusing 3.8 primitives.

`android/` is a source skeleton, not a compiled app: no APK is built here,
no network transport exists yet, and nothing here has run on a phone.

## Server-side adapter (`jarvis/device/android.py`)

Created with the 11 Android capabilities, 5-state permission model, 14
typed SAFE commands, closed event set, pairing manager, and bounded
expiring outbound queue; exposes `AndroidNodeAdapter` plus a `doctor()`
matching the fabric's check conventions.

## Capabilities (11, typed)

`device.info`, `device.status`, `device.notifications`,
`device.battery`, `device.network`, `device.location`,
`device.camera`, `device.microphone`, `device.screen`,
`device.input`, `device.sensors`.

Each capability maps to an Android runtime permission
(`PERMISSION_FOR_CAPABILITY`). Capability ≠ permission ≠ authorization:
declaring a capability only advertises it; the Android OS grants the
permission (user-controlled); the fabric's `PolicyEngine` authorizes each
routed command. All three must align before anything executes.

Permission states: `available`, `denied`, `not_requested`, `restricted`,
`unavailable`.

## SAFE command allowlist (14 typed commands)

Read-only getters plus bounded actions: `get_info`, `get_status`,
`get_battery`, `get_network`, `get_location`, `get_sensors`,
`show_notification`, `open_app`, `open_url`, `vibrate`, `set_volume`,
`capture_photo`, `start_sensor_stream`, `stop_sensor_stream`.

Validators reject (never clamp): bad URLs (via `is_safe_url`), bad package
names, bad durations/volumes. There is no shell, no eval, no filesystem
access, no ADB. Every command goes through `DeviceRouter.route`
(PolicyEngine → trust/lifecycle/capability checks → transport).

## Pairing (explicit, never auto-trust)

`register_android` (DISCOVERED→REGISTERED, trust pending) issues a 6-digit
code; `pair` confirms it (HMAC `compare_digest`, 600 s TTL, 5 attempts,
then `set_trust` → TRUSTED); `unregister_device` unpairs. Pending pairings
persist to `home/android-pairings.json` as **SHA-256 hashes only** — the
plaintext code exists only in the `begin()` return value — so codes survive
core restarts without storing secrets. Future transports (mTLS, Ed25519,
QR, token) are prepared for via `AuthContext`, not faked.

## Presence, telemetry, offline queue

Heartbeats update `last_seen` and flip TRUSTED/OFFLINE → ONLINE; only
`connect()`ed nodes send them. `sweep()` marks timed-out nodes OFFLINE and
never deletes anything. Telemetry is bounded (`Telemetry` model; unknown
stays unknown, never zero-filled). Commands to non-ONLINE nodes queue in a
bounded (50), expiring (300 s) store with drop-oldest counted; `drain()`
rejects stale items; command results carry idempotency-safe correlation ids.

## Events (closed typed set)

`connected`, `disconnected`, `battery.changed`, `battery.low`,
`network.changed`, `location.changed`, `app.opened`,
`notification.received`, `screen.state_changed`, `sensor.updated`,
`permission.changed`. `battery.low` (and connect/disconnect) may raise an
untrusted proactive signal; notification text is always quoted as
untrusted data and never becomes an instruction. Device-supplied text is
injection-scanned before dots fan-out.

## Memory boundaries

Only pair/unpair and permission-denied transitions are remembered
(`store_fact`, source `device-fabric`). Per-heartbeat `last_seen`,
notification bodies, and sensor streams are **never** written to memory
— they stay as registry telemetry.

## World / spatial mirrors

Each Android node mirrors as a `device` world entity (`connected_to` its
network, `located_at` its location if explicitly set, `owns` from its
owner). Spatial: `object` node, parented under a `room` **only** when the
location was explicitly supplied — never guessed. Mirrors are
representation-only; the registry is the source of truth.

## CLI

```
jarvis device android status|list|info|register|pair|trust|revoke
  |capabilities|permissions|command|connect|disconnect|queue
```

Examples: `register --name Pixel`, `pair --id <dev> --code 123456`,
`command --id <dev> --node-command get_battery`. Every action prints real
fabric state; there are no fake/demo commands.

## Doctor

`android-node:*` checks (adapter, registry, pairing, transport, APK)
report `AVAILABLE` / `MISSING` / `OPTIONAL` / `UNSUPPORTED`; the APK check
honestly reports `UNSUPPORTED` until a real build pipeline exists.

## Limitations (honest)

- No network transport exists: 3.9 ships the in-process link only. A phone
  cannot actually connect yet; LAN/WebSocket/mTLS are future work.
- The APK has never been compiled or run; the Kotlin skeleton is
  uncompiled-source-reviewed only.

## 3.10 update: real transport has landed

The 3.9 limitations above are superseded by 3.10 — see
[ANDROID_TRANSPORT.md](ANDROID_TRANSPORT.md) for the full story:

- Real TCP transport exists (`jarvis/device/socket_transport.py` +
  `jarvis/device/android_transport.py`); a phone connects via
  `device transport serve`.
- Pairing codes remain short numeric secrets for local enrollment, now
  backed by SHA-256 hashes, single-use semantics, and a hard
  no-auto-trust rule (`TRUST_PENDING` + explicit CLI approval).
- Identity is now authenticated per-session via rotating HMAC-SHA256
  challenges (`require_verified_transport` enforced at the router).
- The APK compiles (`:app:assembleDebug`, ~3.3 MB), JVM unit tests pass
  11/11 including a live loopback handshake, and the app has been
  installed and launched on a real emulator.
- Remaining honest gaps: plaintext frames (trusted-LAN threat model, no
  TLS yet), foreground-only `serve`, file-based key store.
