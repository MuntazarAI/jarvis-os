"""Voice pipeline: wake word, STT, TTS behind swappable backends."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VoiceConfig:
    wake_word: str = "jarvis"
    stt_backend: str = "auto"  # auto | whisper | vosk | none
    tts_backend: str = "auto"  # auto | piper | espeak | none
    voice: str = "en-gb"
    rate: int = 145


class WakeWordDetector:
    """Low-power wake-word gate. Without audio hardware it stays dormant."""

    def __init__(self, word: str = "jarvis") -> None:
        self.word = word.lower()
        self.detections = 0

    def available(self) -> bool:
        return shutil.which("arecord") is not None or shutil.which("ffmpeg") is not None

    def heard_in(self, transcript: str) -> bool:
        """Text-mode gate used by the CLI and tests."""
        if self.word in transcript.lower():
            self.detections += 1
            return True
        return False

    def status(self) -> dict[str, Any]:
        return {"word": self.word, "detections": self.detections,
                "audio_available": self.available()}


class SpeechToText:
    def __init__(self, backend: str = "auto") -> None:
        self.backend = self._resolve(backend)

    @staticmethod
    def _resolve(backend: str) -> str:
        if backend != "auto":
            return backend
        if shutil.which("whisper") or shutil.which("whisper.cpp"):
            return "whisper"
        return "none"

    def available(self) -> bool:
        return self.backend != "none"

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "no STT backend installed",
                    "hint": "install whisper or place text via the CLI"}
        try:
            proc = subprocess.run(
                ["whisper", audio_path, "--output_format", "txt",
                 "--output_dir", "/tmp"],
                capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                return {"ok": False, "error": proc.stderr[-500:]}
            return {"ok": True, "text": proc.stdout.strip(), "backend": self.backend}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class TextToSpeech:
    def __init__(self, backend: str = "auto", voice: str = "en-gb", rate: int = 145) -> None:
        self.voice = voice
        self.rate = rate
        self.backend = self._resolve(backend)
        self.spoken: list[str] = []

    @staticmethod
    def _resolve(backend: str) -> str:
        if backend != "auto":
            return backend
        if shutil.which("piper"):
            return "piper"
        if shutil.which("espeak") or shutil.which("espeak-ng"):
            return "espeak"
        return "none"

    def available(self) -> bool:
        return self.backend != "none"

    def speak(self, text: str, blocking: bool = True) -> dict[str, Any]:
        self.spoken.append(text)
        if not self.available():
            return {"ok": False, "error": "no TTS backend installed",
                    "queued": text[:120]}
        try:
            binary = "piper" if self.backend == "piper" else shutil.which("espeak-ng") or "espeak"
            proc = subprocess.run([binary, text[:800]], capture_output=True,
                                  text=True, timeout=60)
            return {"ok": proc.returncode == 0, "backend": self.backend}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@dataclass
class VoicePipeline:
    config: VoiceConfig = field(default_factory=VoiceConfig)
    wake: WakeWordDetector = field(default_factory=WakeWordDetector)
    stt: SpeechToText = field(default_factory=SpeechToText)
    tts: TextToSpeech = field(default_factory=TextToSpeech)

    def __post_init__(self) -> None:
        self.wake = WakeWordDetector(self.config.wake_word)
        self.stt = SpeechToText(self.config.stt_backend)
        self.tts = TextToSpeech(self.config.tts_backend, self.config.voice,
                                self.config.rate)

    def handle(self, transcript: str, addressed: bool = False) -> dict[str, Any]:
        """Decide whether speech is for JARVIS and what to do with it."""
        is_wake = self.wake.heard_in(transcript)
        if not (is_wake or addressed):
            return {"for_jarvis": False, "reason": "no wake word"}
        cleaned = transcript.lower().replace(self.config.wake_word, "").strip(" ,.!?")
        return {"for_jarvis": True, "text": cleaned or transcript,
                "wake": is_wake}

    def respond(self, text: str) -> dict[str, Any]:
        return self.tts.speak(text)

    def status(self) -> dict[str, Any]:
        return {"wake": self.wake.status(),
                "stt": self.stt.backend, "tts": self.tts.backend,
                "spoken": len(self.tts.spoken)}
