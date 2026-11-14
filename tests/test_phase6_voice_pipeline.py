"""Phase 6 integration tests: Voice Pipeline Completion.

Tests the full voice turn flow:
  Wake-word gate → STT → Jarvis cognitive loop → TTS → Memory Palace

All tests are deterministic — FakeVAD, FakeSTT, FakeTTS, FakeAudioOutput
require no microphone, speakers, GPU, or network. Voice turns are
provisioned through Memory Palace persistence.

Test categories:
- Safe actions execute without approval
- Actions requiring approval create tokens and pause tasks
- check_approval reflects PolicyEngine state
- resume_task completes after approval, fails after denial
- pending_approvals lists waiting tasks
- Multiple sequential approvals in one task
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.loop import Jarvis
from jarvis.memory.palace import MemoryPalace
from jarvis.voice import (
    VoiceConfig, VoicePipeline, WakeWordDetector, SpeechToText,
    TextToSpeech, VoiceSession, VoiceTurnProcessor, VoiceTurnResult,
    FakeSTT, FakeTTS,
)
from jarvis.voice.output import FakeAudioOutput
from jarvis.voice.speak import speak_text


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-voice-")


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
    db = str(Path(config.paths.home) / "voice_memories.db")
    return MemoryPalace(path=db, config=config)


@pytest.fixture
def pipeline():
    return VoicePipeline(
        config=VoiceConfig(wake_word="jarvis", stt_backend="fake",
                           tts_backend="fake"))


@pytest.fixture
def stt():
    return FakeSTT(transcript="", backend="fake", available=True)


@pytest.fixture
def tts():
    return FakeTTS(voice="jarvis", rate=145)


@pytest.fixture
def output():
    return FakeAudioOutput()


# -- VoiceTurnProcessor: transcript flow ----------------------------------


def test_voice_turn_full_flow(jarvis, palace, pipeline, stt, tts, output):
    """A complete voice turn: wake word → STT → cognitive loop → TTS → memory."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts)

    # Use addressed=True so the wake-word gate passes without "jarvis" word
    result = processor.process_transcript("hello jarvis", addressed=True)

    assert result.ok is True
    assert result.handled is True
    assert result.transcript == "hello"
    assert result.raw_transcript == "hello jarvis"
    assert result.response is not None
    assert result.duration > 0
    assert result.session_id == processor.session.session_id
    assert result.wake_detected is True
    assert result.addressed is True

    # TTS was called
    assert tts.calls >= 1
    assert result.response in tts.spoken

    # Memory was stored
    assert result.memory_stored is True
    memories = palace.all(tier="conversation")
    user_memories = [m for m in memories if "user:" in m.content]
    jarvis_memories = [m for m in memories if "jarvis:" in m.content]
    assert len(user_memories) >= 1
    assert len(jarvis_memories) >= 1


def test_voice_turn_wake_word_gate(jarvis, palace, pipeline, stt, tts, output):
    """Speech without wake word and not addressed is ignored."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts)

    result = processor.process_transcript("some random speech", addressed=False)

    assert result.ok is True
    assert result.handled is False
    assert result.reason == "no wake word"
    assert result.transcript == "some random speech"
    assert result.response == ""
    assert tts.calls == 0  # No TTS call for ignored speech


def test_voice_turn_addressed_without_wake_word(jarvis, palace, pipeline, stt, tts, output):
    """Addressed speech bypasses the wake-word requirement."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts)

    result = processor.process_transcript("what time is it", addressed=True)

    assert result.ok is True
    assert result.handled is True
    assert result.transcript == "what time is it"
    assert result.response is not None
    assert result.wake_detected is False  # No "jarvis" in text
    assert result.addressed is True


def test_voice_turn_multiple_turns_session(jarvis, palace, pipeline, stt, tts, output):
    """Multiple voice turns share a session and increment interaction count."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts)

    r1 = processor.process_transcript("jarvis first turn", addressed=True)
    r2 = processor.process_transcript("jarvis second turn", addressed=True)

    assert r1.session_id == r2.session_id
    assert processor.session.interaction_count == 2
    assert len(processor.turns) == 2


# -- VoiceTurnProcessor: audio flow --------------------------------------


def test_voice_turn_audio_with_stt(jarvis, palace, pipeline, stt, tts, output):
    """Audio processing: STT transcribes, then full voice turn runs."""
    stt.transcript = "jarvis read my mail"
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts)

    # Use a fake audio path — FakeSTT doesn't read it
    result = processor.process_audio("/tmp/fake_audio.wav", addressed=True)

    assert result.ok is True
    assert result.handled is True
    assert result.transcript == "read my mail"
    assert result.raw_transcript == "jarvis read my mail"
    assert result.response is not None
    assert stt.calls == 1
    assert result.stt_backend == "fake"


def test_voice_turn_audio_stt_unavailable(jarvis, palace, pipeline, output):
    """Audio processing with no STT backend degrades gracefully."""
    no_stt = FakeSTT(transcript="", backend="none", available=False)
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=no_stt, tts=FakeTTS())

    result = processor.process_audio("/tmp/fake_audio.wav", addressed=True)

    assert result.ok is False
    assert result.handled is False
    assert result.stt_backend == "none"
    assert "no STT" in result.reason or "no stt" in result.reason.lower()


# -- VoiceTurnProcessor: status ------------------------------------------


def test_voice_turn_status(jarvis, palace, pipeline, stt, tts, output):
    """status() returns processor and pipeline metrics."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts)

    processor.process_transcript("jarvis status check", addressed=True)

    status = processor.status()
    assert status["turns"] == 1
    assert status["session_id"] == processor.session.session_id
    assert "pipeline" in status
    assert status["pipeline"]["wake"]["word"] == "jarvis"
    assert status["memory"] is not None
    assert status["last_turn"] is not None
    assert status["last_turn"]["handled"] is True


