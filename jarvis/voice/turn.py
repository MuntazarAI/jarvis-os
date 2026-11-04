"""Voice turn processor — connects voice input → cognitive loop → TTS → memory.

One voice turn: wake-word gate → STT → Jarvis cognitive loop → TTS →
Memory Palace persistence. All components are injectable for testing;
audio hardware is optional (graceful degradation when missing).

Never executes tools/devices/memory directly — those flow through the
Jarvis cognitive loop's PolicyEngine. TTS never bypasses PolicyEngine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import Modality, Observation
from ..memory.palace import MemoryPalace
from .pipeline import SpeechToText, TextToSpeech, VoiceConfig, VoicePipeline, WakeWordDetector
from .session import VoiceSession
from .speak import speak_text

log = get_module_logger(__name__)


@dataclass
class VoiceTurnResult:
    """Result of one complete voice turn."""
    ok: bool
    handled: bool
    reason: str = ""
    transcript: str = ""
    raw_transcript: str = ""
    response: str = ""
    intent: str = ""
    confidence: float = 0.0
    duration: float = 0.0
    turn_id: str = ""
    session_id: str = ""
    audio_id: str = ""
    transcript_id: str = ""
    cognition_id: str = ""
    response_id: str = ""
    tts_id: str = ""
    stt_backend: str = ""
    tts_backend: str = ""
    wake_detected: bool = False
    addressed: bool = False
    memory_stored: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "handled": self.handled,
            "reason": self.reason,
            "transcript": self.transcript,
            "raw_transcript": self.raw_transcript,
            "response": self.response,
            "intent": self.intent,
            "confidence": self.confidence,
            "duration": self.duration,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "audio_id": self.audio_id,
            "transcript_id": self.transcript_id,
            "cognition_id": self.cognition_id,
            "response_id": self.response_id,
            "tts_id": self.tts_id,
            "stt_backend": self.stt_backend,
            "tts_backend": self.tts_backend,
            "wake_detected": self.wake_detected,
            "addressed": self.addressed,
            "memory_stored": self.memory_stored,
            "error": self.error,
        }


class FakeSTT:
    """Deterministic fake STT for tests. Returns a fixed transcript."""

    def __init__(self, transcript: str = "", backend: str = "fake",
                 available: bool = True) -> None:
        self.transcript = transcript
        self.backend = backend
        self.available_flag = available
        self.calls = 0

    def available(self) -> bool:
        return self.available_flag

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        self.calls += 1
        return {
            "ok": self.available_flag,
            "text": self.transcript,
            "backend": self.backend,
        }


class FakeTTS:
    """Deterministic fake TTS for tests. Records spoken text."""

    def __init__(self, voice: str = "jarvis", rate: int = 145) -> None:
        self.voice = voice
        self.rate = rate
        self.backend = "fake"
        self.spoken: list[str] = []
        self.calls = 0

    def available(self) -> bool:
        return True

    def speak(self, text: str, blocking: bool = True) -> dict[str, Any]:
        self.calls += 1
        self.spoken.append(text)
        return {"ok": True, "provider": "fake", "text": text[:200]}


class VoiceTurnProcessor:
    """Processes one voice turn end-to-end.

    Flow:
      1. Wake-word gate (VoicePipeline.handle)
      2. STT (if raw audio) or use provided transcript
      3. Jarvis cognitive loop (jarvis.cycle_once)
      4. TTS (VoicePipeline.respond or speak_text)
      5. Memory Palace persistence (user + jarvis utterances + episode)
    """

    def __init__(self, jarvis: Any,
                 pipeline: VoicePipeline | None = None,
                 palace: MemoryPalace | None = None,
                 output: Any = None,
                 stt: Any = None,
                 tts: Any = None,
                 auto_memory: bool = True) -> None:
        self.jarvis = jarvis
        self.pipeline = pipeline or VoicePipeline()
        self.palace = palace
        self.output = output
        self.stt = stt
        self.tts = tts
        self.auto_memory = auto_memory
        self.session = VoiceSession()
        self.turns: list[VoiceTurnResult] = []

    # -- single turn ------------------------------------------------------

    def process_transcript(self, transcript: str,
                           addressed: bool = False) -> VoiceTurnResult:
        """Process a text transcript through the full voice turn.

        Applies the wake-word gate, runs the cognitive loop, speaks the
        response, and persists to memory.
        """
        started = time.time()
        turn_id = f"turn-{int(started * 1000)}"

        # 1. Wake-word gate
        handled = self.pipeline.handle(transcript, addressed=addressed)
        if not handled["for_jarvis"]:
            result = VoiceTurnResult(
                ok=True, handled=False, reason=handled["reason"],
                transcript=transcript, raw_transcript=transcript,
                turn_id=turn_id,
                session_id=self.session.session_id,
                wake_detected=handled.get("wake", False),
                addressed=addressed,
                duration=time.time() - started,
            )
            self.turns.append(result)
            return result

        # Advance session turn tracking
        self.session.next_turn(
            audio_id=f"audio-{int(started * 1000)}",
            transcript_id=f"stt-{int(started * 1000)}",
        )

        # 2. Cognitive loop
        cycle = self.jarvis.cycle_once(
            handled["text"], source="voice",
            session_id=self.session.session_id)

        # 3. TTS
        tts_result = self._speak(cycle.response)

        # 4. Memory persistence
        memory_stored = False
        if self.auto_memory and self.palace is not None:
            try:
                self.palace.store_conversation(
                    "user", transcript, session_id=self.session.session_id,
                    room="Home")
                self.palace.store_conversation(
                    "jarvis", cycle.response,
                    session_id=self.session.session_id, room="Home")
                self.palace.store_episode(
                    f"voice turn: {transcript[:80]} → {cycle.response[:80]}",
                    room="Home", importance=0.5,
                    metadata={"turn_id": turn_id,
                              "session_id": self.session.session_id,
                              "intent": cycle.intent,
                              "confidence": cycle.confidence.numeric})
                memory_stored = True
            except Exception as exc:  # noqa: BLE001
                log.warning("voice memory persistence failed",
                            error=str(exc))

        result = VoiceTurnResult(
            ok=True, handled=True, reason="",
            transcript=handled["text"], raw_transcript=transcript,
            response=cycle.response,
            intent=cycle.intent,
            confidence=cycle.confidence.numeric,
            duration=time.time() - started,
            turn_id=turn_id, session_id=self.session.session_id,
            stt_backend=self.pipeline.stt.backend,
            tts_backend=self.pipeline.tts.backend,
            wake_detected=handled.get("wake", False),
            addressed=addressed,
            memory_stored=memory_stored,
        )
        self.turns.append(result)
        return result

    def process_audio(self, audio_path: str,
                      addressed: bool = False) -> VoiceTurnResult:
        """Process raw audio: STT → full voice turn."""
        started = time.time()
        turn_id = f"turn-{int(started * 1000)}"

        # 1. STT
        stt_backend = "none"
        transcript = ""
        if self.stt is not None and self.stt.available():
            stt_result = self.stt.transcribe(audio_path)
            stt_backend = stt_result.get("backend", "none")
            if stt_result.get("ok"):
                transcript = stt_result.get("text", "")
            else:
                result = VoiceTurnResult(
                    ok=False, handled=False,
                    reason=f"stt failed: {stt_result.get('error', 'unknown')}",
                    turn_id=turn_id,
                    session_id=self.session.session_id,
                    stt_backend=stt_backend,
                    duration=time.time() - started,
                    error=stt_result.get("error", "unknown"),
                )
                self.turns.append(result)
                return result
        else:
            # No STT available — cannot process audio
            result = VoiceTurnResult(
                ok=False, handled=False,
                reason="no STT backend available for audio input",
                turn_id=turn_id,
                session_id=self.session.session_id,
                stt_backend="none",
                duration=time.time() - started,
                error="no STT backend",
            )
            self.turns.append(result)
            return result

        # 2. Wake-word gate + cognitive loop + TTS + memory
        result = self.process_transcript(transcript, addressed=addressed)
        result.stt_backend = stt_backend
        result.audio_id = f"audio-{int(started * 1000)}"
        return result

    def _speak(self, text: str) -> dict[str, Any]:
        """Speak text via the pipeline's TTS or the injected output."""
        if self.tts is not None:
            self.tts.calls += 1
            self.tts.spoken.append(text)
            return {"ok": True, "provider": self.tts.backend,
                    "text": text[:200]}
        if self.pipeline.tts.available():
            return self.pipeline.respond(text)
        # Fallback to speak_text with fake output
        return speak_text(text, config=self.jarvis.config.voice.__dict__,
                          output=self.output, play=False)

    # -- status -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return processor and pipeline status."""
        return {
            "turns": len(self.turns),
            "session_id": self.session.session_id,
            "pipeline": self.pipeline.status(),
            "memory": self.palace.stats() if self.palace else None,
            "last_turn": self.turns[-1].to_dict() if self.turns else None,
        }

    def last_turn(self) -> VoiceTurnResult | None:
        return self.turns[-1] if self.turns else None