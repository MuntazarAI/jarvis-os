---
name: verification-loop
description: Six-phase verification for JARVIS-OS work — compile, targeted tests, full pytest, CLI exit codes, secret/security probes, and diff review — ending in a PASS/FAIL report. Use after a feature, refactor, or security fix and before a commit or PR.
license: MIT
metadata:
  origin: ECC
  upstream: ecc-universal@2.2.3
  upstream_repository: https://github.com/affaan-m/ECC
  adapted_for: JARVIS-OS
---

# Verification Loop (JARVIS-OS)

Adapted from ECC's `verification-loop` skill for this repository's
Python/pytest workflow. A green run is not proof: check that the test
would have caught the bug, and treat CLI exit codes as API.

## When to use

- After completing a feature, refactor, or security fix.
- Before staging a commit or opening a PR.
- When a previous run was interrupted and you need to re-establish a
  clean baseline.

## Phase 1 — Baseline and compile

```bash
git status --short
git diff --stat
.venv/bin/python -m compileall -q jarvis tests
```

If compilation fails, stop and fix it before running tests.

## Phase 2 — Targeted tests

Run the suites that own the changed behavior first:

```bash
.venv/bin/python -m pytest tests/test_device_fabric.py \
  tests/test_sec_approvals.py tests/test_secaudit.py -q
```

For a UI or API surface, include the matching page/board tests. For an
agent surface, include `tests/test_agent_mesh.py` and
`tests/test_agent_reach.py`.

## Phase 3 — Full suite

```bash
.venv/bin/python -m pytest tests/ -q
```

Record the exact pass/fail/skip counts. Do not summarize a failure as
"mostly green"; a single failure is a FAIL.

## Phase 4 — CLI exit codes

Exit codes are API. Probe the read-only commands in a throwaway home:

```bash
.venv/bin/python -m jarvis.cli --home /tmp/jarvis-verify status
.venv/bin/python -m jarvis.cli --home /tmp/jarvis-verify doctor
.venv/bin/python -m jarvis.cli --home /tmp/jarvis-verify task doctor
.venv/bin/python -m jarvis.cli --home /tmp/jarvis-verify agents reach health
```

Expected:

| Command | Healthy exit |
| --- | --- |
| `status` | `0` |
| `doctor` | `0` |
| `task doctor` | `0` |
| `agents reach health` | `0` = ok, `1` = degraded, `2` = unknown |

An `unknown` reachability result is not a pass. Report it as unknown.

## Phase 5 — Security and secret probes

```bash
grep -rn "shell=True\|os.system" jarvis tests
grep -rn "innerHTML" jarvis/api
grep -rn "approved(" jarvis | grep -v "peek"
grep -rn "sk-\|ghp_\|xoxb-" jarvis tests
```

Check that:

- every tool call still passes `PolicyEngine`;
- no approval path trusts `approved()` without consuming;
- sensitive output is redacted and marked;
- no new secret appears in logs, traces, fixtures, or board payloads.

## Phase 6 — Diff review

```bash
git diff --check
git diff --stat
git diff
```

Read the diff for:

- accidental edits outside the intended scope;
- debug prints, temporary paths, or commented-out code;
- a second registry, scheduler, policy engine, or memory store;
- tests that assert `True` or `is not None` without a contract;
- generated files or pre-existing user changes that must not be
  committed.

## Report format

```text
verification: verified | failed | unknown
compile: pass
targeted: 42 passed
full: 812 passed, 3 skipped
cli: status=0 doctor=0 task=0 reach=ok
security: no findings
diff: 6 files, no out-of-scope changes
```

Use `verified` only when every phase ran and passed. Use `unknown` when
a phase could not run (missing hardware, unavailable service) and say
why. Never turn an unknown into an ok.
