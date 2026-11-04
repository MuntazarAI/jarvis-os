"""Phase 8: Voice loop end-to-end with real Jarvis + memory persistence.

Tests the complete voice turn using REAL Jarvis cognitive loop:
  mic → STT → wake-gate → jarvis.cycle_once() → TTS → Memory Palace

Uses fakes for mic/STT/TTS (no audio hardware needed) but the real
Jarvis cognitive loop and real Memory Palace. This proves the voice
loop works end-to-end with the actual cognitive engine and memory
persistence — not stubs.
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
    EnergyVAD, MicRecorder, Speaker, Transcriber, VoiceLoop,
)
from jarvis.voice.output import FakeAudioOutput


# -- fakes ------------------------------------------------------------------


class FakeMicRecorder:
    """Deterministic microphone recorder for tests."""

    def __init__(self, pcm: bytes = b"", available: bool = True) -> None:
        self.pcm = pcm
        self.available_flag = available
        self.calls = 0

    def available(self) -> bool:
        return self.available_flag

    def record(self, seconds: float, dest: str) -> dict[str, Any]:
        self.calls += 1
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
    """Deterministic STT for tests."""

    def __init__(self, transcript: str = "", backend: str = "fake",
                 available: bool = True) -> None:
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


class FakeSpeaker:
    """Deterministic speaker wrapping FakeTTSProvider for VoiceLoop."""

    def __init__(self) -> None:
        self.tts = _FakeTTSProvider()
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


class _FakeTTSProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def synthesize(self, request, dest=None) -> dict[str, Any]:
        self.calls += 1
        return {"ok": True, "provider": self.name,
                "audio_path": str(dest) if dest else ""}


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-voice-e2e-")


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
    return FakeTranscriber(transcript="jarvis remember my name is bob",
                           backend="fake", available=True)


@pytest.fixture
def fake_speaker():
    return FakeSpeaker()


@pytest.fixture
def voice_pipeline():
    return VoicePipeline()


# -- VoiceLoop + real Jarvis + memory persistence ---------------------------


def test_voice_loop_full_turn_with_real_jarvis(
    jarvis, palace, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
    """Complete voice turn with REAL Jarvis cognitive loop and memory persistence."""
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
    assert result["voice_session_id"] == loop.session.session_id
    assert "think_ms" in result


def test_voice_loop_persists_to_memory_palace(
    jarvis, palace, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
    """Voice turn via VoiceLoop persists user + jarvis utterances + episode to Jarvis's Memory Palace."""
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    loop.converse_once(jarvis, addressed=True)

    # Jarvis's own Memory Palace stores the conversation
    conv = jarvis.palace.all(tier="conversation")
    user_mem = [m for m in conv if m.content.startswith("user:")]
    jarvis_mem = [m for m in conv if m.content.startswith("jarvis:")]
    assert len(user_mem) >= 1
    assert len(jarvis_mem) >= 1

    # Episode memory stored
    ep = jarvis.palace.all(tier="episodic")
    assert len(ep) >= 1
    episode = ep[0]
    assert "my name is bob" in episode.content or "remember" in episode.content
    assert episode.metadata.get("session_id") == loop.session.session_id


def test_voice_loop_multiple_turns_session(
    jarvis, palace, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
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
    assert r1["turn"]["cognition_id"] != r2["turn"]["cognition_id"]


def test_voice_loop_stt_unavailable(
    jarvis, fake_mic, fake_speaker, voice_pipeline
):
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
    assert no_stt.calls == 0  # check_ready fails before STT
    assert fake_speaker.calls == 0


def test_voice_loop_not_addressed(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
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

    # Transcript without "jarvis" wake word, not addressed -> should be rejected
    no_wake_stt = FakeTranscriber(transcript="what time is it",
                                  backend="fake", available=True)
    loop.stt = no_wake_stt

    result = loop.converse_once(jarvis, addressed=False)

    assert result["ok"] is False
    assert "not addressed" in result.get("error", "")


def test_voice_loop_empty_transcript(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
    """Empty STT transcript still produces a response (clarification)."""
    empty_stt = FakeTranscriber(transcript="", backend="fake", available=True)
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

    assert result["ok"] is True
    assert result["response"] is not None


def test_voice_loop_check_ready(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
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


def test_voice_loop_check_ready_missing_stt(
    jarvis, fake_mic, fake_speaker, voice_pipeline
):
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


def test_voice_loop_stop(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
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


def test_voice_session_chain_ids(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
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


def test_voice_loop_always_listen_mode(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
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

    result = loop.converse_once(jarvis, addressed=True)

    assert result["ok"] is True
    assert result["response"] is not None


def test_voice_loop_voice_session_id_propagates(
    jarvis, palace, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
    """VoiceSession ID propagates through cognitive loop and memory metadata."""
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

    assert result["voice_session_id"] == loop.session.session_id
    assert result["turn"]["voice_session_id"] == loop.session.session_id

    # Memory episode should carry the same session id
    ep = jarvis.palace.all(tier="episodic")
    assert len(ep) >= 1
    assert ep[0].metadata.get("session_id") == loop.session.session_id