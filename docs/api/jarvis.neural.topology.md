# `jarvis.neural.topology`

## Members

### `ConnectomeSchema` (class)

ConnectomeSchema(name: 'str', origin: 'str' = 'synthetic', populations: 'list[PopulationSpec]' = <factory>, projections: 'list[ProjectionSpec]' = <factory>)

### `PopulationSpec` (class)

PopulationSpec(name: 'str', count: 'int', threshold: 'float' = 1.0, leak: 'float' = 0.9, refractory_steps: 'int' = 0, role: 'str' = 'sensory')

### `ProjectionSpec` (class)

ProjectionSpec(source: 'str', target: 'str', fan_out: 'int' = 8, weight_low: 'float' = 0.1, weight_high: 'float' = 0.5, delay_min: 'int' = 1, delay_max: 'int' = 3, recurrent: 'bool' = False)

### `SyntheticGenerator` (class)

Deterministic synthetic topology generator (TESTING ONLY).

### `build_network` (function)

Generate + compile a SparseLIFNetwork from a schema (deterministic).

### `load_schema` (function)

Load a schema from a JSON file (synthetic or measured dataset).

### `validate_edges` (function)

Check a concrete edge list against network bounds.
