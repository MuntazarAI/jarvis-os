# Background Presence 1.0

Bounded background availability without hidden daemons: no threads,
no daemonization magic. The caller (CLI, cron, dots tick) drives
`ticks`; each tick is emergency-checked, time-boxed (120s), and
state-persisted.

## Runtime

`PresenceRuntime`: PID file (second start fails honestly, stale PIDs
cleared), `start/stop/health/tick`, graceful shutdown, bounded
retries (none hidden — each tick is independent), corrupt state
recovers empty, per-tick action log (last 20) answers "why did you
act?".

## Triggers (bounded adapters)

- World refresh due (reuses World Intel interval/snapshots/diffs).
- Watched files (explicit paths only, ≤16, mtime poll, dedupe via
  persisted seen-map, no recursive home scanning).
- Each trigger may observe/recommend/notify or perform a
  grant-authorized low-risk action. Never elevates privilege.

## Notifications

Existing Notifier + policy (cooldowns, quiet hours, dedupe) +
existing proactive candidates. Bounded, attributable, auditable,
dismissible. A trigger storm yields at most the policy-allowed rate.

## CLI

`jarvis autonomy status|health|start|stop|tick`. `start` claims the
slot for this machine; `tick` runs one bounded pass (cron-friendly).
