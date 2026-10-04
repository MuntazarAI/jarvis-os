# Autonomy Security 1.0

Threat model and where each threat dies. PolicyEngine is the single
security authority; everything below is enforcement in depth.

| Threat | Mitigation | Test |
|---|---|---|
| Prompt injection → auth | Grants need explicit CLI/confirmed creation; text never authorizes | malicious-file E2E |
| Forged grant | Schema validation + id match + audit | corrupt-entry skip |
| Privilege escalation | Grant fills scope only; risk/approval/egress stay in evaluate() | policy-input test |
| Cross-session leakage | Subject-bound grants; session-scoped traces | subject mismatch |
| Path traversal | `..` rejected, containment-checked, no-overwrite moves | malicious names |
| Symlink escape | Resolved both sides; symlinks refused as sources | symlink source |
| Expired/revoked reuse | Live check on every evaluation | expiry/revoke E2E |
| Revocation race | mtime reload before each read; atomic replace on write | cross-process |
| Emergency-stop bypass | Checked in authorize_standing + presence tick | e-stop E2E |
| Arbitrary shell | No shell in autonomy code (single subprocess-free package) | source scan |
| Notification spam | Existing cooldown/dedupe/quiet-hour policy | policy-owned |
| Orphan daemon | PID + stale detection; second start refused | start/stop test |
| Restart storm | No auto-restart; ticks independent, errors counted | error counter |

`eval`/`exec`/`shell=True`/`os.system`: absent from autonomy, grant,
presence, preferences, and perception code by construction.
