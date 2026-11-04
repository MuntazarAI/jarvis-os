# Security Intelligence 1.0

JARVIS-native defensive security: a durable, evidence-backed layer that
finds, validates, explains, and re-verifies security issues in code and
configuration **you explicitly own**. It is composed from existing
subsystems — it is not a second scanner runtime, task engine, policy
engine, store, or security authority.

## Scope and authorization

Analysis is limited to:

- local repositories and worktrees supplied with `--target`,
- files inside those repositories,
- already-authorized LAN targets through the existing, separately gated
  `security scan` path (`--yes` plus `--allow-nonlocal`).

`SecurityManager` refuses filesystem roots, missing paths, and JARVIS
sensitive state (`secrets.json`, vault keys, approval stores). There is
no target discovery, credential theft, brute force, persistence, evasion,
malware, destructive exploitation, or policy bypass. Findings are leads
with evidence, not proof of exploitability.

`validate_scope()` takes an explicit `authorized=True` signal. That
signal only means "the operator supplied this path"; it is not a policy
grant and authorizes nothing beyond reading the target.

## Architecture

```
jarvis security intel --target <repo>
        │
        ▼
SecurityManager (jarvis/security/intel.py)  ── composition boundary
        ├── review_path()        deterministic static analysis (read-only)
        ├── FindingStore         one finding contract + atomic JSON store
        ├── DurableRunner/TaskStore  crash-safe task, shared task engine
        ├── PolicyEngine         grants, approvals, e-stop, audit
        └── ToolRegistry         filesystem_write for approved remediation
```

One authoritative task store, one policy engine, one finding store, one
tool registry. Specialist agents call the same manager; they do not get a
private scanner or a parallel write path.

### Durable steps

`security intel` creates a normal durable task with four steps:

1. `scope` — validate the supplied local target.
2. `discover` — run the deterministic scanner (read-only).
3. `validate` — re-check each recorded rule at its source location.
4. `report` — write the bounded, scrubbed JSON report.

Interrupted work is never reported as success. Paused, cancelled, failed,
or still-running tasks return `complete: false` / `verification:
unverified` (or `partial` for completed-but-unverified work). A scan that
hits the file/finding limits is marked `truncated` and treated as
incomplete, never as a clean pass. Resume with the existing task surface:

```bash
jarvis task resume <task-id>
jarvis task status <task-id>
```

The emergency stop is checked before task start and before remediation;
while engaged, security work is refused.

## Finding contract

`jarvis/security/findings.py` defines one shape for every security
surface (static review, audit tools, Strix evidence, and the manager).

| field | meaning |
|---|---|
| `finding_id` | stable `sec-<sha12>` derived from root, asset, kind, and location |
| `title`, `category`, `kind` | bounded description and rule identity |
| `severity` | `critical` / `high` / `medium` / `low` / `info` / `unknown` |
| `asset`, `location` | file or host plus line/URL location, no secrets |
| `evidence` | bounded `EvidenceRef` records (kind, ref, detail, digest) |
| `confidence` | deterministic 0.0–1.0 score, never certainty |
| `provenance` | scanner/rule/agent origin |
| `state` | lifecycle state (below) |
| `validation`, `reproduction`, `verification` | separate evidence axes |
| `remediation` | proposal, hashes, status, preview; never raw content |
| `created_at`, `updated_at`, `validated_at`, `remediated_at`, `verified_at` | timestamps |
| `task_id`, `agent_id`, `trace_id` | durable/agent linkage |
| `history` | bounded state-transition trail |

All text is bounded and scrubbed at the boundary. Credential-shaped spans
(assignments, bearer tokens, URL userinfo, cloud keys) are redacted before
they enter a finding, report, board snapshot, or trace.

### Lifecycle

```
discovered → suspected → validated → remediated → reverified
      │           │           │            │
      ├───────────┴───────────┴──→ false_positive
      └───────────┴───────────┴──→ inconclusive → suspected/validated
```

- `discovered` — scanner produced a lead.
- `suspected` — evidence suggests an issue but has not been re-checked.
- `validated` — the recorded rule was re-checked at the source.
- `remediated` — a reviewed change was applied and hashed; **not fixed**.
- `reverified` — a post-change re-check no longer finds the rule. Only
  this state means the issue is resolved.
