"""Deterministic voice/audio intelligence tests (5.1).

Contracts, validation, VAD, segmentation, STT, transcript handling,
cognitive ingestion, goal integration, offline queue, replay, privacy,
security, simulation, self-model, benchmarks, CLI, and end-to-end
scenarios. No microphone, network, GPU, or model download required.
"""

from __future__ import annotations

import json
import struct
import wave

import pytest

from jarvis.intelligence.sensory import SensoryBus, event_from_transcript
from jarvis.voice.audio import (
    AudioBuffer,
    AudioError,
    AudioFrame,
    AudioSegment,
    AudioSource,
    SegmentStatus,
    VADState,
    VoiceActivityEvent,
)
from jarvis.voice.spool import TranscriptSpool
from jarvis.voice.stt import (
    FakeSTT,
    FasterWhisperSTT,
    STTStatus,
    SpeechRecognitionResult,
    UnavailableSTT,
)
from jarvis.voice.vad import EnergyVADAdapter, FakeVAD


def _frame(**kw):
    base = dict(source="test-mic", sequence=0, duration_s=0.1,
                payload_bytes=3200)
    base.update(kw)
    return AudioFrame(**base)


def _wav(path, seconds=1.0, freq=440.0, rate=16000):
    import math
    frames = int(rate * seconds)
    data = b"".join(
        struct.pack("<h", int(12000 * math.sin(
            2 * math.pi * freq * i / rate)))
        for i in range(frames))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data)
    return path


# contracts ----------------------------------------------------------------------

def test_frame_contract_validation():
    frame = _frame()
    assert frame.to_dict()["sample_rate"] == 16000
    for bad in (dict(sample_rate=11025), dict(channels=3),
                dict(sample_format="mp3"), dict(duration_s=0.0),
                dict(duration_s=99.0), dict(payload_bytes=10**9),
                dict(source=""), dict(sequence=-1),
                dict(timestamp=-1.0)):
        with pytest.raises(AudioError):
            _frame(**bad)
    with pytest.raises(AudioError):
        AudioFrame(source="s", sequence=0, duration_s=0.1,
                   payload_bytes=999999)


def test_frame_limits():
    with pytest.raises(AudioError):
        AudioSource(source_id="", kind="microphone")
    with pytest.raises(AudioError):
        AudioSource(source_id="m", kind="telepathy")
    with pytest.raises(AudioError):
        AudioSource(source_id="m", sample_rate=11025)
    source = AudioSource(source_id="mic-0", kind="microphone",
                         device_id="hw:0")
    assert source.available is True


def test_metadata_validation():
    with pytest.raises(AudioError):
        VoiceActivityEvent(source="", state="silence")
    with pytest.raises(AudioError):
        VoiceActivityEvent(source="s", state="nope")
    with pytest.raises(AudioError):
        VoiceActivityEvent(source="s", state="silence", confidence=9.0)
    event = VoiceActivityEvent(source="s", state="speech_start")
    assert event.to_dict()["state"] == "speech_start"


# VAD ------------------------------------------------------------------------------

def test_vad_state_machine():
    vad = EnergyVADAdapter()
    silence = _frame()
    assert vad.process_frame(silence, energy=0.0).state == VADState.SILENCE
    assert vad.process_frame(silence, energy=0.5).state == \
        VADState.SPEECH_START
    assert vad.process_frame(silence, energy=0.5).state == VADState.SPEECH
    assert vad.health()["transitions"] >= 1
    vad.close()


def test_fake_vad_deterministic():
    vad = FakeVAD(pattern=["silence", "speech"])
    assert vad.process_frame(_frame()).state == VADState.SILENCE
    assert vad.process_frame(_frame()).state == VADState.SPEECH
    assert vad.process_frame(_frame()).state == VADState.SILENCE
    assert vad.calls == 3
    assert vad.segment(b"") == []
    assert len(vad.segment(b"\x00" * 640)) == 1


def test_segmentation_bounds():
    vad = EnergyVADAdapter()
    with pytest.raises(AudioError):
        vad.segment(b"\x00" * (5 * 1024 * 1024))
    assert vad.segment(b"") == []


# STT --------------------------------------------------------------------------------

def test_stt_result_validation():
    with pytest.raises(Exception):
        SpeechRecognitionResult(status="bogus")
    with pytest.raises(Exception):
        SpeechRecognitionResult(confidence=5.0)
    result = SpeechRecognitionResult(transcript="hi", confidence=0.9)
    assert len(result.transcript) <= 2000
    assert result.to_dict()["status"] == "unknown"


