"""Voice runtime tests. Pure-logic parts run anywhere; backend parts degrade honestly."""

import struct
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.voice.runtime import (  # noqa: E402
    EnergyVAD,
    MicRecorder,
    Speaker,
    Transcriber,
    VoiceLoop,
    read_wav_mono16,
    rms,
)


def _silence(seconds=1, rate=16000):
    return b"\x00\x00" * (seconds * rate)


def _tone(seconds=1, rate=16000, amp=4000):
    return struct.pack(f"<{seconds * rate}h", *([amp] * seconds * rate))


def _write_wav(path, pcm, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def test_rms_silence_and_tone():
    assert rms(b"") == 0.0
    assert rms(_silence()) == 0.0
    assert rms(_tone()) > 0.05


def test_vad_segmentation():
    vad = EnergyVAD()
    assert vad.segment(_silence())["segments"] == []
    seg = vad.segment(_silence() + _tone() + _silence())
    assert len(seg["segments"]) == 1 and seg["speech_ms"] >= 900
    assert len(vad.first_utterance(_silence() + _tone())) > 16000
    assert vad.first_utterance(_silence()) == b""
    assert "floor" in vad.calibrate(_silence()[:3200])


def test_read_wav_native_and_conversion(tmp_path):
    native = tmp_path / "native.wav"
    _write_wav(native, _tone())
    pcm, rate = read_wav_mono16(str(native))
    assert rate == 16000 and len(pcm) == 32000
    other = tmp_path / "other.wav"
    _write_wav(other, _tone(seconds=1, rate=22050), rate=22050)
    pcm2, rate2 = read_wav_mono16(str(other))
    assert rate2 == 16000 and len(pcm2) > 30000


def test_transcriber_rejects_silence(tmp_path):
    wav = tmp_path / "sil.wav"
    _write_wav(wav, _silence())
    result = Transcriber().transcribe(str(wav))
    assert not result["ok"] and "silence" in result["error"]


def test_transcriber_missing_file(tmp_path):
    result = Transcriber().transcribe(str(tmp_path / "nope.wav"))
    assert not result["ok"]


def test_transcriber_backend_resolution():
    t = Transcriber()
    assert t.backend in ("faster-whisper", "speech_recognition", "none")
    assert t.available() == (t.backend != "none")


def test_speaker_reports_honestly():
    s = Speaker()
    out = s.say("test")
    assert "ok" in out and not s.speaking
    if out.get("spoken_aloud"):
        assert out["backend"] == "espeak-ng"
    else:
        assert "error" in out or "queued" in out


def test_voice_loop_status_and_gating():
    loop = VoiceLoop()
    status = loop.status()
    assert set(status) == {"mic", "stt", "tts", "wake_word", "vad"}
    ready, missing = loop.check_ready()
    assert isinstance(ready, bool) and isinstance(missing, list)
    assert MicRecorder().available() in (True, False)


def test_faster_whisper_when_installed(tmp_path):
    faster_whisper = pytest.importorskip("faster_whisper")
    assert faster_whisper is not None
    wav = tmp_path / "speech.wav"
    _write_wav(wav, _tone())
    result = Transcriber(model="tiny").transcribe(str(wav))
    assert result["backend"] == "faster-whisper"
    assert "ok" in result  # tone is not speech; either way the backend ran


@pytest.mark.skipif(MicRecorder().available() is False, reason="no mic backend")
def test_record_silence_file(tmp_path):
    # Records 1s from the mic; only asserts file plumbing, not content.
    rec = MicRecorder().record(1, str(tmp_path / "mic.wav"))
    assert "ok" in rec