- `false_positive` — explicitly dismissed with evidence; terminal.
- `inconclusive` — the rule vanished, the file moved, or source changed
  during analysis. Not assumed fixed, and still counted as open.

Illegal transitions raise `FindingError`. A patch proposal never changes
the lifecycle state. `FindingStore.upsert()` is discovery semantics and
may reopen a previously remediated finding only when fresh evidence
arrives; explicit state changes use `save()`.

The store is atomic and `0600`. A corrupt file is quarantined and treated
as empty; it never parses into authority. `security findings` reports a
quarantined store with exit code `3`.

## Validation

`validate` re-runs the exact recorded rule against the source line:

- rule still matches → `validated` (and the location is updated if the
  line moved),
- rule absent → `inconclusive` ("resolved at source, not assumed fixed"),
- path/rule unknown → counted as `unknown`.

The CLI summary uses `resolved` for the absent case. That is a scanner
result, **not** a remediation result: it records `inconclusive`, keeps the
finding open, and makes the command exit `3` (partial), never `0`. A
pre-fix vanished rule cannot prove that a change was ever applied or
verified. Only post-change re-verification can close a finding.

## Remediation

Remediation is a reviewed, single-line change through the existing write
tool. The sequence is deliberate:

1. **Explain** — the finding carries location, evidence, severity,
   confidence, and guidance.
2. **Propose** — `propose_remediation()` re-checks the rule, selects a
   safe replacement (or requires `--replacement`), and records the
   pre-change file hash, line number, and replacement hash. State remains
   `validated`.
3. **Policy** — `PolicyEngine.evaluate(actor, plan)` must allow the
   registered `filesystem_write` tool (`fs.write`). The default actor is
   `security-manager`; grant it explicitly if that is your operator
   policy. No standing `sec.*` grant substitutes for this.
4. **Approval** — a fresh single-use approval is requested. It binds:
   target path, finding id, before hash, and replacement hash — never raw
   file content or credentials.
5. **Apply** — the single-use token is redeemed, then `filesystem_write`
   is called. The post-write hash must match the intended content.
6. **Re-verify** — `security verify` first confirms the file still
   matches the recorded post-fix hash, then re-checks the rule at the
   source. `reverified` is the only success; a remaining rule becomes
   `inconclusive` with `verification: failed`, and a file changed after
   the approved write stays `remediated` with status `unknown`.

Failure modes are explicit: `stale_proposal` (file changed after
proposal), `proposal_mismatch`, `denied` (policy or approval),
`needs_approval`, `not_present`, `write_failed`, `write_mismatch`, and
`unknown` (including a file that changed after the approved write).
Before/after hashes and the redacted replacement preview are preserved in
the finding for evidence.

```bash
# 1. discover + validate
jarvis security intel --target ~/Projects/my-app --json

# 2. inspect findings
jarvis security findings --state validated --severity high

# 3. propose (no write, no approval yet)
jarvis security remediate --finding sec-abc123def456 \
  --replacement 'verify = True'

# 4. approve through the existing approval surface, then apply
jarvis approvals approve --token <prefix>
jarvis security remediate --finding sec-abc123def456 \
  --replacement 'verify = True' --approval <prefix> --actor security-manager

# 5. only a post-change re-check can close it
jarvis security verify --finding sec-abc123def456
```

The benchmark harness uses the same path with a local automated approver
(`auto_remediate`); it does not bypass policy, approval redemption, or
re-verification.

## CLI

```
jarvis security review   [--target PATH] [--json]
jarvis security scan     --target URL|PATH --yes [--allow-nonlocal]
jarvis security intel    [--target PATH] [--json]
jarvis security findings [--state S] [--severity S] [--json]
jarvis security validate [--finding ID] [--json]
jarvis security remediate --finding ID [--replacement LINE]
                         [--approval TOKEN] [--actor ACTOR] [--json]
jarvis security verify   --finding ID [--json]
jarvis security bench    [--target CORPUS] [--json]
```

Exit codes are API:

