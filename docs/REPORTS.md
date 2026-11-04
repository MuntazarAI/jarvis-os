# Read-Only SQL Reports

JARVIS uses SQL as a **bounded polyglot query layer** over the SQLite
stores it already owns. SQL is not a second runtime, a second store, or
an action surface. Python remains the coordinator; report names and SQL
files are fixed in the repository.

## Commands

```bash
jarvis report list
jarvis report events-summary --limit 20
jarvis report events-recent --limit 10
jarvis report memory-rooms --limit 50
jarvis report events-summary --json
```

| Report | Database | Purpose |
| --- | --- | --- |
| `events-summary` | `events.db` | event counts, first/last timestamp by type |
| `events-recent` | `events.db` | most recent events with a bounded payload preview |
| `memory-rooms` | `jarvis.db` | active memory counts by room and tier |

## Safety invariants

- **Fixed reports only.** The CLI accepts a report name and a limit,
  never raw SQL.
- **Read-only connection.** The database is opened with a SQLite
  `mode=ro` URI and `PRAGMA query_only = ON`. A report cannot write even
  if a query file were compromised.
- **One bounded statement.** The runner rejects SQL that does not start
  with `SELECT`/`WITH`, contains a write/DDL keyword, contains multiple
  statements, or does not bind `:limit`.
- **Bounded output.** Rows are capped at 200, string values at 400
  characters, and JSON payload previews at 200 characters in SQL.
- **Secret-scrubbed.** Column names matching token/secret/password
  hints are redacted; string values go through the same credential-span
  scrubber used by security findings; JSON payloads are structurally
  scrubbed by key before serialization.
- **No authority.** A report cannot approve, execute, mutate policy, or
  change durable state.

## Adding a report

1. Add a single `SELECT`/`WITH` statement under
   `jarvis/reports/sql/`, ending with `LIMIT :limit`.
2. Register a name in `jarvis/reports/runner.py` with a fixed database
   name from `PathsConfig` (`events.db` or `jarvis.db`).
3. Add a deterministic test to `tests/test_reports.py`.
4. Keep the query read-only; the validator and read-only URI are
   defense in depth, not a substitute for review.

## Polyglot boundary

The core stays Python. Other languages are permitted only at bounded
edges:

| Language | Current role | Authority |
| --- | --- | --- |
| Python | coordinator, policy, tools, CLI | owns decisions and actions |
| SQL | read-only reports over existing SQLite stores | none |
| Kotlin | Android node protocol client (`android/`) | device-local, fabric-gated |
| JavaScript | browser status board UI | none (token-gated read-only fetch) |

A new language service must reuse the existing bus, store, policy
engine, and command path. It must not own approvals, credentials,
durable state, or a second scheduler. If a helper cannot be bounded
that way, it does not belong in JARVIS.
