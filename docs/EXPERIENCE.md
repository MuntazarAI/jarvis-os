# Experience Layer 1.0

Command center over the existing JARVIS core. Presentation + interaction
only: every number on screen is read from a live subsystem, and every
action reuses an existing authority. No second planner, scheduler, bus,
policy engine, memory, or approval system exists in this layer.

## Architecture map (reuse, not duplication)

| Experience need | Existing authority | Adapter |
|---|---|---|
| System/agent state | `Jarvis.status()` | `experience.py::_mesh` (normalize only) |
| Missions + dots | `missions.hud.build_snapshot` | passed through |
| Durable tasks | `DurableRunner` + `TaskStore` | same runner CLI/service use |
| Approvals | `PolicyEngine.approve/deny` (single-use) | `POST /api/approvals/decision` (carrier only) |
| Policy/e-stop | `PolicyEngine` | displayed; re-checked per action |
| Security findings | `security.review` (deterministic) | history file `security-scans.json` (bounded 20) |
| World intel | `worldintel` config + registry | topics/sources shown; live data on demand |
| Voice | `voice_profile` + TTS config | state shown; no mic claims |
| Service health | `service.runtime` + `PresenceRuntime` | read-only |
| Devices | `device_fabric.status()` | counts shown; absent → "not connected" |
| Notifications | `proactive.notifications` + derived alerts | deduped by key |
| Timeline | `EventStore.stream` | last 30, no second database |
| Evidence | `jarvis proof` (memory/tasks/audit receipts) | linked, not duplicated |
| Commands | `POST /cycle` → `cycle_once` (Conductor path) | `/remote` + experience command box |

## Presence (view mapping, not a state machine)

`presence_state()` is a pure function, highest priority first:
`E_STOP > ALERT > WAITING > EXECUTING > VERIFYING > PLANNING > IDLE`.
`LISTENING`/`SPEAKING` are deliberately absent — no live voice-loop
flag exists, and the UI never claims one.

## API surface (v1, all authenticated unless noted)

- `GET /experience` — page shell (public, no data; token prompt inside)
- `GET /api/experience` — snapshot (bearer; `Cache-Control: no-store`)
- `POST /api/tasks/<id>/<advance|pause|resume|cancel|recover>` —
  bearer; 404 unknown id, 409 illegal transition, 400 malformed input
- `POST /api/approvals/decision` — bearer + single-use approval token
  in body; rate-limited (10/min); token never echoed; decision recorded
  in EventStore
- WebSocket: `?token=` query auth (browsers cannot set WS headers);
  missing/wrong token → 403 close. Same open-when-untokened rule as REST.

Deterministic errors; internal exception details never leak (type names
only). See `docs/API.md` for the wider surface.

## Security model

- Shells (`/board`, `/remote`, `/experience`) are public and hold no
  data; every data/action route needs the bearer token.
- Approval tokens are pasted, never rendered (hints only, 8 chars).
- `_scrub` redacts secret-named keys and URL credentials in all
  snapshots; `token_hint` is explicitly exempt (designed for display).
- UI input travels `Experience → Conductor/cycle → Durable →
  PolicyEngine → tools`, never directly to tools. Task buttons call the
  same runner with the same policy checks as CLI/service.
- Offline-first: every section degrades to explicit `unknown` /
  `not connected` / `unavailable` — never faked, never silent.

## Measured performance (this host)

- Snapshot build: ~28ms cold / ~3ms warm (test budget: <1000ms)
- `/experience` page: ~13KB (budget: <150KB); snapshot JSON <500KB
- Poll interval 5s; timeline capped at 30 rows; notifications at 15;
  findings/history bounded (20 scans, 100 review findings)

## Settings

Read-only in 1.0 by design: the page states where config lives and
refuses to duplicate the config store. Voice style overrides reuse the
existing `voice-profile.json` via CLI, not the page.

## Troubleshooting

- Stale page after update: hard refresh (Ctrl+Shift+R); shells send
  `Cache-Control: no-store`, but proxies may hold copies.
- `401`: token mismatch — restart `serve` with the intended `--token`.
- Timeline empty: fresh home has no events yet — run a cycle.
- `409` on task buttons: the transition is illegal from the current
  state (e.g. advancing a planning task) — inspect first.
