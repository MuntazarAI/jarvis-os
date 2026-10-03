# Android Real Transport (3.10)

Real socket transport between the JARVIS host and the Android JARVIS Node.
3.9 built the node foundation (in-process link only — a phone could not
actually connect). 3.10 adds a real TCP transport with authenticated
pairing, explicit trust approval, heartbeats, events, and host-initiated
typed commands.

## Architecture

```
Android phone (Kotlin)                    JARVIS host (Python)
─────────────────────                     ────────────────────
MainActivity (UI)                         CLI: device transport serve
NodeService (foreground)                  AndroidSocketHost
  └─ NodeConnection                         ├─ FabricServer (TCP listener)
       └─ SocketPeer                         │    └─ ServerPeer per conn
            └─ SocketLink                    ├─ DeviceAuthenticator (HMAC keys)
                 (u32 BE len + JSON)         ├─ AndroidNodeAdapter (3.9)
                                             └─ DeviceRouter authorize/finish
```

The host is started explicitly (`device transport serve`); there is no
background daemon, no autostart, no network listener unless the operator
runs that command. The Android app never listens — it only dials out to
the configured host/port.

## Wire protocol

- Framing: 4-byte big-endian length + N bytes UTF-8 JSON (`encode_frame` /
  `decode_frames` in `jarvis/device/socket_transport.py`).
- Bound: frames larger than `MAX_FRAME_BYTES` (256 KiB) are rejected with
  `FramingError`; a poisoned connection is dropped and counted
  (`rejected`), never partially parsed.
- Multi-frame buffers: `decode_frames(buffer, limit)` returns all complete
  frames; the server read loop (`limit=1` per read) drains buffered
  pipelined frames without blocking on the next `recv`.
- Message envelope: `FabricMessage` (`jarvis/device/protocol.py`, protocol
  version 1) — `message_id`, `message_type`, `sender_node`, payload dict,
  `correlation_id` for request/reply matching. 3.10 adds `pair_request`,
  `pair_status`, `auth_challenge`. Unknown types/versions are rejected.
- Full duplex: either side can initiate. Client `SocketTransport.connect(..
  ., on_request=...)` runs a reader thread: frames whose correlation id
  matches a pending send complete it; anything else goes to `on_request`.
  Server `server.request(peer, message)` delivers host-initiated commands
  over the same connection and waits for the correlated reply.

## Authentication (HMAC challenge-response)

- Per-device secrets live in `<home>/device-keys.json` (0600 file mode),
  created by `DeviceAuthenticator.issue(device_id)` exactly once, at
  approval time. Only hashes/outcomes are logged — never secrets.
- Every protected message carries `auth: {challenge, response}`.
  `verify_and_rotate()` checks the HMAC-SHA256 of the presented challenge
  and **rotates**: a correct response returns the *next* challenge, so a
  captured reply cannot be replayed (replay attempts are rejected).
- The host also proves itself: outgoing commands carry
  `auth: {proof: authenticator.prove(device_id, message_id)}`.
- `require_verified_transport` (`jarvis/device/identity.py`) rejects any
  peer whose transport cannot prove verification; verified peers get an
  honest `AuthContext` (method recorded, no fake crypto claims).

## Pairing flow (never auto-trusts)

1. Operator: `jarvis device android register --name Pixel ...` → device is
   created `REGISTERED`, a 6-digit code is issued (SHA-256 hash persisted in
   `android-pairings.json`, 600s TTL, 5 attempts, single-use).
2. Phone taps PAIR → server `pair_request`: `adapter.pair_request_approval`
   verifies the code and binds `node_id`, then transitions
   `REGISTERED → TRUST_PENDING`. **No trust is granted.**
   The host mints its own pending token (`secrets.token_hex(16)`) and the
   phone polls `pair_status`.
3. Human approval is mandatory: `jarvis device transport approve --device
   <id>` (→ `adapter.trust_android`). CLI approval is picked up mid-session
   because `pair_status` calls `registry.load()` before the trust check.
4. Approved `pair_status` returns `pair: approved` **with the device_secret
   exactly once**, binds the lane (`bind_node`), rewrites the rendezvous
   file, and records a memory fact. Token reuse is rejected.
5. Wrong/expired/reused codes, node_id conflicts, and pre-approval polls
   (`pair: pending`) are all explicit error/pending replies — never silent.

## Lifecycle after pairing

- `auth_challenge` bootstraps the HMAC chain for a fresh session.
- `heartbeat` (HMAC-gated, refused when `disconnect`ed) carries bounded
  telemetry (`android_telemetry()`: battery/sensors/network; unknown stays
  unknown) and updates presence: `heartbeat` → `mark_online` → lifecycle
  `ONLINE`. `disconnect` → `mark_offline`. Sweeps never delete devices.
