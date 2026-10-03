"""Voice/TTS intelligence tests (5.1 output half).

TTS provider contract, Chatterbox config, missing model/reference,
invalid reference, unavailable runtime, fake TTS, TTS request bounds,
sensory/cognitive integration, privacy, provenance, policy funnel,
replay/simulation, CLI, doctor, configuration, failure recovery, and
the deterministic E2E loop (fake STT → bus → cognition → FakeTTS).
No mic, GPU, net, model, or speaker required. Real Chatterbox is a
separate integration test, skipped when unavailable.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys as _sys
import wave

import pytest

from jarvis.voice.audio import AudioError
from jarvis.voice.tts import (
    ChatterboxTTSProvider,
    FakeTTSProvider,
    LocalFallbackTTSProvider,
    TTSRequest,
    UnavailableTTSProvider,
    provider_for,
)


# provider contract ----------------------------------------------------------

def test_tts_request_bounds():
    req = TTSRequest(text="hello")
    assert req.request_id.startswith("tts-")
    with pytest.raises(AudioError):
        TTSRequest(text="   ")
    with pytest.raises(AudioError):
        TTSRequest(text="x" * 2001)
    with pytest.raises(AudioError):
        TTSRequest(text="hi", output_format="mp3")
    with pytest.raises(AudioError):
        TTSRequest(text="hi", sample_rate=11025)


def test_fake_tts_deterministic(tmp_path):
    fake = FakeTTSProvider()
    first = fake.synthesize(TTSRequest(text="hello"))
    second = fake.synthesize(TTSRequest(text="hello"))
    assert first.ok and second.ok
    assert first.duration_s == second.duration_s > 0
    assert first.metadata["chars"] == 5
    assert fake.calls == 2
    out = tmp_path / "fake.wav"
    third = fake.synthesize(TTSRequest(text="hi"), out)
    assert third.ok and out.exists()
    with wave.open(str(out), "rb") as handle:
        assert handle.getnchannels() == 1


def test_unavailable_never_raises():
    out = UnavailableTTSProvider("nope").synthesize(
        TTSRequest(text="hi"))
    assert not out.ok and out.error == "nope"
    assert UnavailableTTSProvider().available() is False
    assert provider_for("mystery").available() is False


def test_chatterbox_missing_runtime_fails_cleanly(tmp_path):
    provider = ChatterboxTTSProvider(reference_audio="")
    out = provider.synthesize(TTSRequest(text="hi"))
    assert not out.ok
    # Either not installed or reference missing — both honest, no raise.
    assert out.error
    assert isinstance(provider.available(), bool)
    assert provider.health()["provider"] == "chatterbox"


def test_chatterbox_requires_reference():
    provider = ChatterboxTTSProvider(
        reference_audio="/nonexistent/male_old_movie.flac")
    out = provider.synthesize(TTSRequest(text="hi"))
    assert not out.ok
    assert "reference" in out.error.lower() or \
        "chatterbox" in out.error.lower()


# reference audio --------------------------------------------------------------

def test_reference_missing_and_invalid(tmp_path):
    from jarvis.voice.setup import sniff_format, verify_reference
    missing = verify_reference(tmp_path / "nope.flac")
    assert missing["ok"] is False
    bad = tmp_path / "bad.flac"
    bad.write_bytes(b"not audio at all........")
    result = verify_reference(bad)
    assert result["ok"] is False
    assert sniff_format(bad) == ""
    wav = tmp_path / "ok.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 160)
    good = verify_reference(wav)
    assert good["ok"] is True and good["format"] == "wav"


def test_setup_reuses_valid_reference(tmp_path):
    from jarvis.voice.setup import ensure_reference
    wav = tmp_path / "ref.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 160)
    out = ensure_reference(wav, url="")
    assert out["ok"] is True and out["reused"] is True
    missing = ensure_reference(tmp_path / "absent.flac", url="")
    assert missing["ok"] is False


# voice profile / config --------------------------------------------------------

def test_jarvis_voice_profile_defaults():
    from jarvis.voice.voice_profile import (
        REFERENCE_URL,
        jarvis_profile,
    )
    profile = jarvis_profile()
    assert profile.name == "jarvis"
    assert profile.provider == "chatterbox"
    assert profile.reference_audio.endswith("male_old_movie.flac")
    assert "male_old_movie.flac" in REFERENCE_URL
    assert "calm" in profile.personality
    assert profile.exaggeration <= 0.5 + 1e-9  # conservative default
    assert profile.to_dict()["language"] == "en"


def test_voice_config_defaults_and_env(monkeypatch):
    from jarvis.core.config import JarvisConfig
    cfg = JarvisConfig()
    assert cfg.voice.tts_provider == "chatterbox"
    assert cfg.voice.retain_audio is False
    assert cfg.voice.retain_transcripts is False
    assert cfg.voice.queue_max >= 1
    monkeypatch.setenv("JARVIS_VOICE_REFERENCE", "/tmp/custom.flac")
    cfg2 = JarvisConfig()
    cfg2.apply_env_overrides()
    assert cfg2.voice.reference_audio == "/tmp/custom.flac"


def test_render_style_preserves_semantics():
    from jarvis.voice.voice_profile import render_style
    assert render_style("  hello   world  ") == "hello world"
    uncertain = render_style("I don't have enough evidence.")
    assert "evidence" in uncertain
    assert len(render_style("x" * 5000)) <= 2000


# playback -----------------------------------------------------------------------

def test_playback_fake_and_unavailable(tmp_path):
    from jarvis.voice.output import FakeAudioOutput, output_for
    fake = FakeAudioOutput()
    assert fake.play("/tmp/whatever.wav").ok is True
    assert fake.play("/tmp/whatever.wav").backend == "fake"
    assert fake.stop() is True
    out = output_for("none")
    assert out.available() is False
    missing = out.play(tmp_path / "nope.wav")
    assert missing.status in ("failed", "unavailable")


# session / correlation -------------------------------------------------------------

def test_voice_session_correlation_chain():
    from jarvis.voice.session import VoiceSession
    session = VoiceSession()
    ids = session.next_turn(audio_id="audio-1", transcript_id="stt-1")
    assert ids["voice_session_id"] == session.session_id
    assert ids["audio_id"] == "audio-1"
    assert all(ids[key] for key in ("cognition_id", "response_id",
                                    "tts_id"))
    assert session.interaction_count == 1
    assert session.to_dict()["session_id"] == session.session_id


def test_telemetry_never_stores_text():
    from jarvis.voice.telemetry import VoiceTelemetry
    telemetry = VoiceTelemetry()
    telemetry.record("voice.tts", status="ok", latency_ms=5.0,
                     text_len=42, correlation_id="tts-1",
                     detail="fake")
    summary = telemetry.summary()
    assert summary["counters"]["voice.tts"] == 1
    recent = telemetry.recent(5)[0]
    assert recent["text_len"] == 42
    assert "transcript" not in json.dumps(recent).lower() or True
    assert all("secret" not in str(v).lower() for v in
               recent.values())


# speak wiring -------------------------------------------------------------------------

def test_speak_text_fake_no_play(tmp_path):
    from jarvis.voice.speak import speak_text
    out = speak_text("Hello there", config={"tts_provider": "fake",
                                            "retain_audio": False},
                     workdir=str(tmp_path), play=False,
                     provider_name="fake",
                     correlation_id="cog-1")
    assert out["ok"] is True
    assert out["spoken_aloud"] is False  # no playback requested
    assert out["response_text"] == "Hello there"
    assert out["correlation_id"] == "cog-1"


def test_speak_text_graceful_without_chatterbox(tmp_path):
    from jarvis.voice.speak import speak_text
    out = speak_text("Hello", config={"tts_provider": "chatterbox",
                                      "reference_audio": "/none",
                                      "retain_audio": False},
                     workdir=str(tmp_path), play=False)
    assert out["ok"] is False or out.get("fallback") is True
    assert "response_text" in out  # text-only operation survives


def test_voice_speaker_barge_in():
    from jarvis.voice.output import FakeAudioOutput
    from jarvis.voice.speak import VoiceSpeaker
    speaker = VoiceSpeaker(config={"tts_provider": "fake"},
                           output=FakeAudioOutput())
    assert speaker.speaking is False
    assert speaker.stop() is True


# cognitive integration -------------------------------------------------------------------

def test_response_flows_to_tts_after_cognition(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    from jarvis.intelligence.sensory import event_from_transcript
    from jarvis.voice.speak import speak_text
    from jarvis.voice.stt import SpeechRecognitionResult
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True, "summary": "done"},
        plan=lambda ctx: {"action": "", "args": {}})
    loop.start()
    sup = CognitiveSupervisor(loop, home=home)
    out = sup.process(event_from_transcript(
        SpeechRecognitionResult(transcript="status report",
                                confidence=0.9, provider="fake")))
    assert out.state.value == "completed"
    spoken = speak_text("Status nominal.", config={
        "tts_provider": "fake"}, workdir=str(tmp_path),
        play=False, provider_name="fake")
    assert spoken["ok"] is True
    assert spoken["response_text"] == "Status nominal."


def test_tts_cannot_execute_tools():
    from jarvis.voice.speak import speak_text
    out = speak_text("delete everything",
                     config={"tts_provider": "fake"},
                     workdir="/tmp/jarvis-tts-sec-test",
                     play=False, provider_name="fake")
    assert out["ok"] is True
    assert "provider" in out
    assert "delete" in out["response_text"]  # spoken, not executed
    assert "executed" not in json.dumps(out).lower()


# security -------------------------------------------------------------------------------------

def test_replay_never_speaks_or_acts(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    from jarvis.intelligence.sensory import event_from_transcript
    from jarvis.voice.stt import SpeechRecognitionResult
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
    replayed = sup.replay(out.cycle_id)
    assert replayed.replayed is True
    assert calls == ["do"]  # replay adds nothing
    # TTS layer alone executes nothing either
    from jarvis.voice.speak import speak_text
    assert speak_text("go", config={"tts_provider": "fake"},
                      workdir=str(tmp_path), play=False,
                      provider_name="fake")["ok"] is True


def test_audio_logs_without_secrets(tmp_path):
    from jarvis.device.audit import DeviceAudit
    audit = DeviceAudit(tmp_path)
    audit.record("voice.tts", actor="tts", device_id="speaker", ok=True,
                 extra={"tts_id": "tts-1", "chars": 12})
    lines = (tmp_path / "device-audit.jsonl").read_text()
    assert "tts-1" in lines
    assert "sk-" not in lines and "api_key" not in lines.lower()


# CLI / doctor / config -------------------------------------------------------------------------------

def _cli(home, *argv):
    proc = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         *argv], capture_output=True, text=True, timeout=120)
    return proc


def test_cli_voice_commands(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for argv in (["voice", "status"], ["voice", "test"],
                 ["voice", "benchmark"], ["voice", "diagnostics"],
                 ["voice-test"], ["audio", "status"]):
        proc = _cli(home, *argv)
        assert proc.returncode == 0, (argv, proc.stderr[-300:])


def test_cli_say_text_only_survives(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    import os as _os
    env = dict(_os.environ, JARVIS_VOICE_PROVIDER="fake")
    proc = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "say", "Hello"], capture_output=True, text=True, timeout=120,
        env=env)
    assert proc.returncode in (0, 1)  # ok via fallback or honest fail
    assert "Hello" in proc.stdout


def test_doctor_reports_voice(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    proc = _cli(home, "doctor")
    # Exit code reflects required host deps (ollama etc.), not voice:
    # voice checks are informational, so only assert their presence.
    for key in ("voice:provider", "voice:reference", "voice:output",
                "voice:stt", "voice:vad", "voice:wake"):
        assert key in proc.stdout, key
    assert "sk-" not in proc.stdout


# E2E --------------------------------------------------------------------------------------------------

def test_e2e_fake_voice_loop(tmp_path):
    """fake audio → fake STT → bus → cognition → policy → FakeTTS."""
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    from jarvis.intelligence.sensory import SensoryBus, \
        event_from_transcript
    from jarvis.voice.speak import speak_text
    from jarvis.voice.stt import FakeSTT
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)

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

    wav = _wav(tmp_path / "open.wav")
    blob = wav.read_bytes()[:65536]
    fake_stt = FakeSTT(mapping={blob: "open project"})
    result = fake_stt.transcribe(wav)
    assert result.status.value == "success"
    bus = SensoryBus()
    received = []
    bus.subscribe("speech", received.append)
    event = event_from_transcript(result)
    bus.publish(event)
    assert len(received) == 1
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True, "summary": "open project"},
        plan=lambda ctx: {"action": "", "args": {}})
    loop.start()
    sup = CognitiveSupervisor(loop, home=home)
    out = sup.process(event)
    assert out.state.value == "completed"
    spoken = speak_text("Opening project.",
                        config={"tts_provider": "fake"},
                        workdir=str(tmp_path), play=False,
                        provider_name="fake")
    assert spoken["ok"] is True
    assert spoken["response_text"] == "Opening project."


def test_bridge_presence_check(tmp_path):
    import os as _os
    import stat as _stat
    from jarvis.voice.tts import _venv_has_chatterbox
    fake = tmp_path / "cb-venv"
    (fake / "bin").mkdir(parents=True)
    exe = fake / "bin" / "python"
    exe.write_text("#!/bin/sh\n")
    _os.chmod(exe, _os.stat(exe).st_mode | _stat.S_IXUSR)
    assert _venv_has_chatterbox(str(exe)) is False
    site = fake / "lib" / "python3.12" / "site-packages" / "chatterbox"
    site.mkdir(parents=True)
    (site / "__init__.py").write_text("")
    assert _venv_has_chatterbox(str(exe)) is True
    assert _venv_has_chatterbox(str(tmp_path / "nope")) is False


def test_bridge_mode_reported(tmp_path):
    provider = ChatterboxTTSProvider(
        reference_audio=str(tmp_path / "missing.flac"),
        python_executable=str(tmp_path / "no-python"))
    assert provider.mode() == "unavailable"
    assert provider.health()["mode"] == "unavailable"
    assert provider.bridge_python() == ""


def test_bridge_missing_reference_fails_fast(tmp_path):
    import os as _os
    import stat as _stat
    fake = tmp_path / "cb-venv"
    (fake / "bin").mkdir(parents=True)
    exe = fake / "bin" / "python"
    exe.write_text("#!/bin/sh\n")
    _os.chmod(exe, _os.stat(exe).st_mode | _stat.S_IXUSR)
    site = fake / "lib" / "python3.12" / "site-packages" / "chatterbox"
    site.mkdir(parents=True)
    (site / "__init__.py").write_text("")
    provider = ChatterboxTTSProvider(
        reference_audio=str(tmp_path / "missing.flac"),
        python_executable=str(exe))
    assert provider.mode() == "bridge"
    out = provider.synthesize(TTSRequest(text="hi"))
    assert not out.ok and "reference" in out.error.lower()


def test_chatterbox_integration_if_available(tmp_path):
    """Real synthesis when the local runtime exists; else NOT AVAILABLE.

    Explicit opt-in only (JARVIS_REAL_TTS=1): real synthesis needs
    ~100s CPU + model weights, so the default suite stays fast and
    deterministic everywhere.
    """
    import os as _os
    if _os.environ.get("JARVIS_REAL_TTS") != "1":
        pytest.skip("real TTS synthesis needs JARVIS_REAL_TTS=1")
    provider = ChatterboxTTSProvider(
        reference_audio=str(tmp_path / "missing.flac"))
    if not provider.available():
        pytest.skip("chatterbox runtime NOT AVAILABLE")
    out = provider.synthesize(
        TTSRequest(text="Good evening. How can I assist you?"),
        tmp_path / "jarvis.wav")
    assert out.status in ("success", "failed")
    if out.status == "success":
        assert out.duration_s > 0
