# `jarvis.cognition.goals`

## Members

### `Constraint` (class)

Constraint(kind: 'str', detail: 'str', limit: 'float | None' = None)

### `CriticVerdict` (class)

str(object='') -> str

### `Goal` (class)

Goal(goal_id: 'str' = <factory>, description: 'str' = '', desired_state: 'str' = '', success_criteria: 'list[str]' = <factory>, failure_criteria: 'list[str]' = <factory>, constraints: 'list[Constraint]' = <factory>, required_capabilities: 'list[str]' = <factory>, risk_level: 'str' = 'low', created_at: 'float' = <factory>)

### `GoalInterpreter` (class)

Deterministic request -> Goal decomposition. Inspectable.

### `HierarchicalPlan` (class)

HierarchicalPlan(plan_id: 'str' = <factory>, goal: 'str' = '', objectives: 'list[str]' = <factory>, steps: 'list[PlanStep]' = <factory>, verification: 'dict[str, Any]' = <factory>, recovery: 'str' = '', max_depth: 'int' = 2)

### `HierarchicalPlanner` (class)

MISSION -> OBJECTIVES -> TASKS -> ACTIONS over MissionPlanner.

### `PlanCritic` (class)

Pre-execution validation: VALID | NEEDS_REVISION | BLOCKED.

### `PlanStep` (class)

PlanStep(name: 'str', kind: 'str' = 'action', args: 'dict[str, Any]' = <factory>, depends_on: 'list[int]' = <factory>, expected: 'str' = '', reversible: 'bool' = True)

### `PlanningError` (class)

Malformed goal/plan or bound violation.
