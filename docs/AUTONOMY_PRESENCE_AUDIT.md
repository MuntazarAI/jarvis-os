# Autonomy & Presence audit (ground truth)

## Grants/permissions (reuse)
- `PolicyEngine`: actor→permission map, file-persisted with flock +
  mtime reload (`grant`/`revoke`/`permitted`); `evaluate` = permitted
  check + RiskEngine + local-only egress + emergency stop. Missing:
  scoped/expiring user-facing standing grants (permissions are bare
  strings, no scope/expiry/risk).
- `DeviceGrantStore`: durable device/capability grants + suspension,
  atomic JSON, reload. Device-scoped only.
- `ApprovalStore`: one-time bound tokens (request/approve/deny/revoke/
  peek/consume), prefix resolution, expiry, audit. Single-use by design.
- Gap: general standing-grant contract (capability + scope + risk +
  expiry) evaluated as input to PolicyEngine. New module, no new engine.

## Proactive/background (reuse)
- `ProactiveEngine`: candidates, cooldowns, quiet hours, notification
  policy, dedupe, persistence, `notify(event)` → candidate|None.
  `world_changed` event type already exists.
- Notifier: LogBackend (always) + DesktopBackend (if notify-send).
- World Intel: TopicStore, refresh_all with interval skip + snapshots
  + diffs, briefing builder. Missing: only the runtime wrapper
  (start/stop/health/poll) — no new loop logic needed.

## Sessions/isolation
- ConversationManager sessions (TTL, prune); voice sessions with turn
  ids; soak-proven isolation. Reuse as-is.

## Service patterns
- `ServiceManager`: PID file, start/stop/restart, health wait, log
  tail. Reuse pattern for presence daemon (PID + stale detection).

## Config
- `JarvisConfig` sections per subsystem; env overrides. Autonomy
  settings go here (disabled-by-default).

## SensoryBus/EventBus
- Both exist, shared stores; no correctness impact found (reliability
  soak green). NOT merging (explicit non-goal).

## Security boundaries (must hold)
- PolicyEngine authoritative; approvals bound; guards (SSRF/injection)
  on fetch paths; secret scrubbing on cycle persistence; secure
  telemetry (metadata-only); emergency-stop file.