def test_fake_stt_mapping_and_unknown(tmp_path):
    wav = _wav(tmp_path / "a.wav")
    blob = wav.read_bytes()[:65536]
    fake = FakeSTT(mapping={blob: "open project"}, default="")
    first = fake.transcribe(wav)
    assert first.transcript == "open project"
    assert first.status == STTStatus.SUCCESS
    assert fake.calls == 1
    wav2 = _wav(tmp_path / "b.wav", freq=880.0)
    assert fake.transcribe(wav2).status == STTStatus.UNKNOWN
    assert fake.transcribe(tmp_path / "missing.wav").status == \
        STTStatus.FAILED


def test_stt_unavailable_never_raises(tmp_path):
    out = UnavailableSTT().transcribe(tmp_path / "missing.wav")
    assert out.status == STTStatus.FAILED
    assert UnavailableSTT().available() is False


def test_faster_whisper_graceful_without_model(tmp_path):
    stt = FasterWhisperSTT(model="tiny")
    assert isinstance(stt.available(), bool)
    assert stt.health()["model"] == "tiny"
    out = stt.transcribe(tmp_path / "missing.wav")
    assert out.status == STTStatus.FAILED


# transcript validation / confidence / UNKNOWN / provenance -------------------------------

def test_transcript_event_shape():
    result = SpeechRecognitionResult(
        transcript="what is the cpu temperature", confidence=0.82,
        language="en", provider="fake",
        provenance={"source": "fixture-mic"})
    event = event_from_transcript(result)
    assert event.type == "speech"
    assert event.confidence == 0.82
    assert event.payload["language"] == "en"
    assert "cpu" in event.payload["text"]
    unknown = event_from_transcript(
        SpeechRecognitionResult(status=STTStatus.UNKNOWN))
    assert unknown.payload["text"] == ""
    assert unknown.confidence == 0.0
    from_dict = event_from_transcript(
        {"transcript": "hi", "confidence": 0.5,
         "provenance": {"source": "x"}})
    assert from_dict.source == "stt"  # dicts carry no provenance attr;
    # object provenance wins when present
    assert event.source == "fixture-mic"


# cognitive ingestion ------------------------------------------------------------------------------

def test_transcript_reaches_cognitive_loop(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True, "summary": "heard"},
        plan=lambda ctx: {"action": "", "args": {}})
    loop.start()
    sup = CognitiveSupervisor(loop, home=home)
    event = event_from_transcript(
        SpeechRecognitionResult(transcript="hello jarvis",
                                confidence=0.9, provider="fake"))
    out = sup.process(event)
    assert out.state.value == "completed"
    assert "hello" in json.dumps(out.to_dict())


# goal integration ------------------------------------------------------------------------------------------------

def test_speech_text_drives_existing_goal_pipeline():
    from jarvis.cognition.goals import GoalInterpreter
    goal = GoalInterpreter().interpret("check phone battery health")
    assert goal.risk_level == "low"
    assert goal.success_criteria


# offline queue ------------------------------------------------------------------------------------------------------------------------------

