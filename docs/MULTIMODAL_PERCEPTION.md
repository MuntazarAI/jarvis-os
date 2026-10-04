# Multimodal Perception 1.0 (consolidation)

No new perception subsystem. Audio/VAD/STT, camera/vision/screen,
SensoryBus/EventBus, and session context already exist and stay where
they are. This milestone adds one pure function —
`autonomy.perceive.correlate` — grouping existing observations by
session + bounded time window, flagging duplicates/stale/conflicts
and hostile content (data only, never executed).

## Contract

Input: observation dicts/objects with id/modality/type/timestamp/
session/confidence. Output: session clusters + counts (total,
duplicates, stale, hostile). Content bodies never required or stored.
Max 64 observations per call; window 0.5–300s (default 5s);
>1h old marked stale.

## Privacy

No microphone/camera/screen recording added. No raw media persisted
by correlation. Explicit session controls unchanged.
