# Distributed Device Fabric (3.8)

JARVIS 3.8 adds a first-class distributed device fabric: one JARVIS core
addressing many nodes (laptop, phone, Raspberry Pi, sensors) with explicit
identity, typed capabilities, lifecycle + trust, presence, and
policy-gated command routing.

No Android app ships in 3.8. This milestone is the core contract
(`jarvis/device/`) plus wiring. Phone support later plugs into this
contract; nothing here assumes Android specifics.

## Non-goals (explicit)

- No remote code execution. There is deliberately no `run_shell`,
  `run_python`, or `eval` message type. A node runs only explicitly
  registered handler functions under declared capability names.
- No implicit trust. LAN presence, a valid-looking node id, a matching
  hostname — none of these grant anything.
- No background threads. Heartbeats are processed on explicit calls;
  timeout sweeps are explicit (`sweep`). No listeners, no polling loops.
- No bulk data sync. State mirrored to world/spatial is representation
  (name, lifecycle, trust, location), never file contents or sensor dumps.

## Architecture

    Agent / Mission / Task
              |
              v
       PolicyEngine.evaluate(actor, ActionPlan)   <- authoritative; no bypass
              |
              v
       DeviceRouter.route                         <- trust + lifecycle + capability
              |
              v
       Transport (3.8: in-process only)            <- future: LAN/WS/HTTPS/mTLS
              |
              v
       Node capability handler                    <- explicit functions only

    DeviceRegistry (source of truth: lifecycle, trust, presence)
         |                |
         v                v   (mirrors only)
    World Model      Spatial Palace

Future transports implement the `Transport` interface and register via
`register_transport`; registry, router, and protocol never change.

## Lifecycle + trust

One validated state machine; trust moves with lifecycle, never separately:

    DISCOVERED -> REGISTERED -> TRUST_PENDING -> TRUSTED -> ONLINE <-> OFFLINE
                                                     +-- REVOKED (terminal)
                                                     +-- QUARANTINED
                                                     +-- DISABLED

- `register` enrolls at TRUST_PENDING (never trusted on sight).
- `trust_device` requires a human actor + reason; recorded in the device
  provenance and the registry audit history.
- Identity conflicts are never silently overwritten: re-registering a known
  `device_id` with a different `node_id` raises `RegistryError`.
- `revoke` is terminal; `quarantine`/`disable` release back to
  TRUST_PENDING for re-evaluation, never straight to trusted.

### Trust limitation (honest)

3.8 fabric identity is stable but unauthenticated: node ids are
self-asserted over the in-process transport. Trust therefore requires an
explicit human approval (actor + reason recorded). `AuthContext` records
*how* each decision was verified (`local-process`, `explicit-approval`,
future `mtls`/`ed25519`) so stronger transports plug in without redesign.
Remote transports MUST verify sender identity before trust; the
`require_verified_transport` path enforces this.

## Capabilities

Typed (dotted names), versioned, individually enable/disable-able per node.
Capabilities describe what a node CAN expose; PolicyEngine decides what
JARVIS MAY request, per call. Unknown capability risk defaults to HIGH —
never assume safe.

The local node serves `system.status` and `system.telemetry` (read-only,
stdlib facts, no shell).

## Presence

First heartbeat from TRUSTED promotes to ONLINE. ONLINE nodes with stale
heartbeats go OFFLINE on explicit `sweep` (3x interval or
`heartbeat_timeout_s`). Timeouts never delete records. Unknown telemetry
metrics stay `None` — never fabricated.

## Security

- Secret-bearing keys (`password`, `secret`, `token`, `credential`,
  `api_key`, `private_key`, `auth`, ...) are REJECTED from device metadata
  and telemetry extras — never stored.
- Persisted/logged structures pass through `scrub` (drop secret keys,
  truncate long strings).
- Device-supplied text is injection-scanned (`scan_injection`) and quoted
  as `<untrusted-content>` before prompts, dots, or memory.
- Every trust decision and routed command produces an audit record.
- Emergency stop blocks all routing before any other check.

## Integrations

- **World Model**: each device mirrored as a `device` entity
  (`state`: lifecycle/trust/connectivity/last_seen; relations:
  `connected_to` network, `located_at` location, `owns` owner person).
  Mirrors only — fabric never reads world state for decisions.
- **Spatial Palace**: device as an `object` node; explicit room parent on
  `locate`. Empty room clears to UNKNOWN; locations are never guessed.
- **Events**: `device.registered/discovered/unregistered/trust_changed/
  revoked/quarantined/disabled/online/offline/heartbeat/command_completed/
  command_failed/capability_changed/location_changed` on the bus with
  per-minute-bucket dedup keys for heartbeats.
- **Proactive**: registration/trust/revocation emit untrusted
  `world_changed` signals (`trusted=False`). Online/offline flaps do not
  page proactive; they route to dots.
- **Dots**: lifecycle events fan out via `route_event` (injection-gated,
  fingerprint dedup).
- **Memory**: notable changes stored as facts (`source=device-fabric`,
  `origin=observed`).
- **Status/doctor/persistence**: `status()` merged into `Jarvis.status()`;
  `doctor()` delegated from `check_dependencies`; atomic JSON persistence
  with corrupt-file recovery; `close()` persists.

## CLI

`jarvis device-fabric <action>` (`devices` remains the local capability
snapshot). All mutating actions are explicit; routing is deny-by-default
(the `cli` actor holds no device grants, so `command` without a prior
policy grant + approval token is refused with a reason).

    status | list | info --device ID
    register --name N [--type T] | enroll-local [--name N] | discover --name N
    unregister --device ID
    trust|distrust|revoke|quarantine|release|enable|disable --device ID [--reason R]
    capabilities --device ID --capability a.b,c.d
    heartbeat --device ID | sweep
    locate --device ID [--room R]
    command --device ID --capability a.b [--args '{...}'] [--approve TOKEN]
    doctor

## Files

- `jarvis/device/`: `model.py` (Device, lifecycle machine), `identity.py`
  (NodeIdentity, AuthContext), `capabilities.py`, `protocol.py`
  (versioned FabricMessage), `transport.py` (in-process + interface),
  `telemetry.py`, `security.py` (reject/scrub/scan/audit), `registry.py`
  (persistent registry), `router.py` (policy-gated routing), `fabric.py`
  (subsystem facade).
- State: `~/.jarvis-os/device-fabric.json` (atomic write, corrupt recovery).
- Config: `JarvisConfig.device_fabric` (`enabled`, `state_path`,
  `heartbeat_timeout_s`, `max_devices`).
