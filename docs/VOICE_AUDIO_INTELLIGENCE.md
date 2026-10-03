# Voice & Audio Intelligence 5.1

Local-first voice as a sensory/output modality of the existing
intelligence architecture — not a second brain, not a toy demo.

JARVIS voice = **Chatterbox** (local) + Chatterbox reference sample
`male_old_movie.flac`, selected as the JARVIS voice identity. The sample
is a Chatterbox reference prompt, not an official JARVIS voice.

Reference:
`https://storage.googleapis.com/chatterbox-demo-samples/prompts/male_old_movie.flac`

## Architecture

```
microphone
  ↓  MicRecorder (existing, arecord/sounddevice)
existing EnergyVAD → speech segmentation (existing)
  ↓
existing Transcriber / faster-whisper STT (independent of TTS)
  ↓
AudioFrame/Segment + SpeechRecognitionResult (typed contracts)
  ↓
event_from_transcript → existing SensoryBus (type: speech)
  ↓
existing CognitiveSupervisor → reasoning / memory / planning
  ↓
existing PolicyEngine → approval if required → existing tools/devices
  ↓
response text
  ↓
TTSRequest → TTSProvider abstraction → ChatterboxTTSProvider (local)
  ↓  fallback: existing espeak/piper → text-only
reference voice male_old_movie.flac (configurable)
  ↓
AudioOutput (aplay/paplay/ffplay) / FakeAudioOutput in tests
```

Reused, never duplicated: MicRecorder, EnergyVAD, Transcriber,
WakeWordDetector, VoiceLoop/VoicePipeline, SensoryBus,
CognitiveSupervisor, IntelligenceLoop, PolicyEngine, DeviceCommandService,
memory/learning, device fabric.

New: `jarvis/voice/tts.py` (TTSRequest/TTSResult, Chatterbox/Fake/
LocalFallback/Unavailable providers), `voice_profile.py` (JARVIS calm/
mature/controlled profile), `output.py` (playback abstraction),
`session.py` (VoiceSession + correlation chain), `telemetry.py`
(structured voice metrics), `setup.py` (explicit reference install),
`speak.py` (response→TTS→playback wiring, priority + fallback).

## Configuration

`JarvisConfig.voice`: enabled, stt_provider (`faster-whisper`, never
replaced by TTS work), tts_provider (`chatterbox`), profile (`jarvis`),
reference_audio (`~/.config/jarvis/voices/male_old_movie.flac`,
overridable via `JARVIS_VOICE_REFERENCE`), language, style, emotion,
model, output format/sample_rate/device, exaggeration (0.5),
temperature (0.8), cfg_weight (0.5), retain_audio=false,
retain_transcripts=false, playback_backend, timeout_s, queue_max.

No machine-specific absolute paths. No cloud TTS required.

## Setup

```bash
jarvis voice status    # provider, reference, backends
jarvis voice setup     # explicit download + verify of male_old_movie.flac
jarvis voice test      # deterministic, no mic/GPU/net
jarvis voice-test      # same self-test (alias)
jarvis voice benchmark # fake measured; chatterbox measured on demand only
jarvis say "Hello"     # chatterbox → fallback → text-only, never crashes
jarvis listen          # mic → STT → think → speak (existing loop)
jarvis doctor          # voice:* diagnostics, no secrets
```

Model install (once, then local):
`pip install chatterbox-tts`. Inference stays on-device (CPU/GPU per
host). Missing runtime/reference/model fails gracefully with a clear
error — never a silent voice switch, never a cognition crash.

## Security / privacy

Transcript = untrusted input → perception → cognition → policy →
approval → existing command path. TTS synthesizes text only (never
executes tools/devices/memory). Replay/simulation never touch
mic/audio/devices/network. Raw audio transient by default, never
logged; transcripts transient unless explicitly retained; telemetry
carries lengths/latencies/statuses only. Wake word ≠ authentication.
Learning never grants permissions.

## Testing

`tests/test_voice_tts_51.py` (25 tests): provider contract, fake TTS,
missing/invalid reference, unavailable runtime, bounds, session/
correlation, telemetry hygiene, speak wiring, cognitive handoff,
replay/simulation, CLI/doctor, E2E fake loop; real Chatterbox test
skips honestly when unavailable (`NOT AVAILABLE`, never fake-passed).

## Status / limitations (this host)

Chatterbox runtime: NOT AVAILABLE (not installed). Reference audio:
MISSING (setup not run). Microphone: backend present (arecord), content
recording NOT TESTED. Playback: aplay present, audible output NOT
TESTED. Raspberry Pi audio: HARDWARE-PENDING. faster-whisper: installed
but runtime blocked by PyAV `metadata_errors` incompatibility (STT and
TTS tracked independently). Benchmarks: fake measured only; no
real-time claims.
