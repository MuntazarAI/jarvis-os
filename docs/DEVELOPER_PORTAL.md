# JARVIS-OS Developer Portal

## Start here

1. [README](../README.md) — project overview.
2. [Contributing](../CONTRIBUTING.md) — contribution workflow.
3. [Security](../SECURITY.md) — security reporting.
4. [Architecture decisions](adr/README.md) — why the system is shaped this way.

## Build areas

| Area | Entry point |
|---|---|
| Core runtime | `jarvis/` |
| Agents | agent modules and planner |
| Memory | `jarvis/memory/` |
| World model | world-model modules |
| Device fabric | `jarvis/device/` |
| Android node | `android/` |
| Neural system | `jarvis/neural/` |
| Plugins | [Plugin SDK](PLUGIN_SDK.md) |
| Benchmarks | `benchmarks/` |
| Tests | `tests/` |

## API

See [API map](API.md). The API documentation intentionally describes public architecture and stable entry points rather than promising every internal class is stable.

## Development loop

```text
change → focused test → full relevant tests → benchmark/security check
      → commit → PR → review → merge → release
```

## Evidence policy

Documentation must distinguish:

- implemented
- experimentally implemented
- tested
- planned
- conceptual

Avoid marketing language that turns a roadmap item into a current capability.
