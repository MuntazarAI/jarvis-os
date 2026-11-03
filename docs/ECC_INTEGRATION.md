# ECC Integration

Curated integration of [ECC](https://github.com/affaan-m/ECC) into the
OpenCode workflow for this repository. ECC is MIT-licensed; the upstream
package, version, and per-file attribution live in
`.opencode/ECC_SOURCE.json` and `.opencode/ECC_LICENSE`.

## Decision: assets, not the npm plugin

`ecc-universal@2.2.3` ships an OpenCode **V1** plugin built against
`@opencode-ai/plugin`. OpenCode V2 (this checkout is verified with
`v2.2.5`) requires the V2 plugin API: a default export defined with
`Plugin.define({ id, setup(ctx) })` and `@opencode/plugin`. V1 plugin
implementations do not run in V2, and moving or renaming the config
entry is not enough.

Loading the npm plugin would therefore add a broken dependency. The
skills and agent prompts are plain Markdown, so this repository vendors
curated, adapted copies and does not load any plugin.

```json
// opencode.json — no "plugin" (V1) or "plugins" entry
{
  "$schema": "https://opencode.ai/config.json"
}
```

## What is included

| Asset | Kind | Use |
| --- | --- | --- |
| `security-review` | skill | Policy, approval, device, injection, and secret review |
| `python-patterns` | skill | Stdlib-first Python structure and typing |
| `python-testing` | skill | Deterministic pytest and regression-test quality |
| `verification-loop` | skill | Compile, targeted tests, full pytest, CLI, security, diff |
| `agent-harness-construction` | skill | Tool contracts, observations, recovery, budgets |
| `python-reviewer` | subagent | Read-only Python review |
| `security-reviewer` | subagent | Read-only threat-model review |
| `tdd-guide` | subagent | Test-first changes, limited edit and shell |

Skills are discovered automatically from `.opencode/skills/`. Subagents
are discovered from `.opencode/agents/` and can be requested by name:

```text
Use the security-reviewer subagent on the current diff.
Use the python-reviewer subagent on jarvis/device/router.py.
Use the tdd-guide subagent to add a replay regression test.
```

## Boundaries

- These assets are **guidance and review**, not authority. They do not
  grant permissions, approve actions, or bypass `PolicyEngine`.
- OpenCode subagents operate on repository files. They are separate from
  the JARVIS runtime roles in `jarvis/agents/`; the two registries are
  not merged.
- The `tdd-guide` subagent may edit only `tests/**` and `jarvis/**` and
  may run only pytest, `py_compile`, `git status`, and `git diff`.
- The review subagents are read-only: edit, shell, web, and nested
  subagent launch are denied.
- The agent-reach views (`jarvis agents reach`, `/api/agents/reach`)
  inventory these assets and report them as `ecc-skill` / `ecc-agent`.
  They add no reach of their own.

## Updating

1. Pin a new upstream version and inspect its skills/agents.
2. Adapt the content to this repository's rules; do not copy V1
   frontmatter into agents.
3. Update `.opencode/ECC_SOURCE.json` and, if the license changed,
   `.opencode/ECC_LICENSE`.
4. Run `.venv/bin/python -m pytest tests/test_ecc_integration.py -q`.
5. Run `.venv/bin/python -m jarvis.cli --home /tmp/jarvis-probe agents reach health`
   and confirm the harness check is `ok`.

## Verification

`tests/test_ecc_integration.py` checks:

- the manifest version, repository, license, and attribution;
- every listed asset exists and has the expected frontmatter;
- agents are V2-format (`mode`, `permissions`) with no legacy `tools`,
  `prompt`, `permission`, `disable`, or `maxSteps` fields;
- the review agents deny edit and shell;
- no V1 plugin or `@opencode-ai/plugin` dependency is configured;
- the reach inventory discovers five skills and three agents.
