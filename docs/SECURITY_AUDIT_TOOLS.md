# Defensive security-audit tools

JARVIS can operate the laptop's audit toolkit — strictly defensive,
explicitly scoped, approval-gated. Attack execution is not exposed
and never will be.

## Tools (`jarvis/tools/secaudit.py`, all HIGH risk + `sec.audit` permission)

| tool | does | refuses |
|---|---|---|
| net_inventory | nmap ping-scan of one host or /24 | overbroad nets, non-routable targets |
| web_audit | nikto findings scan of one named URL | loopback, non-http |
| dir_enum | gobuster with YOUR wordlist file | missing wordlist |
| hash_audit | john/hashcat on YOUR hash + wordlist files | missing files |
| sqli_scan | sqlmap level-1/risk-1 detection only | dump/exploit modes (don't exist here) |
| capture_read | read-only analysis of a capture file | live sniffing (no interface flag exists) |

All run argv-list subprocesses (no shell), bounded time/output.
Authorization: Security Guardian skill `security.audit` (least-privilege
gate) + PolicyEngine `sec.audit` grant + approval for HIGH risk.

## Live verified (2026-10-04, this laptop)

nmap 7.98 ping-scan of the laptop's own IP: host up, 0.08s.

## Never exposed

Brute-force logins, sqlmap dump/exploit/os-shell, WiFi deauth,
packet injection, exploit frameworks, autonomous targeting. These
stay manual tools. No prompt, approval, or agent output unlocks them.
