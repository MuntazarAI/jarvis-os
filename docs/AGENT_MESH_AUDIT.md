# Agent Mesh audit (ground truth, 2026-10-04)

## Existing agent architecture
`jarvis/agents/`: contract.py (AgentCard/AgentResult/Skill/SkillRegistry,
30 role cards, no versions), agents.py (AgentRegistry spawn/shutdown,
Planner with VERB_TOOL mapping + DAG validation, Supervisor
submit/run_task/verify), orchestrator.py (OrchestratorContext injection,
Budgets, RunRecord traces persisted, blackboard, bus, TEAMS, FALLBACKS,
_gated_tool through PolicyEngine, 24 role handlers), blackboard.py
(versioned entries), bus.py (typed messages + classification).

## Existing orchestration
Supervisor owns task lifecycle; Orchestrator owns goal runs with depth/
budget/deadline/cancellation. CLI `agents run/status/teams/explain`
already wired. No new orchestrator needed.

## Tool architecture
ToolRegistry with required_permissions per tool; python_run AST
whitelist; terminal_run shlex, no shell, capped timeout. PolicyEngine
`permitted()`/`evaluate()` + approvals authoritative.

## Integration opportunities taken
Least-privilege gate, tester role, chain guard, card versions.

## Architectural conflicts found
- Planner VERB_TOOL can emit web_fetch/system_probe for coder steps;
  coder card lacks them → now denied by gate (correct: planner should
  route such steps to researcher/computer roles; documented).
- `_h_browser`/`_h_devops` used foreign actor names ("researcher",
  "computer"); devops fixed, browser kept (researcher skills cover
  web_fetch; renaming would change trace attribution — accepted).

## Duplicate-system risks (all avoided)
No second planner/policy/memory/tools/events/trace/registry/scheduler.
New files: none in jarvis/ except edits to contract.py + orchestrator.py.
Tests: tests/test_agent_mesh.py only.
