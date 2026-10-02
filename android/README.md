# JARVIS Node — Android app (milestone 3.9)

Companion app that turns an Android phone into a first-class Device Fabric
node. It mirrors the core-side contract in `jarvis/device/android.py`
(11 capabilities, SAFE command allowlist, typed events, bounded telemetry).

## Honest build status

This is a **real, minimal Gradle + Kotlin project** — not a mock. But:

- It has **not been compiled here**: this environment has no Android SDK,
  no emulator, and no physical device. Host-side verification is done with
  `FakeAndroidNode` semantics through the core in-process transport
  (`tests/test_android_node.py`); nothing in the test suite claims to run
  Kotlin or Gradle.
- To build it you need the Android SDK (API 34), JDK 17, and
  `./gradlew :app:assembleDebug` from this directory. Until someone runs
  that on a real machine, treat the app as **source-reviewed, not
  build-verified**.
- Only `InProcessLink` ships: there is **no LAN/WebSocket/Internet
  transport** in 3.9. The app cannot reach a core over a network yet.

## Pairing (explicit, never automatic)

1. Core: `jarvis device android register --name <name> --model <model>
   --android-version <v> --app-version <a>` → prints a 6-digit code.
2. Enter the code in the app (or core CLI `pair --device <id> --code <code>
   --node <node-id>` for local testing).
3. Core records the trust decision with actor + reason. Only then can the
   node heartbeat, declare capabilities, or receive commands.

## Security model

- Capability ≠ permission ≠ authorization. A declared capability still
  needs the Android runtime permission AND a per-command core authorization
  (`PolicyEngine` → `DeviceRouter`). Revoking either side stops execution.
- SAFE command allowlist only (see `Commands.kt` ↔ `SAFE_COMMANDS`):
  no shell, no eval, no filesystem access, no ADB.
- Device text (notifications, SSIDs) is untrusted data: scanned and
  sanitized core-side before it touches prompts, dots, or memory.
