# API Reference Map

JARVIS-OS exposes Python modules, a CLI, and typed device/plugin boundaries. Internal modules can change quickly; this page is the stable map for contributors.

## CLI

The package installs the `jarvis` command through `jarvis.cli:main`.

Use:

```bash
jarvis --help
```

## Core boundaries

- `jarvis.core` — runtime/core configuration and shared orchestration.
- `jarvis.device` — device identity, routing, policy-gated commands, and transport.
- `jarvis.memory` — memory storage, retrieval, consolidation, and boundaries.
- `jarvis.neural` — spiking neural subsystem.
- `jarvis.plugins` — dependency-light typed plugin SDK.
- `jarvis.world` — world-state modelling and temporal context.

## Stability

Public documentation describes contracts at the boundary level. Internal implementation details are not guaranteed stable between minor architecture releases.

## Generating deeper API documentation

For local exploration, Python's standard tools are dependency-free:

```bash
python -m pydoc jarvis
python -m pydoc jarvis.device
python -m pydoc jarvis.neural
```

A generated API site may be added later once module import requirements are suitable for deterministic documentation builds.
