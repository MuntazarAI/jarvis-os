# Defensive security-audit tools

JARVIS can operate the laptop's audit toolkit — strictly defensive,
explicitly scoped, approval-gated. Attack execution is not exposed
and never will be.

## Tools (`jarvis/tools/secaudit.py`, all HIGH risk + `sec.audit` permission)

| tool | does | refuses |
|---|---|---|
| net_inventory | nmap host discovery, fast top-port, or service-version profiles + parsed host/port findings | overbroad nets, non-routable targets, option-like targets, bad profiles |
| web_audit | nikto findings scan of one named URL | loopback, link-local, non-http, unresolved hosts |
| dir_enum | gobuster with YOUR wordlist + extensions/threads | missing/oversized wordlist, bad thread count |
| hash_audit | john/hashcat dictionary audit with YOUR hash file, wordlist, and explicit format/mode | missing/oversized files, invalid modes |
| sqli_scan | sqlmap detection-only, level 1-2, risk 1, parsed injectable findings | dump/exploit modes (don't exist here) |
| capture_read | read-only capture analysis + display filter | live sniffing (no interface flag exists) |

All run argv-list subprocesses (no shell), bounded time/output.
Authorization: Security Guardian skill `security.audit` (least-privilege
gate) + PolicyEngine `sec.audit` grant + approval for HIGH risk.

## Destination policy (net_inventory / web_audit / dir_enum / sqli_scan)

Allowed:

- public IPv4/IPv6 addresses,
- explicit RFC1918 (`10/8`, `172.16/12`, `192.168/16`) and ULA
  (`fc00::/7`) addresses, for auditing the operator's own network,
- operator-named hostnames that pass syntax checks and, for
  `net_inventory`, resolve only to allowed addresses.

Refused:

- loopback (including `localhost`, `127.0.0.1`, `::1`, and legacy
  spellings such as `127.1`, `2130706433`, `0x7f000001`, `0177.0.0.1`),
- unspecified, link-local (including `169.254.169.254`), multicast,
  reserved, and otherwise non-routable destinations,
- networks wider than 256 addresses (e.g. IPv4 wider than `/24`),
- option-like values, control characters, and shell/metachar punctuation.

For URL tools and `net_inventory`, hostnames are resolved best-effort
before acceptance; every resolved address must pass, and resolution
failure fails closed. **This is not a DNS-rebinding-proof control.** The
external tool resolves the name again (and URL tools may follow
redirects), so the address it connects to can differ from the address
validated here. Pass explicit addresses, or use host firewall/egress
policy, when that distinction matters.

`net_inventory` validates the addresses returned by one resolver call and
then gives nmap the original hostname. Multiple A/AAAA answers are all
checked, and one prohibited answer rejects the whole target. The
resolution/use gap remains: nmap may see different DNS answers.

## Argument and resource bounds

- Every external binary receives an argv list, never a shell string.
- Operator-supplied file paths are resolved to absolute paths before argv
  construction, so a filename like `-w` cannot become an option.
- Wordlists are capped at 100 MiB, hash files at 10 MiB, capture files must
  exist, thread/level/packet counts are numeric and clamped, and hashcat
  modes must be numeric.
- Output/time are capped by each wrapper; `nmap` never receives OS
  detection, scripts, or UDP; `sqlmap` never receives dump/exploit/shell
  flags.

## hash_audit boundary

`hash_audit` is an intentional **local** dictionary attack against hashes
the operator explicitly supplies, with a wordlist the operator explicitly
supplies. It never extracts hashes from the system, targets a remote
service, or accepts mask/brute-force modes. John format names and hashcat
numeric modes are validated; hashcat's `-a 0` (straight/dictionary) mode is
fixed.

Recovered plaintext is **never returned**. The raw stdout/stderr can
contain cracked passwords in several tool-specific formats, so both are
replaced with a withholding notice. Findings expose only a short hash
prefix, `cracked: "[redacted]"`, and a `cracked_count`; the result is
marked `sensitive` and `redacted`. The registry declares
`ToolSpec.sensitive_output`, which marks every `ToolResult` from this
tool as sensitive, and the redacted payload carries `sensitive: true`.
Traces, bus messages, and `agents explain` therefore receive only the
redacted view. The authorized operator can inspect the hash tool's own
output directly; JARVIS never persists it.

Limitation: `john` and `hashcat` may write their own pot files under the
user's home directory (for example `~/.john/john.pot`). JARVIS does not
manage or delete those files. If that matters, disable potfile writing in
the tool's own configuration or point it at a disposable/encrypted
location before running the audit.

## Live verified (2026-10-04, this laptop)

nmap 7.98 ping-scan of the laptop's own IP: host up, 0.08s.

## Never exposed

Brute-force logins, sqlmap dump/exploit/os-shell, WiFi deauth,
packet injection, exploit frameworks, autonomous targeting. These
stay manual tools. No prompt, approval, or agent output unlocks them.
