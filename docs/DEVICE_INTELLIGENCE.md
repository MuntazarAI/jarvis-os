# Persistent Device Intelligence (4.2 device track)

Durable orchestration above the 3.10 Android transport. The transport
is unchanged; this layer adds authorization, approvals, queueing, and
audit that survive restarts.

```
User / Agent intent
        ↓
DeviceCommandService.request_command
        ↓
shape validation (typed commands only)
        ↓
DeviceRouter.authorize
  1. emergency stop
  2. device exists + ONLINE + TRUSTED (can_execute)
  3. capability declared + enabled
  3b. persistent device grant (actor+device+capability, default deny)
  4. PolicyEngine: risk/e-stop authoritative; a durable grant may
     satisfy ONLY the permission-membership test, never risk/approval
        ↓ (approval required?)
Durable approval (PENDING→APPROVED→CONSUMED, bound, single-use, TTL)
        ↓
Durable outbox (QUEUED→…→COMPLETED, crash-recovering, idempotent)
        ↓
Outbox drainer (lane-before-approval ordering, reply verification)
        ↓
Existing transport (socket lane / in-process) → typed command
        ↓
Typed result/event → verification → COMPLETED + audit
```

## Files

- `jarvis/device/authz.py` — `DeviceGrantStore`
  (`<home>/device-grants.json`, atomic write, merge-load, mtime reload):
  grant/revoke per (actor, device, capability, wildcard-capable),
  device suspend/restore (presence/trust untouched), TTL expiry,
  default deny, fail closed.
- `jarvis/device/approvals.py` — `ApprovalStore`
  (`<home>/device-approvals.json`): `apd-` tokens bound to
  actor/device/capability/args-hash, PENDING→APPROVED→CONSUMED plus
  DENIED/REVOKED/EXPIRED, atomic single-use `consume()`, pure-check
  `peek()` (authorize peeks, delivery consumes — exactly once).
- `jarvis/device/outbox.py` — `CommandOutbox`
  (`<home>/device-outbox.json` + flock lock file): full lifecycle
  QUEUED/APPROVED/DISPATCHING/SENT/ACKNOWLEDGED/COMPLETED/FAILED/
  RETRYING/CANCELLED/EXPIRED/DEAD_LETTER, bounded retries with
  backoff, TTL sweep, `recover()` for stale in-flight records
  (flagged at-least-once), single-shot `complete()` (duplicate
  results ignored, not applied), `defer()`, dead-lettering, pruning.
- `jarvis/device/service.py` — `DeviceCommandService`
  (request/approve/deny/status/cancel/outbox/audit) + drainer
  `tick()` (recover → sweep → claim → deliver → verify). Attaches
  both stores to the shared fabric router, so `adapter.send_command`,
  `router.route`, and `host.send_command` all enforce the same gates.
  Never touches sockets.
- `jarvis/device/audit.py` — `DeviceAudit`, append-only
  `<home>/device-audit.jsonl`, scrubbed records, never raises.
- `jarvis/device/router.py` — optional `grant_store` / `approval_store`
  hooks in `authorize()`; `route()` consumes durable approvals at
  delivery. Unattached routers behave exactly as before.
- `jarvis/device/android_transport.py` — `send_command` consumes the
  durable approval at delivery, after lane verification (a dead lane
  never burns a single-use token).
- `jarvis/cli.py` — `device` actions: `inspect grants grant suspend
  restore approve deny command-status cancel outbox audit`
  (`--approval`, `--command-id`); `revoke --capability` revokes
  grants (bare `revoke` still revokes the device); `command` flows
  through the service; `serve` drains the outbox (throttled).

## Security properties

- Default deny at every layer; all checks fail closed.
- No path executes a device command without `authorize()`:
  service, adapter, host, and router all funnel through it (plus
  direct-`route()` bypass attempts are denied — tested).
- Grants are strictly narrower than policy permissions
  (actor+device+capability vs global capability); substitution is
  explicit and audited, risk/approval/e-stop stay authoritative.
- Approvals are single-use, device/command/args-bound, expiring;
  unknown tokens never mint replacements (no harvest).
- No shell/eval/ADB/filesystem capabilities added; commands stay
  typed and allowlisted; results sanitized + injection-scanned.
- Secrets/tokens never logged (presence logged as booleans only).

## Provenance (2026-10-03, emulator-5554, real APK 3.10.0)

register → grant → pair_request → approve → trust → secret →
heartbeat → ONLINE → command → requires_approval → approve →
serve-tick drain → lane delivery → typed battery result →
COMPLETED → host restart (state survives) → revoke → denied,
never reached the node (0 command frames) → full audit lifecycle
in `device-audit.jsonl`.

## Known limits / next

- Policy permissions are still process-local: pair durable grants
  with an operator grant flow (persistent policy grants) next.
- Server drops idle lanes after 15 s vs 60 s heartbeats (redial
  churn; lengthen idle allowance for HMAC-bound lanes).
- No approval notification channel (operator polls `outbox`).
- Secrets in plain files (documented 3.10 limitation, unchanged).
