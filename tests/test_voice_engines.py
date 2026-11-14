"""Voice engine tests: piper, kokoro and edge.

Deterministic: no network, no models, no mic, no speaker. The engines
are faked at the subprocess boundary, so these tests assert the
contract (arguments, timeouts, privacy metadata, honest failures) and
never the sound itself.

The privacy invariant matters most: the cloud engine (Edge) sends the
text off this machine, so it must never be picked automatically.
"""

from __future__ import annotations

import io
import subprocess
import sys as _sys
import wave
from pathlib import Path

import pytest

from jarvis.core.config import VoiceConfig
from jarvis.voice import runtime_setup, voice_assets
from jarvis.voice.tts import (EdgeTTSProvider, KokoroTTSProvider,
                              LocalFallbackTTSProvider, TTSRequest,
                              UnavailableTTSProvider, provider_for)


# helpers ---------------------------------------------------------------------

class _FakeResponse:
    """A urlopen() response that yields a fixed payload."""

    def __init__(self, payload: bytes) -> None:
        self._buf = io.BytesIO(payload)

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _fake_wav(path: Path, seconds: float = 0.5, rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))


class _Recorder:
    """A subprocess.run() stand-in that records the call."""

    def __init__(self, returncode: int = 0, stdout: str = "",
                 stderr: str = "", on_call=None) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.on_call = on_call
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), **kwargs})
        if self.on_call:
            self.on_call(list(argv), kwargs)
        return subprocess.CompletedProcess(list(argv), self.returncode,
                                          self.stdout, self.stderr)


# voice assets -----------------------------------------------------------------

