# JARVIS-OS Documentation

JARVIS-OS is a local-first AI operating system architecture for agents, memory, world modeling, device orchestration, neural computation, and secure automation.

## Start here

- **[GitHub repository](https://github.com/MuntazarAI/jarvis-os)** — source code and project history
- **[README](https://github.com/MuntazarAI/jarvis-os#readme)** — project overview and quick start
- **[Security](https://github.com/MuntazarAI/jarvis-os/blob/main/SECURITY.md)** — security policy and reporting
- **[Contributing](https://github.com/MuntazarAI/jarvis-os/blob/main/CONTRIBUTING.md)** — development workflow
- **[Roadmap](https://github.com/MuntazarAI/jarvis-os/milestones)** — planned work

## Architecture

JARVIS-OS is organized around explicit boundaries:

1. **Intelligence** — agents, planning, memory, world model, and neural computation.
2. **Perception** — typed sensory inputs and bounded event streams.
3. **Action** — policy-gated typed commands rather than unrestricted execution.
4. **Device fabric** — laptop, Android, and future edge/robotic nodes.
5. **Security** — identity, trust, authorization, least privilege, and auditable boundaries.

## Core design principle

The language model is not the security boundary. Model output is treated as a proposal and must pass deterministic policy and capability checks before a device action can occur.

## Documentation map

| Area | Purpose |
| --- | --- |
| docs/NEURAL_NERVOUS_SYSTEM.md | Neural subsystem architecture |
| docs/ANDROID_NODE.md | Android node design |
| docs/ANDROID_TRANSPORT.md | Android transport and pairing |
| docs/ | Technical architecture and implementation notes |

## Development

Clone the repository, create an isolated Python environment, install the project and run the test suite. The repository CI matrix tests supported Python versions on every pull request to main.

See the repository README for the exact current setup commands.
