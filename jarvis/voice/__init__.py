"""JARVIS Voice subsystem (5.1).

Public API:

- VoiceConfig / VoicePipeline / WakeWordDetector / SpeechToText /
  TextToSpeech — voice input/output pipeline (pipeline.py)
- VoiceSession — voice session + correlation tracking (session.py)
- VoiceTurnProcessor — voice turn: wake-word → STT → cognitive loop →
  TTS → memory (turn.py)
- VoiceProfile / jarvis_profile / render_style — voice identity and
  speaking style (voice_profile.py)
- VoiceSpeaker / speak_text / resolve_tts — response → TTS → playback
  (speak.py)
- Transcriber / SpeechRecognitionResult — STT provider abstraction
  (stt.py)
- TTSProvider / TTSRequest / TTSResult / provider_for — TTS abstraction
  (tts.py)
- SecretVault — local encrypted-at-rest secret store (security.py)
"""

from .pipeline import (
    SpeechToText, TextToSpeech, VoiceConfig, VoicePipeline, WakeWordDetector,
)
from .session import VoiceSession
from .turn import VoiceTurnProcessor, VoiceTurnResult, FakeSTT, FakeTTS
from .voice_profile import (
    VoiceProfile, jarvis_profile, render_style, REFERENCE_FILENAME,
    REFERENCE_URL, DEFAULT_REFERENCE, default_reference_path,
    STYLE_GUIDANCE,
)
from .speak import speak_text, VoiceSpeaker, resolve_tts
from .stt import STTProvider, SpeechRecognitionResult, STTStatus, STTError
from .tts import (
    TTSProvider, TTSRequest, TTSResult, provider_for,
    FakeTTSProvider, UnavailableTTSProvider, LocalFallbackTTSProvider,
    ChatterboxTTSProvider,
)
from ..security.security import SecretVault

__all__ = [
    # Pipeline
    "VoiceConfig", "VoicePipeline", "WakeWordDetector",
    "SpeechToText", "TextToSpeech",
    # Session
    "VoiceSession",
    # Turn processor
    "VoiceTurnProcessor", "VoiceTurnResult", "FakeSTT", "FakeTTS",
    # Profile
    "VoiceProfile", "jarvis_profile", "render_style",
    "REFERENCE_FILENAME", "REFERENCE_URL", "DEFAULT_REFERENCE",
    "default_reference_path", "STYLE_GUIDANCE",
    # Speak
    "speak_text", "VoiceSpeaker", "resolve_tts",
    # STT
    "STTProvider", "SpeechRecognitionResult", "STTStatus", "STTError",
    # TTS
    "TTSProvider", "TTSRequest", "TTSResult", "provider_for",
    "FakeTTSProvider", "UnavailableTTSProvider", "LocalFallbackTTSProvider",
    "ChatterboxTTSProvider",
    # Security
    "SecretVault",
]