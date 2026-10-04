# Standing Grants 1.0

Explicit bounded durable authorizations. A grant pre-authorizes a
narrow capability class so repeated low-risk actions skip interactive
approval — it never replaces PolicyEngine (risk, approval needs,
egress rules, emergency stop all still apply on top).

## Contract

`grant_id, subject, capability, scope_kind, scope, allowed_operations,
denied_operations, risk_class, created_at, expires_at (30d default),
revoked_at, created_by, status, provenance`. Validated at creation:
capability + scope + ≥1 operation required; `*` scope needs
high/critical risk; unknown kinds rejected.

Risk classes reuse the repo vocabulary:
read_only, low, moderate, high, critical.

## Scopes

- `path`: containment-checked (symlinks resolved, `..` rejected,
  missing side fails closed).
- `device`, `topic`, `capability`: exact match (trailing-`*` prefix
  match supported).
- No implicit wildcards.

## Conflict order

Explicit deny > policy > grant. Expired/revoked/corrupt/mismatched =
deny. Emergency stop = deny everything. evaluate() itself is
untouched; grants are consulted via
`PolicyEngine.authorize_standing()` as authorization input.

## Lifecycle

Create (explicit CLI/NL-confirmed) → live → expire/revoke.
Revocation is immediate, persistent, audited. Registry bounded
(64), atomic JSON, mtime reload across processes, corrupt file fails
closed. Restart-safe (verified by test).

## CLI

`jarvis grants create --capability media.organize --scope ~/Downloads
--allow move,list [--deny delete] [--risk low] [--days 30]`,
`list`, `show --id`, `revoke --id`.
