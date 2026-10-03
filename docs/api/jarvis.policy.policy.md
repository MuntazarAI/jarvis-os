# `jarvis.policy.policy`

## Members

### `PolicyDecision` (class)

PolicyDecision(allow: 'bool', risk: 'float', risk_level: 'RiskLevel', requires_approval: 'bool', reasons: 'list[str]' = <factory>, mitigations: 'list[str]' = <factory>, decided_at: 'float' = <factory>)

### `PolicyEngine` (class)

Permission policies, privacy boundaries, approval workflow, audit.

### `RiskEngine` (class)

Impact × probability × reversibility scoring with blast-radius checks.