- `event` requires the name in the closed `ANDROID_EVENTS` set
  (11 typed events); invalid names are rejected at both adapter and host.
  Summaries are sanitized; `battery.low` emits an *untrusted*
  `ProactiveEvent` (never an instruction).
- `command_result` completes a host-initiated command via `router.finish`
  (audited, sanitized, injection-scanned).

## Host-initiated commands

`AndroidSocketHost.send_command(actor, device_id, capability, args)`:

1. `router.authorize(...)` — e-stop, device exists + `can_execute`,
   capability declared + permission-enabled, then `PolicyEngine.evaluate`
   (risk floor 0.75 ⇒ approval token flow, same as 3.8). Denials return the
   same shape as `route()` including `approval_token`.
2. `build_command_message()` — validated `COMMAND_REQUEST`. Interop note:
   the wire carries the **bare** command name (`get_battery`), which is
   what the Kotlin allowlist matches; the typed `device.*` capability is
   used for authorize/audit only.
3. `server.request(lane, message)` on the device's most-recent lane
   (`peer_for_node` prefers the freshest binding, so reconnects win).
4. `router.finish(...)` on the correlated `command_result` — full audit
   trail, result sanitized + `scan_injection` checked.

The command allowlist is `SAFE_COMMANDS` (14 typed commands: `device.*`
info/status/battery/network/location/sensors, show_notification,
open_app/open_url (URL validated by `is_safe_url`), vibrate, set_volume,
capture_photo, start/stop_sensor_stream). No shell, no eval, no filesystem
access, no ADB — verified by test (`test_allowlist_has_no_shell`).

## Offline queue

The 3.9 adapter queue is unchanged: `send_command` while disconnected
queues (bounded 50, 300s TTL, drop-oldest counted); `drain` on `connect`
dispatches fresh items via the socket host when a lane exists (re-checking
authorization — nothing bypasses the router) and rejects expired ones.

## Rendezvous file

`AndroidSocketHost.start()` writes `<home>/device-transport.json`
atomically: `{running, port, pid, peers, updated_at}`; `stop()` removes it.
Short-lived CLI commands (`transport status/peers`) read it via
`read_host_status()` with `os.kill(pid, 0)` liveness — stale/missing/
corrupt files report `running: false`, never raise.

## CLI

```
jarvis device transport status            # host running? port/pid/peers
jarvis device transport peers             # bound lanes from rendezvous file
jarvis device transport approve --device <id> [--by op] [--reason ...]
jarvis device transport serve [--host 127.0.0.1] [--port 0]
jarvis device android unpair --device <id>   # revoke + disconnect + remember
```

`serve` runs the host in the foreground (Ctrl-C shuts down cleanly and
removes the rendezvous file). The `android` actions from 3.9 are unchanged.

## Config

`DeviceTransportConfig` on `JarvisConfig.device_transport` (auto-walked by
`from_dict` like every other section): `enabled=false` (serve is explicit),
`host=127.0.0.1`, `port=0` (ephemeral, actual port in rendezvous file),
`connect_timeout_s=15`, `max_connections=16`, `max_frame_bytes=262144`,
`reconnect_initial_s=1` → `reconnect_max_s=60` backoff, `heartbeat_s=60`,
`keys_path=device-keys.json`.

## Android app (Kotlin)

- `SocketLink.kt` — pure framing mirror (u32 BE + UTF-8, 256 KiB cap,
  incremental decode → frames + next position, `FramingException`).
- `SocketPeer.kt` — blocking TCP client: sync request/reply by
  correlation id (max 32 pending), connect loop with 1s→60s backoff, reader
  thread (replies → pending, unsolicited → `onRequest`), `AUTH_FAILED`
  stops retries.
- `NodeConnection.kt` — `org.json` messages: hello / pairRequest+poll /
  auth headers / heartbeat / sendEvent; answers server `command_request`
  frames through the 3.9 `CommandDispatcher` allowlist only. Tracks
  `connState` so PAIR waits for `CONNECTED` before sending.
- `NodeCrypto.kt` — HMAC-SHA256 hex, mirrors `DeviceAuthenticator`.
- `NodeService.kt` — owns connection on a single-thread executor; PAIR
  action (connect → pairRequest → 40×5s poll → save secret → heartbeats);
  60s heartbeat schedule; `ACTION_STATE` broadcasts
  (connected/trust/device_id/heartbeat_at/error, all String extras).
  `startForeground` is wrapped in try/catch (broadcasts the error and stops
  instead of crashing) and the manifest declares
  `FOREGROUND_SERVICE_CONNECTED_DEVICE` (API-34 requirement).
- `MainActivity.kt` — minimal honest UI: host/port + save, pair fields,
  connect/disconnect, status + battery + capabilities with live states.

