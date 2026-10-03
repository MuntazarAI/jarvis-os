# Raspberry Pi Edge Intelligence Node (5.0)

A Raspberry Pi 5 as a typed JARVIS node: secure transport, pairing,
telemetry, sensors, camera, allowlisted GPIO, offline queueing, and
full cognitive integration. It is a node, NEVER a remote shell —
14 typed commands, zero shell/eval/subprocess paths.

## Architecture

```
JARVIS CORE (memory/reasoning/planning/learning/supervisor)
        │  Secure Device Fabric (framing/HMAC/trust/policy/audit)
   ┌────┴─────┐
 laptop   android   raspberry-pi
                         │ typed commands/results/events
                    PiNodeAdapter + PiSocketHost
                         │ PolicyEngine + approvals + outbox
                    Pi hardware providers (read-only)
```

Reused unchanged: DeviceRouter, FabricServer, DeviceAuthenticator,
PairingManager design, DeviceCommandService, outbox, approvals,
audit, perception contract, replay, CLI conventions.

## Pairing

DISCOVER → PAIR_REQUEST (6-digit single-use code, 600s TTL, 5
attempts) → PENDING → human APPROVE → TRUSTED → HMAC challenge →
ONLINE. No capability works before trust; lane spoofing rejected
(HMAC-bound device_id required, not hello-claimed node names).

## Commands (closed allowlist, `pi.*`)

`system.info/status/cpu/memory/storage/temperature`,
`network.status`, `camera.status/capture`, `sensor.read`,
`gpio.read/write` (allowlisted pins only, default deny, read-only
unless explicitly write-enabled), `led.set`, `audio.status`
(contracts only). Unknown names and bad args are refused before
any authorization check.

## Hardware (`jarvis/device/pi_hardware.py`)

System/Temperature/Network/Camera/GPIO/I2C/SPI/Audio providers,
each real/fake/unavailable. Real telemetry verified on dev host
(CPU/mem/disk/uptime, 58°C thermal, interfaces). GPIO writes exist
ONLY as validated commands, never in providers. I2C/SPI transfers
and audio capture are explicit future work (presence reported).

## Offline behavior

Commands to offline nodes queue durably (`pi-queue.json`, bounded
50, 300s TTL, drop-oldest counted, corrupt file recovers empty).
On reconnect the queue drains through the same authorized path.
Stale items expire; nothing executes silently. Event replay dedupes
by id and preserves timestamps/provenance.

## Edge vs core routing

`decide_execution_site()` (pure): private data stays local,
unauthorized asks humans, high risk goes to core with policy,
down networks run local, heavy compute goes to core, device.*
capabilities route to their node.

## Cognitive integration

Pi telemetry becomes `SENSOR` observations (perception contract)
→ SensoryBus → world claims → memory (privacy-gated) →
CognitiveSupervisor → beliefs → predictions → verified device
actions → experiences → learning. Proven live (see E2E below).

## Health, prediction, anomaly

`pi_health()` reports HEALTHY/DEGRADED/OFFLINE/UNKNOWN from facts
only. `predict_pressure()` forecasts threshold crossings
(EXPECTED/UNEXPECTED/PARTIAL/UNKNOWN). `AnomalyDetector` flags
threshold/spike anomalies without diagnosing causes. Automation
rules emit ALERT events only — never destructive recovery.

## Privacy

Camera observations default PRIVATE; raw frames deleted after
extraction (metadata/hash only); secrets never logged; credential
stores unobservable.

## Replay

Recorded observations replay through the sandbox; providers,
GPIO, camera, and commands are never touched.

## Real E2E (2026-10-03)

Socket: pair → trust → heartbeat → typed command → result →
event → reconnect, spoofing rejected, intruder denied (loopback,
deterministic). Cognitive: Pi telemetry → supervised cycle →
`pi.system.cpu` → VERIFIED → experience → belief → learning.
Hardware: real telemetry/camera/OCR probes on dev host.

No physical Pi 5 was available: real-device pairing over the
network is marked hardware-pending. Nothing here claims it.

## CLI

`pi list|show|pair|trust|revoke|status|health|capabilities|
sensors|telemetry|events|queue|doctor|camera|gpio|logs|command|
serve|approve` — bounded output, exit codes 0/1/2, no secrets.

## Benchmarks (dev host)

heartbeat 0.32ms, validate 0.3µs, anomaly 2µs, queue instant.
Normal load keeps the node responsive; all queues bounded.

## Limitations

No physical-Pi pairing proven; I2C/SPI transfers, audio capture,
and on-Pi inference are future; TLS/mTLS future (trusted LAN);
secrets in plain files (unchanged convention).
