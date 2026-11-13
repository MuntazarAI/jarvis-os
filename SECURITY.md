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

### What the runtime actually enforces

- **Approvals are single-use, expiring and bound.** An approval token is
  spent once, carries a five-minute TTL, and is bound to the actor, the
  action and the arguments. An ambiguous prefix resolves to nothing rather
  than to whichever request was created first.
- **A denial is final.** Denying a device command ends it; it does not mint
  a fresh approval and ask again.
- **A standing grant cannot widen itself.** An explicit deny beats an older
  allow, and a standing grant never substitutes for a global permission the
  operator did not grant.
- **The emergency stop fails closed.** If the stop state cannot be read, the
  action is blocked rather than permitted.
- **Credential stores are unreadable.** The vault key, the approval store
  and other credential files are refused by the tool layer and by
  perception — the refusal lives in one list (`jarvis/core/protected.py`).
- **Corrupt state is quarantined.** An unreadable store is copied aside and
  refused, never overwritten and never parsed into authority.
- **Tool execution is bounded.** `python_run` evaluates in a child process
  with an OS-enforced timeout; it cannot hang the agent.
- **Model output is untrusted.** The only path to an action is
  perception → cognition → intent → policy → approval → the existing
  command path.

### Model providers and keys

JARVIS-OS can talk to any model provider: a local Ollama daemon, NVIDIA
NIM, or any OpenAI-compatible server.

- **Keys live in the vault.** A backend names a vault secret and/or an
  environment variable; the value is fetched at call time and never
  reaches `config.json`, a command line, a log, an audit record, a cycle
  record or a snapshot.
- **Approval tokens are sealed.** Tokens are minted with the `appr-`
  prefix that the redactors recognise, so a token that reaches a log is
  scrubbed rather than persisted.
- **Remote providers are opt-in.** `policy.local_only` (on by default)
  removes remote backends from the routing chain entirely. Turning it off
  is an explicit decision.
- **Remote use means remote disclosure.** Prompts, and any data attached
  to them, leave the machine when a remote backend is selected. Keep
  `local_only` on unless that is intended.

### Reporting a model-provider issue

If a provider leaks keys into logs, mis-scopes a model's permissions, or
returns content that bypasses the policy layer, treat it as a security
issue and report it privately — the provider is third-party, but the
integration is ours.
