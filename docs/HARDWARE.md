# Hardware Compatibility Matrix

JARVIS-OS is designed to scale down to ordinary developer hardware and up to dedicated nodes. Compatibility below distinguishes architecture support from tested support.

| Target | Intended role | Current status | Evidence |
|---|---|---|---|
| Linux laptop | Primary local runtime | Supported architecture | Python test suite + local development |
| Android phone | Mobile JARVIS node | Transport/app work in progress | Android node tests; real-device transport tracked separately |
| Raspberry Pi | Edge/device node | Planned | Architecture supports typed device fabric |
| GPU workstation | Accelerated models/vision | Optional | Model/runtime dependent |
| CPU-only host | Core orchestration | Supported | Dependency-light core |
| Tailscale network | Remote node connectivity | Transport-ready design | Requires deployment/network configuration |

## Reporting a new device

Record:

- exact model
- CPU/GPU/RAM
- operating system and version
- Python/JDK/SDK versions
- connected peripherals
- transport used
- features tested
- benchmark output
- known limitations

Do not mark a device as fully supported because code merely imports on it.

## Compatibility levels

- **Architecture** — code is designed for the target.
- **Build** — artifacts build successfully.
- **Smoke-tested** — a minimal real execution was verified.
- **Tested** — meaningful feature tests passed.
- **Validated** — sustained or benchmarked real-world testing exists.

See the Android and device-fabric documentation for node-specific details.
