# Multimodal Perception (4.3)

Read-only observation providers feeding the existing nervous system:
contract → providers → `PerceptionPipeline` → `SensoryBus` → world,
memory, spatial → `CognitiveSupervisor`. Perception never acts — no
sockets, no commands, no loops, no planning, no policy decisions.

## Architecture

```
screen shot / camera frame / file / image
        │  (one-shot, bounded, lifecycle-explicit)
        v
PerceptionProvider (screen/camera/image/file)
        │  OCR (tesseract / fake) + objects (fake / future local ML)
        v
Observation (typed, bounded, provenance-aware)
        │  validation (fail closed) + secret-key refusal
        v
PerceptionPipeline.ingest
   ├─ ChangeDetector (bounded fingerprint cache; repeats suppressed)
   ├─ ObservationStore (JSONL + bounded index, cross-process reads)
   ├─ SensoryBus (reference event only, never media)
   ├─ WorldRegistry (claims; auto-apply: file entities ≥0.85 only)
   ├─ MemoryPalace (PUBLIC/LOCAL, confidence ≥0.5, scrubbed)
   └─ SpatialMemoryPalace (screen bboxes as measured; camera
       left_of relations only — never invented coordinates)
        │
        v
CognitiveSupervisor.process(bus_event) → 13 stages → outcome
```

## Observation contract (`perception/contract.py`)

`observation_id, timestamp, source, source_device, modality
(SCREEN|CAMERA|FILE|IMAGE|DOCUMENT|SENSOR), payload, confidence
0..1, provenance, privacy_class (PUBLIC|LOCAL|SENSITIVE|PRIVATE),
ttl_s, correlation/cycle ids`. Payloads are structured metadata —
never binary. Explicit caps (`MAX_*` constants). Fingerprint
(sha256 of modality+payload) drives change detection.

## Providers

| Provider | Backends | Honesty rule |
|---|---|---|
| screen | gnome-screenshot/scrot/`import`/ffmpeg x11grab, tesseract, xdotool* | missing backend → `status: unavailable` |
| camera | fswebcam/ffmpeg v4l2; `start/stop/observe_once/sample≤10` | never a daemon; frames deleted |
| image | magic bytes, size/sha256, PNG dims (or optional PIL) | unknown format → `unsupported` |
| file | txt/md/json/csv/log (+yaml/toml only with parsers) | credential paths refused; CSV capped 5000 rows |

`*` optional. OCR confidence is 0.6-heuristic labeled as such
(tesseract CLI exposes none); empty means 0.0. No bundled ML
models: object detection reports unavailability; fakes are
deterministic and test-only. Persons are always anonymous —
identity-shaped labels are refused.

## Privacy / retention

- `PRIVATE`: ephemeral — bus only, never stored/indexed anywhere.
- `SENSITIVE`: working context only — no durable memory.
- Credential stores can never be observed (blocked paths/names).
- Credential spans (PEM blocks, AKIA/ghp_/xox tokens) are redacted
  at the OCR boundary (kinds logged, values never).
- Free prose under innocent keys is NOT rewritten (pinned by test;
  same convention as snapshots).
- Raw frames/screenshots are deleted after extraction, never persisted.

## Replay

Recorded structured observations replay through the existing
sandbox (no executor, stubbed side-effecting hooks). Providers are
never invoked during replay (proven: provider call counts unchanged).

## CLI

`intelligence perception-status|perception-observe [--source
screen|camera|file|image] [--path] |perception-events|
perception-inspect --observation ID`. One-shot only; bounded
output; unavailable hardware degrades to structured messages.

## Android seam

`perception/android.py`: closed event set (`camera.snapshot`,
`screen.describe`) mapping to modalities; bounded scalar payloads;
no transport/policy/pairing changes. Full Android perception is a
future milestone.

## Threat model (see code for details)

Fail-closed validation; credential-store refusal; row/nesting/size
caps; fixed-arg subprocess only (no shell); bounded caches/queues;
lane between perception and action runs exclusively through
PolicyEngine + DeviceCommandService (perception has no path to
either — verified by test).

## Proven real (2026-10-03, this workstation)

- Screen: ffmpeg x11grab capture + pipeline (honest empty OCR).
- Camera: v4l2 `/dev/video0` frame + pipeline (honest result).
- OCR: ffmpeg-rendered `DEPLOY OK 123` read back exactly by
  tesseract; PNG dims parsed with zero new dependencies.
- Benchmarks: validate 6µs, fingerprint 4µs, bus event 6µs,
  full ingest (world+memory) 0.27ms.

## Not built (honest futures)

Audio/microphone pipeline, STT integration, bundled ML object
detection, EncryptedSharedPreferences-equivalent secret storage
for observations, longer idle lane allowance, push notifications
for approvals.
