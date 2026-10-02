# Security Policy

Security is a core design requirement of JARVIS-OS.

## Supported versions

The default branch is the actively developed version. Older releases may not
receive security fixes.

## Reporting a vulnerability

Do not disclose an unpatched vulnerability in a public issue, discussion, or
pull request.

Use GitHub's private vulnerability reporting/security advisory mechanism for
this repository when available. Include a concise description, affected
component/version or commit, reproduction steps, security impact, and any
known mitigation.

If private reporting is unavailable, contact the repository owner privately
through GitHub rather than posting sensitive details publicly.

## Security boundaries

JARVIS-OS should preserve least-privilege execution, policy-gated actions,
authentication and authorization for device connections, bounded resource use,
auditability of consequential actions, and safe credential handling.

Security-sensitive changes should include regression tests where practical.