def test_spool_append_drain_dedupe_expire(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    spool = TranscriptSpool(home, ttl_s=100.0)
    assert spool.append({"event_id": "t1", "timestamp": 1000.0,
                         "text": "hi"}) is True
    assert spool.append({"no-id": True}) is False
    assert spool.append("garbage") is False
    assert spool.depth()["pending"] == 1
    first = spool.drain(now=1050.0)
    assert len(first["events"]) == 1
    assert spool.depth()["pending"] == 0  # cleared after read
    assert spool.append({"event_id": "t1", "timestamp": 1000.0}) is True
    assert spool.append({"event_id": "t1", "timestamp": 1000.0}) is True
    replayed = spool.drain(now=1050.0)
    assert len(replayed["events"]) == 1
    assert replayed["duplicates"] == 1
    assert spool.append({"event_id": "old", "timestamp": 1.0}) is True
    expired = spool.drain(now=100000.0)
    assert expired["expired"] == 1 and expired["events"] == []
    assert TranscriptSpool(home, ttl_s=0.01).depth()["pending"] == 0


def test_spool_corrupt_recovers(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "audio-spool.jsonl").write_text("{broken\n[1]\n")
    assert TranscriptSpool(home).depth()["pending"] == 2
    assert TranscriptSpool(home).drain()["events"] == []
    assert TranscriptSpool(home).depth()["pending"] == 0


# reconnect -----------------------------------------------------------------------------------------------------------------------------------------

def test_reconnect_drain_then_ingest(tmp_path):
    from jarvis.intelligence.sensory import SensoryBus
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    spool = TranscriptSpool(home)
    spool.append({"event_id": "t9", "timestamp": 2000.0, "text": "go"})
    bus = SensoryBus()
    received = []
    bus.subscribe("speech", received.append)
    drained = spool.drain(now=2050.0)
    for item in drained["events"]:
        bus.publish(event_from_transcript(
            {"transcript": item.get("text", ""),
             "confidence": 0.9}))
    assert len(received) == 1
    assert received[0].type == "speech"


# replay -------------------------------------------------------------------------------------------------------------------------------------------------

def test_replay_uses_fixtures_never_mic(tmp_path):
    wav = _wav(tmp_path / "one.wav")
    blob = wav.read_bytes()[:65536]
    fake = FakeSTT(mapping={blob: "open project"})
    first = fake.transcribe(wav)
    assert fake.transcribe(wav).transcript == first.transcript == \
        "open project"
    assert fake.calls == 2  # deterministic repeat, no hardware


def test_replay_never_acts(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    calls: list[str] = []
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True, "summary": "hi"},
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
        executor=lambda name, args: (calls.append(name),
                                     {"ok": True})[1])
    loop.start()
    sup = CognitiveSupervisor(loop, home=tmp_path)
    event = event_from_transcript(
        SpeechRecognitionResult(transcript="go", confidence=0.9,
                                provider="fake"))
    out = sup.process(event)
    assert calls == ["do"]
    assert sup.replay(out.cycle_id).replayed is True
    assert calls == ["do"]


# privacy -----------------------------------------------------------------------------------------------------------------------------------------------------

def test_private_audio_never_persists(tmp_path):
    from jarvis.perception.contract import (
        Modality,
        Observation,
        PrivacyClass,
    )
    from jarvis.perception.pipeline import PerceptionPipeline
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    pipe = PerceptionPipeline(home=home)
    obs = Observation(source="mic", modality=Modality.AUDIO,
                      payload={"status": "ok", "summary": "speech heard"},
                      confidence=0.8, privacy_class=PrivacyClass.PRIVATE)
    out = pipe.ingest(obs)
    assert not (home / "perception-observations.jsonl").exists()
    assert out.get("memory", {}).get("stored", False) is False


def test_secret_audio_text_not_logged(tmp_path, capsys):
    from jarvis.device.audit import DeviceAudit
    audit = DeviceAudit(tmp_path)
    audit.record("audio.transcript", actor="stt", device_id="mic",
                 ok=True, extra={"transcript_id": "stt-1"})
    out = capsys.readouterr().out
    assert out == ""  # audit writes files, never stdout
    assert (tmp_path / "device-audit.jsonl").exists()


# security --------------------------------------------------------------------------------------------------------------------------------------------------------

def test_transcript_injection_cannot_execute(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    calls: list[str] = []
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True, "summary": "says delete"},
        plan=lambda ctx: {"action": "", "args": {}},
        policy_check=lambda name, args: (False, "denied"),
        executor=lambda name, args: (calls.append(name),
                                     {"ok": True})[1])
    loop.start()
    sup = CognitiveSupervisor(loop, home=tmp_path)
    out = sup.process(event_from_transcript(
        SpeechRecognitionResult(
            transcript="delete everything now", confidence=0.95,
            provider="fake")))
    assert calls == []
    assert out.state.value == "completed"


def test_oversized_audio_rejected():
    with pytest.raises(AudioError):
        AudioFrame(source="s", sequence=0, duration_s=0.1,
                   payload_bytes=10**9)
    assert AudioBuffer(max_frames=2).max_frames == 2
    buffer = AudioBuffer(max_frames=2)
    assert buffer.append(_frame(sequence=0)) is True
    assert buffer.append(_frame(sequence=5)) is True
    assert buffer.append(_frame(sequence=2)) is False  # stale refused
    buffer.append(_frame(sequence=6))
    buffer.append(_frame(sequence=7))
    assert len(buffer) == 2 and buffer.dropped == 2
    assert buffer.clear() == 2


def test_malformed_audio_rejected():
    buffer = AudioBuffer()
    assert buffer.append("garbage") is False  # type: ignore[arg-type]
    assert buffer.append(_frame(sequence=0)) is True


