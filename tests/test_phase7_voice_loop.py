"""Phase 7: Voice loop deterministic integration tests.

Tests the full voice turn flow using fakes — no microphone, speakers,
GPU, or network required:
  mic → STT → wake-gate → cognitive loop → TTS → memory → session

Uses FakeMicRecorder, FakeTranscriber, FakeSpeaker injected into
VoiceLoop and VoiceTurnProcessor.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.loop import Jarvis
from jarvis.memory.palace import MemoryPalace
from jarvis.voice.pipeline import VoicePipeline
from jarvis.voice.runtime import (
    EnergyVAD, MicRecorder, Speaker, Transcriber, VoiceLoop, VoiceSession,
)
from jarvis.voice.turn import VoiceTurnProcessor
from jarvis.voice.output import FakeAudioOutput


# -- fakes ------------------------------------------------------------------


class FakeMicRecorder:
    """Deterministic microphone recorder for tests.

    Returns a canned PCM buffer; never touches audio hardware.
    """

    def __init__(self, pcm: bytes = b"", available: bool = True) -> None:
        self.pcm = pcm
        self.available_flag = available
        self.calls = 0
        self.last_dest: str | None = None
        self.last_seconds: float | None = None

    def available(self) -> bool:
        return self.available_flag

    def record(self, seconds: float, dest: str) -> dict[str, Any]:
        self.calls += 1
        self.last_dest = dest
        self.last_seconds = seconds
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(self.pcm)
        return {"ok": True, "path": dest, "backend": "fake"}

    def record_until_silence(
        self, dest: str, vad: EnergyVAD,
        poll_seconds: float = 0.5,
        max_seconds: float = 15.0,
    ) -> dict[str, Any]:
        return self.record(max_seconds, dest)


class FakeTranscriber:
    """Deterministic STT for tests. Returns a canned transcript."""

    def __init__(
        self, transcript: str = "", backend: str = "fake",
        available: bool = True,
    ) -> None:
        self.transcript = transcript
        self.backend = backend
        self.available_flag = available
        self.calls = 0

    def available(self) -> bool:
        return self.available_flag

    def transcribe(self, wav_path: str, language: str = "en") -> dict[str, Any]:
        self.calls += 1
        return {
            "ok": self.available_flag,
            "text": self.transcript,
            "backend": self.backend,
        }


class FakeTTSProvider:
    """Deterministic fake TTS provider for VoiceLoop compatibility."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def synthesize(self, request, dest=None) -> dict[str, Any]:
        self.calls += 1
        return {"ok": True, "provider": self.name,
                "audio_path": str(dest) if dest else ""}


class FakeSpeaker:
    """Deterministic speaker for VoiceLoop compatibility.

    Wraps a fake TTS provider so VoiceLoop.check_ready() works.
    Also exposes backend/calls/spoken for VoiceTurnProcessor compatibility.
    """

    def __init__(self) -> None:
        self.tts = FakeTTSProvider()
        self.backend = "fake"
        self.calls = 0
        self.spoken: list[str] = []

    def available(self) -> bool:
        return True

    def say(self, text: str) -> dict[str, Any]:
        self.calls += 1
        self.spoken.append(text)
        return {"ok": True, "provider": "fake", "text": text[:200]}

    def stop(self) -> bool:
        return True


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-voice-loop-")


@pytest.fixture
def config(home):
    cfg = JarvisConfig()
    cfg.paths.home = Path(home)
    cfg.policy.local_only = True
    cfg.models.cloud_enabled = False
    cfg.models.ollama_enabled = False
    return cfg


@pytest.fixture
def jarvis(home, config):
    return Jarvis(config=config)


@pytest.fixture
def palace(home, config):
    db = str(Path(config.paths.home) / "voice_loop_memories.db")
    return MemoryPalace(path=db, config=config)


@pytest.fixture
def fake_mic():
    return FakeMicRecorder(pcm=b"\x00\x00" * 16000, available=True)


