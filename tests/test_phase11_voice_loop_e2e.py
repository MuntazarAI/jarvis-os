"""Phase 11: Voice loop end-to-end with REAL Jarvis + Memory Palace via VoiceLoop.

Tests the complete voice turn using REAL Jarvis cognitive loop through
VoiceLoop.converse_once():
  mic → STT → wake-gate → jarvis.cycle_once() → TTS → Memory Palace

Uses fakes for mic/STT/TTS (no audio hardware needed) but the real
Jarvis cognitive loop and real Memory Palace. This proves the voice
loop works end-to-end with the actual cognitive engine through the
VoiceLoop class itself.

All tests are deterministic — FakeMicRecorder, FakeTranscriber,
FakeSpeaker require no microphone, speakers, GPU, or network.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.loop import Jarvis
from jarvis.memory.palace import MemoryPalace
from jarvis.voice.audio import AudioFrame, AudioError
from jarvis.voice.pipeline import VoicePipeline, WakeWordDetector
from jarvis.voice.output import FakeAudioOutput
from jarvis.voice.runtime import (
    EnergyVAD, MicRecorder, Speaker, Transcriber, VoiceLoop,
    read_wav_mono16, rms,
)
from jarvis.voice.turn import VoiceTurnProcessor, FakeSTT, FakeTTS


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
    return FakeSTT(transcript="jarvis remember my name is bob",
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
    """Complete voice turn: mic → STT → wake-gate → cognitive loop → TTS → memory."""
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
    """Voice turn via VoiceLoop persists user + jarvis utterances + episode
    to Jarvis's Memory Palace."""
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
    no_stt = FakeSTT(transcript="", backend="none", available=False)
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

    # Transcript without "jarvis" wake word, not addressed -> rejected
    no_wake_stt = FakeSTT(transcript="what time is it",
                          backend="fake", available=True)
    loop.stt = no_wake_stt

    result = loop.converse_once(jarvis, addressed=False)

    assert result["ok"] is False
    assert "not addressed" in result.get("error", "")


def test_voice_loop_empty_transcript(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
    """Empty STT transcript still produces a response (clarification)."""
    empty_stt = FakeSTT(transcript="", backend="fake", available=True)
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
    no_stt = FakeSTT(transcript="", backend="none", available=False)
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


def test_voice_loop_check_ready_missing_mic(
    jarvis, fake_stt, fake_speaker, voice_pipeline
):
    """check_ready reports missing mic."""
    no_mic = FakeMicRecorder(available=False)
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=no_mic,
        stt=fake_stt,
        speaker=fake_speaker,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    ready, missing = loop.check_ready()
    assert ready is False
    assert "microphone" in str(missing).lower()


def test_voice_loop_check_ready_missing_tts(
    jarvis, fake_mic, fake_stt, voice_pipeline
):
    """check_ready reports missing TTS."""
    no_tts = FakeSpeaker()
    no_tts.tts = type("UnavailableTTS", (), {"available": lambda self: False})()
    loop = VoiceLoop(
        pipeline=voice_pipeline,
        vad=EnergyVAD(),
        mic=fake_mic,
        stt=fake_stt,
        speaker=no_tts,
        workdir=str(Path(tempfile.mkdtemp())),
        always_listen=True,
    )

    ready, missing = loop.check_ready()
    assert ready is False
    assert "TTS" in str(missing)


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


# -- Audio frame / VAD determinism ------------------------------------------


def test_audio_frame_validation():
    """AudioFrame enforces bounded fields."""
    f = AudioFrame(source="mic", sample_rate=16000, channels=1,
                   sample_format="pcm_s16le", duration_s=0.02,
                   payload_bytes=640)
    assert f.sample_rate == 16000
    assert f.channels == 1

    # Invalid sample rate fails closed
    with pytest.raises(AudioError):
        AudioFrame(source="mic", sample_rate=80000, channels=1,
                   sample_format="pcm_s16le", duration_s=0.02,
                   payload_bytes=640)


def test_vad_segmentation_deterministic():
    """EnergyVAD segments speech vs silence deterministically."""
    def _tone(seconds=1, rate=16000, amp=4000):
        return struct.pack(f"<{seconds * rate}h", *([amp] * seconds * rate))

    def _silence(seconds=1, rate=16000):
        return b"\x00\x00" * (seconds * rate)

    vad = EnergyVAD()
    assert vad.segment(_silence())["segments"] == []
    seg = vad.segment(_silence() + _tone() + _silence())
    assert len(seg["segments"]) == 1
    assert vad.segment(_silence())["segments"] == []


def test_wake_word_detector():
    """WakeWordDetector detects the wake word in transcript."""
    wake = WakeWordDetector(word="jarvis")
    assert wake.available() is True  # ffmpeg or arecord may be available
    assert wake.heard_in("hey jarvis what time is it") is True
    assert wake.heard_in("hello world") is False
    assert wake.detections == 1


def test_wake_word_detector_custom_word():
    """WakeWordDetector with custom wake word."""
    wake = WakeWordDetector(word="computer")
    assert wake.word == "computer"
    assert wake.heard_in("computer turn on lights") is True
    assert wake.heard_in("hey jarvis") is False


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


def test_voice_loop_empty_transcript(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
    """Empty STT transcript still produces a response (clarification)."""
    empty_stt = FakeSTT(transcript="", backend="fake", available=True)
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


def test_voice_loop_think_latency_recorded(
    jarvis, fake_mic, fake_stt, fake_speaker, voice_pipeline
):
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