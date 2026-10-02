# JARVIS-OS Documentation

Welcome to the documentation hub.

## Start here

1. **[Architecture guide](ARCHITECTURE.md)** — understand the major subsystems and how they interact.
2. **[Unified master map](JARVIS_FULL_MASTER_MAP_UNIFIED.md)** — the detailed system specification.
3. **[Project README](../README.md)** — installation, commands, status, roadmap, and development principles.

## Documentation map

| Area | Primary location |
|---|---|
| Core architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Full specification | [JARVIS_FULL_MASTER_MAP_UNIFIED.md](JARVIS_FULL_MASTER_MAP_UNIFIED.md) |
| Memory | `jarvis/memory/` + master map |
| World model | `jarvis/world/` + master map |
| Cognition | `jarvis/cognition/` + master map |
| Agents | `jarvis/agents/` + master map |
| Tasks/workflows | `jarvis/tasks/` + master map |
| Models | `jarvis/models/` + master map |
| Security/policy | `jarvis/security/` + `jarvis/policy/` |
| Voice/vision | `jarvis/voice/` + `jarvis/vision/` |
| API | `jarvis/api/` |

## Documentation rule

When implementation and specification disagree, the implementation and automated tests are the source of truth for current behavior. Update the documentation when a subsystem changes materially.
