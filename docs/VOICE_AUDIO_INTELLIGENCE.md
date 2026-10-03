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

Model install (once, then local). Official package is `chatterbox-tts`
(resemble-ai/chatterbox); tested on Python 3.11, `requires-python >=3.10`
(Python 3.14 needs torch>=2.9 — prefer the isolated 3.12 runtime below).
System Python is never touched; neither is the project `.venv`:

```bash
uv venv ~/.config/jarvis/chatterbox-venv --python 3.12
uv pip install --torch-backend cpu \
  --python ~/.config/jarvis/chatterbox-venv/bin/python chatterbox-tts
# Runtime fix 2026-10-03: perth needs pkg_resources (setuptools<81)
uv pip install --python ~/.config/jarvis/chatterbox-venv/bin/python \
  "setuptools<81"
```

JARVIS sees the runtime through a small documented bridge, not a global
install: `ChatterboxTTSProvider` uses `import chatterbox` directly when
possible (`direct` mode), otherwise shells out to
`jarvis/voice/chatterbox_bridge.py` under the interpreter at
`voice.chatterbox_python` (env `JARVIS_CHATTERBOX_PYTHON`, default
`~/.config/jarvis/chatterbox-venv/bin/python`). `voice status` and
`doctor` report the real mode (`direct`/`bridge`/unavailable).

Missing runtime/reference/model fails gracefully with a clear
error — never a silent voice switch, never a cognition crash.
Fallback chain: chatterbox → existing espeak/piper → text-only.

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

## Status / limitations (this host, 2026-10-03)

Chatterbox runtime: AVAILABLE via bridge
(`~/.config/jarvis/chatterbox-venv`, Python 3.12.13, torch 2.6.0+cpu,
Intel iGPU only — CPU inference, no CUDA installed). Reference audio:
OK (`male_old_movie.flac`, verified). Model: weights cached (~6.3GiB
HF hub), loads in ~20s, first synthesis ~83s for 2.7s audio on CPU
(RTF ~30; full CLI turn ~104s wall, ~3 cores, 4.1GiB peak RSS).
Generation verified end-to-end (`voice say` → chatterbox → wav,
non-silent rms 0.085/peak 0.65). Playback: aplay present + hardware
listed, `aplay` invocation NOT TESTED, audible output NOT TESTED.
Microphone: backend present (arecord), content recording NOT TESTED.
Raspberry Pi audio: HARDWARE-PENDING. faster-whisper: installed
but runtime blocked by PyAV `metadata_errors` incompatibility (STT and
TTS tracked independently). No real-time claims. Disk: runtime 1.6GiB
+ models ~6.3GiB (~8GiB total); 19GiB free remain. RAM is the binding
constraint (6GiB total) — one-shot bridge loads the model per call; a
persistent worker (amortized load) is future work, not implemented.
