# Defensive security-audit tools

JARVIS can operate the laptop's audit toolkit — strictly defensive,
explicitly scoped, approval-gated. Attack execution is not exposed
and never will be.

## Tools (`jarvis/tools/secaudit.py`, all HIGH risk + `sec.audit` permission)

| tool | does | refuses |
|---|---|---|
| net_inventory | nmap ping/fast-ports/service-version profiles + parsed host/port findings | overbroad nets, non-routable targets, bad profiles |
| web_audit | nikto findings scan of one named URL | loopback, non-http |
| dir_enum | gobuster with YOUR wordlist + extensions/threads | missing wordlist |
| hash_audit | john/hashcat with YOUR files + format/mode select | missing files |
| sqli_scan | sqlmap detection-only, level 1-2, risk 1, parsed injectable findings | dump/exploit modes (don't exist here) |
| capture_read | read-only capture analysis + display filter | live sniffing (no interface flag exists) |

All run argv-list subprocesses (no shell), bounded time/output.
Authorization: Security Guardian skill `security.audit` (least-privilege
gate) + PolicyEngine `sec.audit` grant + approval for HIGH risk.

## Live verified (2026-10-04, this laptop)

nmap 7.98 ping-scan of the laptop's own IP: host up, 0.08s.

## Never exposed

Brute-force logins, sqlmap dump/exploit/os-shell, WiFi deauth,
packet injection, exploit frameworks, autonomous targeting. These
stay manual tools. No prompt, approval, or agent output unlocks them.
