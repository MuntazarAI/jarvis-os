# Voice & Audio Intelligence 5.1

## 5.2 — persistent Turbo runtime (this section)

The one-shot bridge (spawn Python → load model → synthesize → exit)
reloaded ~3GB of weights per sentence. 5.2 adds a persistent worker:

```
JARVIS → TTSProvider → PersistentTTSClient (single owner)
  → stdio JSONL, protocol v1 (no sockets, no network, no shell)
  → tts_worker.py (Python 3.12 venv): Turbo loaded ONCE
  → wav artifact in client-owned dir → existing AudioOutput
```

Why stdio JSONL: simplest portable Linux/Pi mechanism; no stale
sockets, no network surface, debuggable lines, stdlib only. The device
socket transport was evaluated and rejected (wrong tool: network
protocol for a local pipe).

### Lifecycle and ownership

States: STARTING → LOADING → READY → BUSY → READY; FAILED;
READY → SHUTDOWN_REQUESTED → SHUTDOWN. Illegal transitions rejected.
One worker, one model, one active synthesis; BUSY rejects with
structured backpressure (no queue). Timeouts (monotonic): startup 120s,
ready 1800s, request 900s, health 10s, shutdown 15s. Restarts: max 2
with 5s/15s backoff, then fallback. Every response correlates by
request id AND worker generation; timeouts abandon, taint, restart.

Fallback chain: persistent → one-shot bridge → local espeak/piper →
text-only. The reported `mode` always names the actual producer
(`persistent`/`bridge`/`direct`/`local-fallback`/`fake`).

### Security and privacy

Worker authority: synthesize validated text, nothing else. No shell,
no eval/exec, no imports by request, no arbitrary paths (writes only
`<workdir>/req-<id>.wav`, id charset-enforced), no env modification,
no network. Child env = parent env + repo PYTHONPATH only. Telemetry
is metadata-only (lengths, latencies, counts). Temp audio is transient
by default. Cancellation = abandon + restart (model-level interruption
is unsafe; documented limitation).

### Configuration (`JarvisConfig.voice`)

`persistent: true` (master switch), plus LIMITS in
`jarvis/voice/persistent.py` (text/audio caps, all timeouts, restart
limit, optional `max_worker_rss_mb` defaulting to observe-only).
`voice worker [--op status|start|stop]`, `voice:worker` doctor check
with stray-worker (orphan) detection. First-sentence cost remains
(~20s load); steady state amortizes it. A persistent daemon across CLI
invocations was deliberately NOT built (stale-endpoint/orphan risk);
workers live with their owner process (serve/repl/listen benefit,
one-shot CLI measures cold start honestly then shuts down).

### Measured (this host, CPU-only, Turbo)

time-to-ready ~20–40s (one load); warm syntheses ~12–17s for ~2.3s
audio (RTF ~5–7) vs one-shot ~22–52s; 10/10 requests ok, RSS
2.7→3.0GB oscillating, no leak; offline synthesis PASS. See the 5.2
final report for the full benchmark table.

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
