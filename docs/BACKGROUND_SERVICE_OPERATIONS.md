# Background Service — Operations

## Install (user service, no root)

```bash
cp systemd/jarvis.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jarvis.service
systemctl --user status jarvis.service
```

Starts after login (Mode A). For availability with no session open
(Mode B), explicitly opt in: `loginctl enable-linger $USER`.

## Daily use

```bash
jarvis service status     # running pid + heartbeat age/state
jarvis service health     # machine-readable health (JSON with --json)
jarvis service doctor     # PASS/WARN/FAIL per subsystem
jarvis service logs --lines 50
jarvis service stop       # graceful (≤20s) shutdown
jarvis service start      # refused if already running
```

## Failure modes

`stop` sends SIGTERM and waits ~25s. A network-bound tick can delay
exit past that (stop reports timeout; the process still finishes its
tick and exits — verified live). `start` refuses while the lock is
held.

| Symptom | Meaning | Action |
|---|---|---|
| `stopped (no pidfile)` | never started or clean stop | `service start` |
| `already running (pid N)` | healthy instance holds the lock | `service status` to inspect |
| heartbeat `stale` | loop wedged >5min | `service logs`, then `stop`/`start` |
| state FAILED | dependency failed repeatedly | `service doctor`, fix cause, restart |
| EMERGENCY_STOP | stop file present | read-only mode; remove file to resume |
| start refused after crash | systemd StartLimit tripped | `systemctl --user reset-failed`, investigate logs |

## Recovery

Reboot: unit restarts automatically (login session or linger).
Pending triggers are NOT replayed blindly: scheduler state is
in-memory, so a restart re-discovers due work (world refresh
intervals, file mtimes) instead of resuming half-done actions.
Unknown outcome is never recorded as success — verification decides.

## Limitations (honest)

- Single machine, single user; no failover, no clustering.
- Presence tick interval minimum 30s (no sub-second scheduling).
- Voice/model-heavy triggers run in-process; very long syntheses
  should stay on the voice worker path, not the service loop.
- No autonomous background crawling beyond configured topics/paths.