def test_find_piper_voice_prefers_the_british_male(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    voices = voice_assets.voices_dir()
    voices.mkdir(parents=True)
    (voices / "en_US-ryan-high.onnx").write_bytes(b"model")
    (voices / "en_GB-northern_english_male-medium.onnx").write_bytes(b"model")
    found = voice_assets.find_piper_voice()
    assert found is not None
    assert found.stem == "en_GB-northern_english_male-medium"


def test_find_piper_voice_honours_the_configured_model(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    chosen = tmp_path / "custom.onnx"
    chosen.write_bytes(b"model")
    assert voice_assets.find_piper_voice(str(chosen)) == chosen
    # A configured model that does not exist falls back to discovery.
    assert voice_assets.find_piper_voice(str(tmp_path / "nope.onnx")) is None


def test_install_piper_voice_rejects_an_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = voice_assets.install_piper_voice("en_GB-does-not-exist")
    assert result["ok"] is False
    assert "unknown piper voice" in result["error"]
    assert result["available"]


def test_install_piper_voice_downloads_then_reuses(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen: list[str] = []

    def _urlopen(request, timeout=0):
        seen.append(request.full_url)
        return _FakeResponse(b"payload")

    monkeypatch.setattr(voice_assets.urllib.request, "urlopen", _urlopen)
    result = voice_assets.install_piper_voice(
        "en_GB-northern_english_male-medium")
    assert result["ok"] is True
    assert result["reused"] is False
    assert len(seen) == 2  # model + config
    assert (tmp_path / ".config" / "jarvis" / "voices"
            / "en_GB-northern_english_male-medium.onnx").exists()

    seen.clear()
    again = voice_assets.install_piper_voice(
        "en_GB-northern_english_male-medium")
    assert again["ok"] is True and again["reused"] is True
    assert seen == []  # nothing downloaded twice


def test_install_piper_voice_reports_a_failed_download(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    def _urlopen(request, timeout=0):
        raise OSError("no network")

    monkeypatch.setattr(voice_assets.urllib.request, "urlopen", _urlopen)
    result = voice_assets.install_piper_voice(
        "en_GB-northern_english_male-medium")
    assert result["ok"] is False
    assert "no network" in result["error"]
    # No half-written file is left behind.
    assert not list((tmp_path / ".config" / "jarvis" / "voices")
                    .glob("*.part"))


def test_install_kokoro_assets_writes_both_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    def _urlopen(request, timeout=0):
        return _FakeResponse(b"payload")

    monkeypatch.setattr(voice_assets.urllib.request, "urlopen", _urlopen)
    result = voice_assets.install_kokoro_assets()
    assert result["ok"] is True
    assert voice_assets.kokoro_installed() is True
    assert voice_assets.kokoro_model_path().exists()
    assert voice_assets.kokoro_voices_path().exists()


def test_engine_status_never_hides_the_cloud_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    status = voice_assets.engine_status()
    assert set(status) >= {"piper", "kokoro", "edge"}
    assert status["edge"]["cloud"] is True


# kokoro provider ---------------------------------------------------------------

def test_kokoro_provider_builds_the_right_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    model = tmp_path / "kokoro.onnx"
    model.write_bytes(b"model")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"voices")
    provider = KokoroTTSProvider(voice="bm_george", lang="en-gb",
                                 model=str(model), voices_path=str(voices))
    argv = provider._argv("in.txt", "out.wav")
    assert argv[0].endswith("kokoro-tts")
    assert argv[1] == "in.txt" and argv[2] == "out.wav"
    assert argv[argv.index("--voice") + 1] == "bm_george"
    assert argv[argv.index("--lang") + 1] == "en-gb"
    assert argv[argv.index("--model") + 1] == str(model)
    assert argv[argv.index("--voices") + 1] == str(voices)


def test_kokoro_provider_synthesizes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    model = tmp_path / "kokoro.onnx"
    model.write_bytes(b"model")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"voices")

    def _write_wav(argv, kwargs):
        _fake_wav(Path(argv[2]))

    monkeypatch.setattr(runtime_setup, "install_runtime", lambda **kw: {})
    monkeypatch.setattr("jarvis.voice.tts.kokoro_installed", lambda: True)
    monkeypatch.setattr("jarvis.voice.tts._find_binary",
                        lambda name: f"/fake/{name}")
    monkeypatch.setattr("jarvis.voice.tts.subprocess.run",
                        _Recorder(on_call=_write_wav))
    provider = KokoroTTSProvider(model=str(model), voices_path=str(voices))
    out = provider.synthesize(TTSRequest(text="hello"), tmp_path / "out.wav")
    assert out.ok
    assert out.duration_s > 0
    assert out.sample_rate == 24000
    assert out.metadata["local"] is True
    assert out.metadata["voice"] == "bm_george"


def test_kokoro_provider_fails_honestly_without_the_runtime(monkeypatch):
    monkeypatch.setattr("jarvis.voice.tts.kokoro_installed", lambda: False)
    monkeypatch.setattr("jarvis.voice.tts._find_binary", lambda name: "")
    provider = KokoroTTSProvider()
    assert provider.available() is False
    out = provider.synthesize(TTSRequest(text="hello"))
    assert not out.ok
    assert "not installed" in out.error


# edge provider -----------------------------------------------------------------

def test_edge_provider_marks_itself_as_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    def _write_mp3(argv, kwargs):
        Path(argv[-1]).write_bytes(b"ID3 fake mp3")

    monkeypatch.setattr("jarvis.voice.tts._find_binary",
                        lambda name: f"/fake/{name}")
    monkeypatch.setattr("jarvis.voice.tts._convert_to_wav",
                        lambda src, dest: False)
    monkeypatch.setattr("jarvis.voice.tts.subprocess.run",
                        _Recorder(on_call=_write_mp3))
    provider = EdgeTTSProvider(voice="en-GB-RyanNeural")
    out = provider.synthesize(TTSRequest(text="hello"), tmp_path / "out.wav")
    assert out.ok
    assert out.metadata["cloud"] is True
    assert out.metadata["local"] is False
    assert out.audio_path.endswith(".mp3")


def test_edge_provider_converts_to_wav_when_it_can(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    def _write_mp3(argv, kwargs):
        Path(argv[-1]).write_bytes(b"ID3 fake mp3")

    def _convert(src, dest):
        _fake_wav(dest)
        return True

    monkeypatch.setattr("jarvis.voice.tts._find_binary",
                        lambda name: f"/fake/{name}")
    monkeypatch.setattr("jarvis.voice.tts._convert_to_wav", _convert)
    monkeypatch.setattr("jarvis.voice.tts.subprocess.run",
                        _Recorder(on_call=_write_mp3))
    out = EdgeTTSProvider().synthesize(TTSRequest(text="hello"),
                                        tmp_path / "out.wav")
    assert out.ok
    assert out.audio_path.endswith(".wav")
    assert out.duration_s > 0


def test_edge_provider_fails_honestly_without_the_runtime(monkeypatch):
    monkeypatch.setattr("jarvis.voice.tts._find_binary", lambda name: "")
    provider = EdgeTTSProvider()
    assert provider.available() is False
    out = provider.synthesize(TTSRequest(text="hello"))
    assert not out.ok
    assert "not installed" in out.error


# the automatic chain -----------------------------------------------------------

def test_auto_chain_prefers_kokoro_then_piper(monkeypatch):
    monkeypatch.setattr("jarvis.voice.tts.KokoroTTSProvider.available",
                        lambda self: True)
    assert isinstance(provider_for("auto"), KokoroTTSProvider)

    monkeypatch.setattr("jarvis.voice.tts.KokoroTTSProvider.available",
                        lambda self: False)
    monkeypatch.setattr("jarvis.voice.tts.LocalFallbackTTSProvider._resolve",
                        lambda self: "piper")
    chosen = provider_for("auto")
    assert isinstance(chosen, LocalFallbackTTSProvider)
    assert chosen.backend == "piper"


def test_auto_chain_never_picks_the_cloud_engine(monkeypatch):
    """Privacy: text must not leave the machine unless asked for."""
    monkeypatch.setattr("jarvis.voice.tts.KokoroTTSProvider.available",
                        lambda self: True)
    monkeypatch.setattr("jarvis.voice.tts.EdgeTTSProvider.available",
                        lambda self: True)
    assert not isinstance(provider_for("auto"), EdgeTTSProvider)

    monkeypatch.setattr("jarvis.voice.tts.KokoroTTSProvider.available",
                        lambda self: False)
    monkeypatch.setattr("jarvis.voice.tts.LocalFallbackTTSProvider._resolve",
                        lambda self: "none")
    monkeypatch.setattr("jarvis.voice.tts.ChatterboxTTSProvider.available",
                        lambda self: False)
    assert isinstance(provider_for("auto"), UnavailableTTSProvider)


def test_provider_for_named_engines(monkeypatch):
    monkeypatch.setattr("jarvis.voice.tts._find_binary",
                        lambda name: f"/fake/{name}")
    assert isinstance(provider_for("kokoro"), KokoroTTSProvider)
    assert isinstance(provider_for("edge"), EdgeTTSProvider)
    assert isinstance(provider_for("edge-tts"), EdgeTTSProvider)
    assert isinstance(provider_for("mystery"), UnavailableTTSProvider)
    assert provider_for("mystery").available() is False


def test_provider_for_passes_the_configured_voices(monkeypatch):
    monkeypatch.setattr("jarvis.voice.tts._find_binary",
                        lambda name: f"/fake/{name}")
    kokoro = provider_for("kokoro", {"kokoro_voice": "bm_daniel"})
    assert kokoro.voice == "bm_daniel"
    edge = provider_for("edge", {"edge_voice": "en-GB-ThomasNeural"})
    assert edge.voice == "en-GB-ThomasNeural"


# the local fallback ------------------------------------------------------------

def test_piper_gets_bytes_on_stdin(tmp_path, monkeypatch):
    """Regression: piper reads stdin, and stdin must be bytes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    monkeypatch.setattr("jarvis.voice.tts.find_binary",
                        lambda name: f"/fake/{name}")
    monkeypatch.setattr("jarvis.voice.tts.find_piper_voice",
                        lambda preferred="": model)
    recorder = _Recorder()

    def _write_wav(argv, kwargs):
        _fake_wav(Path(argv[argv.index("--output_file") + 1]))

    recorder.on_call = _write_wav
    monkeypatch.setattr("jarvis.voice.tts.subprocess.run", recorder)
    provider = LocalFallbackTTSProvider()
    assert provider.backend == "piper"
    out = provider.synthesize(TTSRequest(text="hello"), tmp_path / "out.wav")
    assert out.ok
    assert out.duration_s > 0
    assert isinstance(recorder.calls[0]["input"], bytes)
    assert recorder.calls[0]["input"] == b"hello"


def test_local_fallback_prefers_espeak_when_there_is_no_voice(tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("jarvis.voice.tts.find_binary", lambda name: "")
    monkeypatch.setattr("jarvis.voice.tts.find_piper_voice",
                        lambda preferred="": None)
    provider = LocalFallbackTTSProvider()
    # espeak is present on this host; without it the provider is honest.
    assert provider.backend in ("espeak", "none")


# runtime setup -----------------------------------------------------------------

def test_runtime_install_reports_a_missing_uv(monkeypatch):
    monkeypatch.setattr(runtime_setup, "runtime_ready", lambda: False)
    monkeypatch.setattr(runtime_setup, "find_uv", lambda: "")
    result = runtime_setup.install_runtime()
    assert result["ok"] is False
    assert "uv" in result["error"]


def test_runtime_install_reuses_an_existing_runtime(monkeypatch):
    monkeypatch.setattr(runtime_setup, "runtime_ready", lambda: True)
    monkeypatch.setattr(runtime_setup, "installed_tools",
                        lambda: ["piper", "kokoro-tts", "edge-tts"])
    result = runtime_setup.install_runtime()
    assert result["ok"] is True and result["reused"] is True


# configuration -----------------------------------------------------------------

def test_voice_config_defaults():
    cfg = VoiceConfig()
    assert cfg.tts_provider == "auto"
    assert cfg.kokoro_voice == "bm_george"
    assert cfg.kokoro_lang == "en-gb"
    assert cfg.edge_voice == "en-GB-RyanNeural"
    assert cfg.piper_model == ""


# CLI ----------------------------------------------------------------------------

def _cli(home, *argv):
    return subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home), *argv],
        capture_output=True, text=True, timeout=120)


def test_cli_voice_voices_lists_the_engines(tmp_path):
    import json
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    proc = _cli(home, "voice", "voices", "--json")
    assert proc.returncode == 0, proc.stderr[-300:]
    payload = json.loads(proc.stdout[proc.stdout.index("{"):])
    assert set(payload) >= {"piper", "kokoro", "edge", "chatterbox"}
    assert payload["edge"]["cloud"] is True


def test_cli_voice_status_reports_the_engine(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    proc = _cli(home, "voice", "status")
    assert proc.returncode == 0, proc.stderr[-300:]
    assert "Engine:" in proc.stdout
