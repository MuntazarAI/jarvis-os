# Agent Mesh 1.0

Disciplined specialists on the existing Agent Intelligence 2.0 substrate:
one contract, one registry, one orchestrator, one policy authority.
No second planner/policy/memory/tools/event/trace system was created.

## Audit findings (what already existed)

- `AgentCard`/`AgentResult`/`Skill`/`SkillRegistry` contracts (30 roles)
- `AgentRegistry` (spawn/shutdown/capability lookup), `Planner`
  (plan/validate/DAG/independent groups), `Supervisor`
  (submit/run_task/verify), `Orchestrator` (budgets, depth, teams,
  fallbacks, per-role isolation, traces, blackboard, bus)
- `_gated_tool`: every tool call through PolicyEngine (unchanged)
- Gaps found and closed: no least-privilege check (any role could
  request any tool, policy permitting); no Tester role; a devops
  health read ran under the wrong actor name; no delegation-chain
  guard; no card versions.

## Added (minimal extensions)

- `AgentCard.version` ("1.0", in `to_dict`, traced per result)
- `tester` role card (skills `code.test`, analyst/fast) + `_h_tester`:
  bounded pytest on validated in-repo paths only (traversal-proof),
  never weakens tests, structured verified/failed verdict
- Least-privilege gate in `_gated_tool`: tool must belong to the
  acting role's declared skills (SkillRegistry-backed); PolicyEngine
  stays authoritative after the gate
- `_h_devops` actor corrected to `devops`
- Delegation chain in run state; 3rd revisit of a role fails
  (verifier×2-style legitimate reuse still allowed)

## Least privilege map (enforced)

A tool passes the gate iff it is in the role's declared skills, or
every permission it requires is in the role's declared permissions
(this keeps permissionless observables like `system_probe` working for
any role, exactly as the policy layer already treats them).
PolicyEngine authorizes every actual call afterwards.

| role | representative reach |
|---|---|
| researcher/browser | web_fetch (net.fetch declared) |
| coder/debugger | fs read/write, exec (declared); web_fetch denied |
| tester/verifier | test exec, probes; web/filesystem-write denied |
| reviewer/critic | advisory only (may_act=False, no tool path) |

## Measured (this host)

startup 39.6ms · single-role run 0.4ms · 5-role team 23.7ms ·
tracemalloc 552KB current / 584KB peak. No heavyweight models held.

## Security model

Roles declare capabilities; PolicyEngine authorizes. Handoffs are
typed `AgentResult`s — a researcher's text never authorizes an
engineer. Injection scans live in the security handler; sessions are
per-run boards (no cross-run leakage). Shell exists only inside
audited tools behind policy, never from agent language.

## Extension

New role = AgentCard (skills from the existing SkillRegistry) +
handler returning AgentResult + tests. No new registries.
