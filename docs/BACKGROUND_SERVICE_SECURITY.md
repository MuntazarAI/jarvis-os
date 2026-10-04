# Background Service — Security

Threat model for the 24/7 runtime. PolicyEngine stays authoritative;
nothing below bypasses it.

| Threat | Mitigation | Test |
|---|---|---|
| Second instance / lock games | flock-held lock file; PID + start-time validation; stale locks die with holder | start/stop, stale-pidfile, duplicate-reject |
| Forged scheduler triggers | Trigger ids are labels only; handlers treat payloads as data; no exec/shell in service code | malicious-payload test |
| Malicious world/file content | Existing guards + injection scans on fetch paths; trigger carries references, never instructions | worldintel + guards suites |
| Forged approvals/grants | Approval/grant stores validate schema, bindings, expiry; corrupt = deny | autonomy + approval suites |
| Emergency-stop bypass | Checked in service health, presence tick, and every authorize path | e-stop tests |
| Privilege escalation | Service runs as the user; unit file drops privileges it never needs; no setuid paths | hardening review in unit file |
| Path traversal (logs/state/snapshots) | Canonical home-rooted paths; `..` rejected; atomic replace writes | traversal tests |
| Symlink attacks (state dirs) | State files opened by exact path; temp files mkstemp + replace | storage tests |
| Log injection | Logs are append-only diagnostics; never parsed as commands | — (structural) |
| Restart storms | systemd StartLimit (5/10min) + per-trigger backoff caps + give-up counting | backoff/budget tests |
| Resource exhaustion | Queue cap 32 + drop-lowest, worker count 1, retry cap 3, log rotation, heartbeat 60s | bound tests |
| Stale heartbeat mistaken for health | Readers compute age from monotonic stamp; >5min reads stale | stale-detect test |
| Secrets in state/telemetry | Heartbeat/state carry counts/ages/ids only; no payloads, no keys | metadata-only assertions |

No `shell=True`, `os.system`, `eval`, or `exec` anywhere in the
service package (source-scanned by test).
