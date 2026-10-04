# JARVIS 24/7 Background Service 2.0

Thin supervision around existing capabilities: PresenceRuntime ticks,
world refresh, health checks, and maintenance run on a bounded
in-memory scheduler inside one supervised process. No threads, no
second event bus, no cognitive loop here.

## Lifecycle

`jarvis service start|stop|restart|status|health|doctor|logs|run`.
`run` is the foreground loop systemd (or `start`) supervises.
Single instance via flock + PID/start-time validation (stale locks
die with their holder; PID reuse cannot confuse the check).

Signals: SIGTERM/SIGINT stop after the current trigger (1s sleep
slices, no 5-minute hangs); SIGHUP re-reads state. Shutdown has a
20s grace bound, then exits rather than hanging.

## Scheduler

Triggers (world_refresh, presence_tick, health_check, maintenance)
carry id, source, priority, dedupe key, budget, timeout, and
correlation id. Queue cap 32 with explicit backpressure (drop lowest
priority first, counted, never silent). Retries: capped exponential
backoff (60s→1h), max 3 attempts, then counted and abandoned — no
restart storms. Dedupe keys live 1h max.

## Watchdog & health

Heartbeat `<home>/service-heartbeat.json` every 60s (monotonic ages,
bounded writes — no SSD churn). States: FULL, DEGRADED, RECOVERING,
EMERGENCY_STOP, FAILED, STOPPED. A stale heartbeat (>5min) reads as
stale, never as healthy. The watchdog never kills: systemd
`Restart=on-failure` (5 tries/10min) owns restarts.

## Degraded mode

Each dependency degrades independently: network/model/world/voice/
device failures pause only their triggers; memory, reasoning, and
diagnostics continue. Emergency stop pauses autonomous side effects;
health/status/doctor stay available.

## systemd

`systemd/jarvis.service` (user unit, no root): start after login
(Mode A default; lingering documented opt-in), journald logging,
audited hardening (NoNewPrivileges, PrivateTmp, memory/tasks caps;
ProtectHome omitted — the service legitimately uses home state).

Install: copy to `~/.config/systemd/user/`, `systemctl --user
daemon-reload`, `systemctl --user enable --now jarvis.service`.
