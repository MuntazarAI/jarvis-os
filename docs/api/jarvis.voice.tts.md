# `jarvis.voice.tts`

## Members

### `ChatterboxTTSProvider` (class)

Local-first Chatterbox TTS (JARVIS voice). Lazy, honest, bounded.

### `FakeTTSProvider` (class)

Deterministic fake: predictable duration, synthetic wav bytes.

### `LocalFallbackTTSProvider` (class)

Preserve the existing espeak/piper path as fallback #2.

### `TTSProvider` (class)

_No docstring._

### `TTSRequest` (class)

TTSRequest(text: 'str', voice_profile: 'str' = 'jarvis', language: 'str' = 'en', reference_audio: 'str' = '', output_format: 'str' = 'wav', sample_rate: 'int' = 24000, exaggeration: 'float' = 0.5, temperature: 'float' = 0.8, cfg_weight: 'float' = 0.5, correlation_id: 'str' = '', request_id: 'str' = <factory>)

### `TTSResult` (class)

TTSResult(request_id: 'str' = '', provider: 'str' = '', status: 'str' = 'unknown', audio_path: 'str' = '', audio_bytes: 'int' = 0, duration_s: 'float' = 0.0, sample_rate: 'int' = 24000, latency_ms: 'float' = 0.0, error: 'str' = '', metadata: 'dict[str, Any]' = <factory>)

### `UnavailableTTSProvider` (class)

_No docstring._

### `provider_for` (function)

Resolve a provider by name with graceful fallback to unavailable.