def test_voice_turn_last_turn(jarvis, pipeline, stt, tts, output):
    """last_turn() returns the most recent turn result."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=None,
        output=output, stt=stt, tts=tts)

    assert processor.last_turn() is None

    processor.process_transcript("jarvis first", addressed=True)
    assert processor.last_turn() is not None
    assert processor.last_turn().transcript == "first"
    assert processor.last_turn().raw_transcript == "jarvis first"

    processor.process_transcript("jarvis second", addressed=True)
    assert processor.last_turn().transcript == "second"
    assert processor.last_turn().raw_transcript == "jarvis second"


# -- speak_text integration ----------------------------------------------


def test_speak_text_with_fake_tts(jarvis, output):
    """speak_text works with a fake TTS provider via VoiceSpeaker."""
    from jarvis.voice.speak import VoiceSpeaker

    speaker = VoiceSpeaker(config=jarvis.config.voice.__dict__,
                           output=output)
    result = speaker.say("hello from jarvis", play=False)

    assert result["ok"] is True
    assert result["spoken_aloud"] is False  # play=False
    assert result["response_text"] == "hello from jarvis"
    assert result["tts_id"] != ""


def test_voice_speaker_barge_in(jarvis, output):
    """VoiceSpeaker can start and stop speaking."""
    from jarvis.voice.speak import VoiceSpeaker

    speaker = VoiceSpeaker(config=jarvis.config.voice.__dict__,
                           output=output)
    result = speaker.say("test barge-in", play=False)
    assert result["ok"] is True
    stopped = speaker.stop()
    assert stopped is True


# -- VoicePipeline status ------------------------------------------------


def test_voice_pipeline_status(pipeline, stt, tts):
    """VoicePipeline.status() reports all component states."""
    pipeline.stt = stt
    pipeline.tts = tts
    pipeline.wake.heard_in("jarvis wake up")

    status = pipeline.status()
    assert status["wake"]["word"] == "jarvis"
    assert status["wake"]["detections"] == 1
    assert status["stt"] == "fake"
    assert status["tts"] == "fake"
    assert status["spoken"] == 0

    pipeline.respond("test response")
    status = pipeline.status()
    assert status["spoken"] == 1


# -- Memory Palace persistence -------------------------------------------


def test_voice_memory_persistence(jarvis, palace, pipeline, stt, tts, output):
    """Voice turns persist user + jarvis utterances and an episode."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts)

    processor.process_transcript("jarvis remember my name is alice", addressed=True)

    # Check conversation memories
    conv = palace.all(tier="conversation")
    user_mem = [m for m in conv if m.content.startswith("user:")]
    jarvis_mem = [m for m in conv if m.content.startswith("jarvis:")]
    assert len(user_mem) >= 1
    assert len(jarvis_mem) >= 1

    # Check episode memory
    ep = palace.all(tier="episodic")
    assert len(ep) >= 1
    episode = ep[0]
    assert "voice turn" in episode.content
    assert episode.metadata.get("session_id") == processor.session.session_id
    assert episode.metadata.get("intent") is not None


def test_voice_memory_auto_memory_off(jarvis, palace, pipeline, stt, tts, output):
    """auto_memory=False skips memory persistence."""
    processor = VoiceTurnProcessor(
        jarvis=jarvis, pipeline=pipeline, palace=palace,
        output=output, stt=stt, tts=tts, auto_memory=False)

    processor.process_transcript("jarvis no memory", addressed=True)

    assert processor.last_turn().memory_stored is False
    conv = palace.all(tier="conversation")
    assert len(conv) == 0
    ep = palace.all(tier="episodic")
    assert len(ep) == 0


# -- VoiceSession --------------------------------------------------------


def test_voice_session_turns(home):
    """VoiceSession groups turns with unique IDs."""
    session = VoiceSession(source="microphone")

    turn1 = session.next_turn(audio_id="audio-1", transcript_id="stt-1")
    turn2 = session.next_turn(audio_id="audio-2", transcript_id="stt-2")

    assert session.interaction_count == 2
    assert turn1["voice_session_id"] == turn2["voice_session_id"]
    assert turn1["audio_id"] == "audio-1"
    assert turn2["audio_id"] == "audio-2"
    assert turn1["transcript_id"] == "stt-1"
    assert turn2["transcript_id"] == "stt-2"
    assert turn1["cognition_id"] != turn2["cognition_id"]
    assert turn1["response_id"] != turn2["response_id"]
    assert turn1["tts_id"] != turn2["tts_id"]


def test_voice_session_to_dict(home):
    """VoiceSession.to_dict() serializes all fields."""
    session = VoiceSession(source="voice")
    session.next_turn()
    d = session.to_dict()
    assert d["source"] == "voice"
    assert d["interaction_count"] == 1
    assert d["session_id"].startswith("voice-")
    assert d["wake_state"] == "idle"
    assert d["privacy_mode"] == "transient"