| action | `0` | `1` | `2` | `3` |
|---|---|---|---|---|
| `review` | no high findings | high findings | — | error/incomplete scan |
| `scan` | clean | findings | refused/misuse | unavailable/error |
| `intel` | no open findings | open findings | refused scope | interrupted/failed/incomplete/error |
| `findings` | listed | — | — | quarantined/unavailable |
| `validate` | all known | — | unknown id | unknown/error |
| `remediate` | applied (not yet verified) | not present | approval/denied/misuse | write failed/unavailable |
| `verify` | reverified | still present | not remediated/refused | unknown/error |
| `bench` | passed | thresholds failed | — | corpus/error |

`review` and `scan` keep their previous exit semantics. Human output is
scrubbed; `--json` is bounded and machine-readable.

## Board and agents

`GET /api/board` includes a `security` snapshot key (posture, store
health, counts by severity/state, up to eight findings, and recent
security tasks). The board stays read-only, token-gated, and scrubbed:
findings in the snapshot never include evidence content, tokens, or
credentials. There is no parallel viewer.

The existing `security` role card is the manager. Seven least-privilege
specialists extend the roster (38 roles total): `code-security`,
`dependency-security`, `config-security`, `web-security`,
`secrets-exposure`, `remediation-verifier`, and `security-report`
(`may_act=False`). `TEAMS["security"]` runs seven stages within the
eight-agent budget:

```
security(scope) → code-security → config-security → dependency-security
→ secrets-exposure → remediation-verifier → security-report
```

Specialists only analyze. Remediation remains a manager operation behind
policy and approval. The read-only `code_security_scan` tool is SAFE but
requires `fs.read`; it returns scrubbed findings. Free-text local targets
from the orchestrator are restricted to paths under `$HOME` or the
current working directory.

## Benchmark

`jarvis/security/bench.py` runs a safe local corpus under
`tests/fixtures/security_bench/` — intentionally vulnerable toy files
with a ground-truth manifest. No network, no real targets, no models.

It copies each case to a temporary work tree (the corpus is never
modified), runs discovery, durable validation, and policy-approved
remediation, then measures:

- precision, recall, F1, false positives/negatives,
- validation rate,
- remediation verification rate,
- line-location accuracy,
- wall latency, CPU time, peak RSS,
- deterministic repeat scans.

```bash
jarvis security bench --target tests/fixtures/security_bench --json
```

The benchmark passes only when the corpus yields the expected findings
and predicted findings, at least one remediation is attempted, precision
and recall are ≥ 0.9, validation is ≥ 0.8, line accuracy is ≥ 0.8,
remediation verification is ≥ 0.8, and repeat scans are deterministic.
A reference run on the six-case corpus reports 20/20 matched findings,
precision/recall 1.0, validation 1.0, remediation 1.0, and line accuracy
1.0. Treat those numbers as a regression baseline for the corpus, not a
claim about arbitrary code.

## Safety boundaries and limitations

- **Static analysis is heuristic.** Rules find patterns; they cannot
  prove exploitability. `validated` means "re-checked", not "exploitable".
- **Remediation is single-line and reviewed.** It is not automated
  refactoring; multi-line fixes require an operator-authored change.
- **No offensive capability.** The layer does not discover targets, crack
  credentials, persist, evade, or exploit. `security scan` remains a
  separate Strix bridge with its own authorization gate.
- **Secrets are redacted, not recoverable.** Redaction is best-effort
  pattern scrubbing; do not place live credentials in a scanned tree.
- **TOCTOU is bounded, not eliminated.** Remediation hashes the file
  before and after and rejects stale proposals, but another process can
  still race between check and write.
- **The board is a snapshot.** It is not a real-time monitor and does not
  execute actions.
- **DNS/redirect gaps remain** for the dynamic scan path; see
  `docs/SECURITY_AUDIT_TOOLS.md`.

## Tests

Comprehensive coverage lives in `tests/test_security_intel.py`, with
scanner coverage in `tests/test_secaudit.py` and board coverage in
`tests/test_board.py`. Tests are deterministic: tmp homes, toy fixtures,
no network, no models. The corpus manifest and fixture hashes are
asserted unchanged after a benchmark run.