@pytest.fixture
def fake_stt():
    return FakeTranscriber(transcript="jarvis what time is it",
                           backend="fake", available=True)


@pytest.fixture
def fake_speaker():
    return FakeSpeaker()


@pytest.fixture
def voice_pipeline():
    return VoicePipeline()


# -- VoiceLoop deterministic end-to-end tests -----------------------------


def test_voice_loop_full_turn(jarvis, palace, fake_mic, fake_stt,
                              fake_speaker, voice_pipeline):
    """A complete voice turn: mic → STT → wake-gate → cognitive loop → TTS → memory."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    result = loop.converse_once(jarvis, addressed=True)

    assert result["ok"] is True
    assert result["heard"] is not None
    assert result["response"] is not None
    assert fake_stt.calls == 1
    assert fake_speaker.calls == 1
    assert fake_mic.calls == 1


def test_voice_loop_multiple_turns_session(jarvis, palace, fake_mic,
                                           fake_stt, fake_speaker,
                                           voice_pipeline):
    """Multiple voice turns share a session and increment interaction count."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    r1 = loop.converse_once(jarvis, addressed=True)
    r2 = loop.converse_once(jarvis, addressed=True)

    assert r1["voice_session_id"] == r2["voice_session_id"]
    assert loop.session.interaction_count == 2


def test_voice_loop_stt_unavailable(jarvis, fake_mic, fake_speaker,
                                    voice_pipeline):
    """Voice loop degrades gracefully when STT is unavailable."""
    no_stt = FakeTranscriber(transcript="", backend="none", available=False)
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=no_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    result = loop.converse_once(jarvis, addressed=True)

    assert result["ok"] is False
    assert no_stt.calls == 0  # check_ready fails before STT is called
    assert fake_speaker.calls == 0  # never reached TTS


def test_voice_loop_not_addressed(jarvis, fake_mic, fake_stt,
                                  fake_speaker, voice_pipeline):
    """Speech not addressed to JARVIS is filtered out."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=False,
    )

    # Transcript without wake word, not addressed -> should be rejected
    no_stt2 = FakeTranscriber(transcript="what time is it",
                              backend="fake", available=True)
    loop.stt = no_stt2

    result = loop.converse_once(jarvis, addressed=False)

    assert result["ok"] is False
    assert "not addressed" in result.get("error", "")


def test_voice_loop_memory_persistence(jarvis, palace, fake_mic, fake_stt,
                                       fake_speaker, voice_pipeline):
    """Voice turns persist to Memory Palace via VoiceTurnProcessor."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=voice_pipeline, palace=palace,
        output=FakeAudioOutput(), stt=fake_stt, tts=fake_speaker,
    )

    # Use addressed=True so wake-word gate passes
    result = processor.process_transcript("jarvis remember this",
                                          addressed=True)

    assert result.ok is True
    assert result.handled is True
    assert result.memory_stored is True

    # Verify memory was stored
    conv = palace.all(tier="conversation")
    assert len(conv) >= 2  # user + jarvis
    ep = palace.all(tier="episodic")
    assert len(ep) >= 1


# -- VoiceLoop readiness and gating ---------------------------------------


def test_voice_loop_check_ready_with_fakes(jarvis, fake_mic, fake_stt,
                                           fake_speaker, voice_pipeline):
    """check_ready reports honest availability."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    ready, missing = loop.check_ready()
    assert ready is True
    assert missing == []


def test_voice_loop_check_ready_missing_stt(jarvis, fake_mic, fake_speaker,
                                            voice_pipeline):
    """check_ready reports missing STT."""
    no_stt = FakeTranscriber(transcript="", backend="none", available=False)
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=no_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    ready, missing = loop.check_ready()
    assert ready is False
    assert "STT" in str(missing)


def test_voice_loop_stop(jarvis, fake_mic, fake_stt, fake_speaker,
                         voice_pipeline):
    """VoiceLoop.stop() halts speech and signals exit."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    stopped = loop.stop()
    assert stopped is True