Build (from the `android/` directory — the Gradle project lives there, not
at repo root):

```
cd android
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ./gradlew :app:testDebugUnitTest
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ./gradlew :app:assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk (~3.3 MB)
```

Requires JDK 17 and the Android SDK (`ANDROID_HOME`/`ANDROID_SDK_ROOT`,
compileSdk 37, targetSdk 34). JVM unit tests need `testImplementation org.json:json`
because `android.jar` JSON stubs throw `not mocked` on the JVM. AGP 9
provides built-in Kotlin (no `kotlin.android` plugin; `jvmTarget`
defaults to `targetCompatibility`).

## Doctor

`device-transport:*` checks report `AVAILABLE` / `MISSING` / `OPTIONAL` /
`UNSUPPORTED` (same convention as `android-node:*`): host key store,
rendezvous liveness, config sanity, loopback self-test where practical.

## Security model and threat model (honest)

- What 3.10 gives you: no auto-trust (TRUST_PENDING + human approval),
  single-use short-lived pairing codes with attempt limits, per-device
  secrets in 0600 files, single-use rotating HMAC challenges (no replay),
  mutual proof (device proves to host, host proves to device), bounded
  framing, closed typed event/command sets, every command through
  PolicyEngine with audit, emergency-stop compatible, no shell/eval/ADB.
- What it does **not** give you: **encryption**. Frames are plaintext JSON
  over TCP — anyone who can tap the path sees telemetry and events.
  Threat model is therefore *trusted LAN only*: loopback, direct cable,
  or a private tunnel (Tailscale/WireGuard readiness = bind `host` to the
  tunnel interface via config; the transport itself is bearer-agnostic).
  Do not expose the port to the open internet. mTLS (mutual TLS with
  per-device certs) is the planned follow-up that removes this limitation.
- Pairing codes are short numeric secrets for local enrollment, not for
  hostile networks. `require_verified_transport` is enforced at the router
  boundary; the in-process transport remains `UNVERIFIED` by design.

## Pairing order (mandatory)

The human approval MUST come after the phone's `pair_request`:

1. `device android register` → 6-digit code (600 s TTL, 5 attempts, single-use).
2. Phone taps PAIR → `pair_request` verifies the code → `TRUST_PENDING` + pending token.
3. Human runs `device transport approve --device <id>`.
4. Phone's `pair_status` poll returns the device secret exactly once.

Approving BEFORE `pair_request` (pre-approval) cancels the pending code
(`trust_android` clears it) and the phone can never complete pairing —
fail closed by design, since trust without code proof is meaningless.
To recover, register again for a fresh code.

The long-running host reloads both the device registry and the pairing
file from disk before verifying a `pair_request`, so codes/devices
registered by short-lived CLI processes are visible mid-session
(single-process tests never catch this; cross-process regression tests
prove it).

## Troubleshooting

- `pair: pending` forever → the CLI approval hasn't happened; run
  `device transport approve --device <id>`.
- `unknown or reused pending token` → the phone's poll token was consumed
  (approve already returned the secret once); re-pair from scratch.
- `no live socket lane` → the device paired but its TCP connection dropped;
  the phone reconnects with backoff; check `transport peers`.
- `AUTH_FAILED` on the phone → secret mismatch (re-pair; never reuse an
  old secret).
- `ForegroundServiceStartNotAllowedException` (pre-fix builds) → rebuild;
  current code catches this and reports it in the UI instead of crashing.

## Limitations (honest)

- No TLS yet (see threat model above); no mTLS/Ed25519/QR-token pairing.
- No daemon/API-server integration: `serve` is foreground-only.
- `device-keys.json` is a file secret store, not the Android Keystore /
  system keyring. The app keeps the device secret in plain
  SharedPreferences (documented; EncryptedSharedPreferences is the
  hardened-build follow-up).
- Idle churn: the server drops silent connections after its 15 s read
  timeout while the phone heartbeats every 60 s, so the lane redials
  roughly every 16 s between heartbeats. Bounded and self-healing
  (a one-time resync covers lost-reply desync), but noisy; a longer
  idle allowance for HMAC-bound lanes is the follow-up.
- No async operator command path yet: policy grants/approvals live in
  the serving process, so `device android command` from a short-lived
  CLI only queues process-locally. Typed host→phone commands are proven
  through `AndroidSocketHost.send_command` (approval, bare-wire mapping,
  host proof, audited result); wiring it to multi-process operators is
  the next item.
- Emulator E2E (real APK 3.10.0 ↔ real host: register, pair_request,
  pending token, explicit trust, one-time secret, HMAC heartbeat,
  typed `device.get_battery`/`device.get_info` commands with typed
  results, policy denial of an ungranted actor) PROVEN 2026-10-03;
  43 Python loopback tests + 12 Kotlin JVM tests green.