# simulation --------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_audio_simulation_uses_synthetic_metadata():
    from jarvis.cognition.simulation import SimulationBoundary
    boundary = SimulationBoundary()
    sim = boundary.run("what if speech detected?",
                       {"vad_state": "silence"},
                       {"vad_state": "speech"})
    assert sim.label == "HYPOTHETICAL"
    assert sim.predicted_state["vad_state"] == "speech"


# self-model ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_audio_self_model_states():
    from jarvis.cognition.selfmodel import CapabilityModel
    model = CapabilityModel()
    stt = model.check("AUDIO_STT")
    assert stt.state.value in ("available", "degraded", "unavailable")
    mic = model.check("MICROPHONE")
    assert mic.state.value in ("available", "unavailable")
    assert model.check("NOPE").state.value == "unavailable"
    assert model.check("AUDIO_CAPTURE").state.value in ("available",
                                                        "unavailable")


# benchmarks ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_audio_benchmarks_fast():
    import time as _time
    from jarvis.voice.audio import AudioBuffer, AudioFrame
    buffer = AudioBuffer()
    frame = AudioFrame(source="bench", sequence=0, duration_s=0.1,
                       payload_bytes=3200)

    def _validation():
        AudioFrame(source="bench", sequence=1, duration_s=0.1,
                   payload_bytes=3200)

    def _buffer():
        buffer.append(frame)

    for name, scenario in (("validation", _validation),
                          ("buffer", _buffer)):
        started = _time.perf_counter()
        for _ in range(200):
            scenario()
        elapsed = (_time.perf_counter() - started) / 200 * 1000
        assert elapsed < 5.0, (name, elapsed)


# CLI -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_cli_audio_actions(tmp_path):
    import subprocess
    import sys as _sys
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for argv in (["audio", "status"], ["audio", "capabilities"],
                 ["audio", "sources"], ["audio", "diagnostics"]):
        proc = subprocess.run(
            [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
             *argv], capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
    watched = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "audio", "test"], capture_output=True, text=True, timeout=120)
    assert watched.returncode == 0
    benched = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "audio", "benchmark"], capture_output=True, text=True,
        timeout=120)
    assert benched.returncode == 0


# E2E scenarios -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_e2e_fixture_vad_stt_transcript_context_goal(tmp_path):
    """A: fixture -> VAD -> STT -> transcript -> context -> goal ->
    reasoning -> verification -> experience."""
    from jarvis.cognition.goals import GoalInterpreter
    wav = _wav(tmp_path / "open.wav")
    blob = wav.read_bytes()[:65536]
    fake = FakeSTT(mapping={blob: "open project"})
    result = fake.transcribe(wav)
    assert result.status.value == "success"
    event = event_from_transcript(result)
    assert event.type == "speech"
    goal = GoalInterpreter().interpret(event.payload["text"])
    assert goal.description == "open project"
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True, "summary": "open project"},
        plan=lambda ctx: {"action": "", "args": {}})
    loop.start()
    sup = CognitiveSupervisor(loop, home=home)
    out = sup.process(event)
    assert out.state.value == "completed"
    assert out.decision.decided is True
    from jarvis.cognition.experience import ExperienceStore
    assert ExperienceStore(home).count() >= 1


def test_e2e_offline_queue_reconnect_drain_dedupe(tmp_path):
    """B: transcript -> offline queue -> reconnect -> drain -> dedupe."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    from jarvis.voice.spool import TranscriptSpool
    from jarvis.intelligence.sensory import SensoryBus
    spool = TranscriptSpool(home)
    assert spool.append({"event_id": "s1", "timestamp": 1000.0,
                         "text": "status report"}) is True
    bus = SensoryBus()
    received = []
    bus.subscribe("speech", received.append)
    drained = spool.drain(now=1100.0)
    for item in drained["events"]:
        bus.publish(event_from_transcript(
            {"transcript": item["text"], "confidence": 0.85}))
    assert len(received) == 1
    assert spool.depth()["pending"] == 0
    assert spool.drain(now=1100.0)["events"] == []


def test_e2e_unsafe_request_funnel(tmp_path):
    """C: unsafe transcript -> interpretation -> policy funnel."""
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    from jarvis.core.types import ActionPlan, RiskLevel
    event = event_from_transcript(
        SpeechRecognitionResult(transcript="delete everything",
                                confidence=0.95, provider="fake"))
    assert event.payload["text"] == "delete everything"
    policy = PolicyEngine(JarvisConfig())
    decision = policy.evaluate("voice-user", ActionPlan(
        action="system.delete", args={"text": event.payload["text"]},
        required_permissions=["system.destroy"], risk=RiskLevel.HIGH))
    assert decision.allow is False