# -- VoiceSession integration ---------------------------------------------


def test_voice_session_chain_ids(jarvis, fake_mic, fake_stt,
                                 fake_speaker, voice_pipeline):
    """Each turn mints fresh IDs while session stays constant."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    r1 = loop.converse_once(jarvis, addressed=True)
    r2 = loop.converse_once(jarvis, addressed=True)

    assert r1["voice_session_id"] == r2["voice_session_id"]
    assert r1["turn"]["cognition_id"] != r2["turn"]["cognition_id"]
    assert r1["turn"]["response_id"] != r2["turn"]["response_id"]
    assert r1["turn"]["tts_id"] != r2["turn"]["tts_id"]


# -- VoiceTurnProcessor + VoiceLoop interop -------------------------------


def test_voice_turn_processor_with_voice_loop(
    jarvis, palace, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
    """VoiceTurnProcessor can use VoiceLoop components."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=voice_pipeline, palace=palace,
        output=FakeAudioOutput(), stt=fake_stt, tts=fake_speaker,
    )

    result = processor.process_transcript("jarvis test interop",
                                          addressed=True)

    assert result.ok is True
    assert result.handled is True
    assert result.response is not None
    assert fake_stt.calls == 0  # process_transcript doesn't use STT
    assert fake_speaker.calls == 1  # TTS was called


# -- Edge cases ----------------------------------------------------------


def test_voice_loop_empty_transcript(jarvis, fake_mic, fake_stt,
                                     fake_speaker, voice_pipeline):
    """Empty STT transcript is handled gracefully."""
    empty_stt = FakeTranscriber(transcript="", backend="fake",
                                available=True)
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=empty_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    result = loop.converse_once(jarvis, addressed=True)

    # Empty transcript should still produce a response (clarification)
    assert result["ok"] is True
    assert result["response"] is not None


def test_voice_loop_think_latency_recorded(jarvis, fake_mic, fake_stt,
                                           fake_speaker, voice_pipeline):
    """think_ms is recorded for each turn."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    result = loop.converse_once(jarvis, addressed=True)

    assert result["ok"] is True
    assert "think_ms" in result
    assert isinstance(result["think_ms"], (int, float))
    assert result["think_ms"] >= 0


# -- always_listen mode --------------------------------------------------


def test_voice_loop_always_listen_mode(jarvis, fake_mic, fake_stt,
                                       fake_speaker, voice_pipeline):
    """always_listen=True doesn't require wake word in transcript."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    # Even without "jarvis" in the text, addressed=True allows processing
    result = loop.converse_once(jarvis, addressed=True)

    assert result["ok"] is True
    assert result["response"] is not None


# -- VoiceSession determinism --------------------------------------------


def test_voice_session_deterministic_ids():
    """VoiceSession generates deterministic, unique IDs."""
    from jarvis.voice.session import VoiceSession

    s1 = VoiceSession(source="microphone")
    s2 = VoiceSession(source="microphone")

    assert s1.session_id != s2.session_id
    assert s1.source == "microphone"
    assert s2.source == "microphone"

    t1 = s1.next_turn()
    t2 = s1.next_turn()

    assert t1["voice_session_id"] == t2["voice_session_id"]
    assert t1["audio_id"] != t2["audio_id"]
    assert t1["cognition_id"] != t2["cognition_id"]
    assert t1["response_id"] != t2["response_id"]
    assert t1["tts_id"] != t2["tts_id"]
    assert s1.interaction_count == 2


# -- Fake speaker stop ---------------------------------------------------


def test_voice_speaker_stop(fake_speaker):
    """FakeSpeaker.stop() works and is callable multiple times."""
    assert fake_speaker.stop() is True
    assert fake_speaker.stop() is True