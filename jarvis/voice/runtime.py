"""Voice runtime: mic capture, energy VAD, STT backends, TTS, barge-in.

Standard library only. faster-whisper and sounddevice are used when
importable (e.g. inside .venv); otherwise the runtime reports exactly
which piece is missing instead of pretending to listen.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .pipeline import TextToSpeech, VoiceConfig, VoicePipeline, WakeWordDetector
from .session import VoiceSession


# -- PCM helpers (stdlib only) --------------------------------------------------
def rms(samples: bytes, width: int = 2) -> float:
    """Root-mean-square energy of one PCM frame."""
    if not samples:
        return 0.0
    fmt = "<" + ("h" * (len(samples) // 2)) if width == 2 else "b" * len(samples)
    try:
        values = struct.unpack(fmt, samples[: len(samples) // width * width])
    except struct.error:
        return 0.0
    if not values:
        return 0.0
    scale = 32768.0 if width == 2 else 128.0
    return (sum((v / scale) ** 2 for v in values) / len(values)) ** 0.5


def read_wav_mono16(path: str, target_rate: int = 16000) -> tuple[bytes, int]:
    """Return (pcm16 bytes, rate). Only native 16kHz mono is read directly;
    otherwise ffmpeg converts (ffmpeg is required for that path)."""
    with wave.open(path, "rb") as w:
        channels, width, rate, n = (w.getnchannels(), w.getsampwidth(),
                                    w.getframerate(), w.getnframes())
        raw = w.readframes(n)
    if rate == target_rate and channels == 1 and width == 2:
        return raw, rate
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(f"unsupported wav format ({rate}Hz/{channels}ch) "
                           "and ffmpeg is missing for conversion")
    out = path + ".16k.wav"
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path,
                           "-ar", str(target_rate), "-ac", "1",
                           "-c:a", "pcm_s16le", out],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not Path(out).exists():
        raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr[-300:]}")
    with wave.open(out, "rb") as w:
        return w.readframes(w.getnframes()), target_rate


# -- VAD -------------------------------------------------------------------------
@dataclass
class VADConfig:
    sample_rate: int = 16000
    frame_ms: int = 20
    speech_threshold: float = 0.02
    silence_threshold: float = 0.012
    min_speech_ms: int = 300
    end_silence_ms: int = 700
    max_utterance_ms: int = 15000
    pre_roll_ms: int = 200


class EnergyVAD:
    """Frame-energy voice activity detector with hysteresis."""

    def __init__(self, config: VADConfig | None = None) -> None:
        self.config = config or VADConfig()
        self.frame_bytes = int(self.config.sample_rate * self.config.frame_ms / 1000) * 2

    def calibrate(self, noise_pcm: bytes) -> dict[str, float]:
        energies = [rms(noise_pcm[i:i + self.frame_bytes])
                    for i in range(0, len(noise_pcm), self.frame_bytes)]
        floor = sum(energies) / len(energies) if energies else 0.005
        self.config.speech_threshold = max(self.config.speech_threshold, floor * 3.0)
        self.config.silence_threshold = max(self.config.silence_threshold, floor * 1.8)
        return {"floor": round(floor, 5),
                "speech": round(self.config.speech_threshold, 5),
                "silence": round(self.config.silence_threshold, 5)}

    def segment(self, pcm: bytes) -> dict[str, Any]:
        """Split PCM into speech/silence spans. Pure function — unit testable."""
        cfg = self.config
        frames = [pcm[i:i + self.frame_bytes]
                  for i in range(0, len(pcm), self.frame_bytes)]
        energies = [rms(f) for f in frames]
        in_speech = False
        speech_ms = 0
        silence_ms = 0
        segments: list[tuple[int, int]] = []
        start = 0
        for i, energy in enumerate(energies):
            if not in_speech:
                if energy >= cfg.speech_threshold:
                    in_speech = True
                    start = i
                    speech_ms = cfg.frame_ms
                    silence_ms = 0
            else:
                speech_ms += cfg.frame_ms
                if energy <= cfg.silence_threshold:
                    silence_ms += cfg.frame_ms
                    if silence_ms >= cfg.end_silence_ms and speech_ms >= cfg.min_speech_ms:
                        segments.append((start, i + 1))
                        in_speech = False
                        speech_ms = 0
                        silence_ms = 0
                else:
                    silence_ms = 0
                if speech_ms >= cfg.max_utterance_ms:
                    segments.append((start, i + 1))
                    in_speech = False
                    speech_ms = 0
                    silence_ms = 0
        if in_speech and speech_ms >= cfg.min_speech_ms:
            segments.append((start, len(frames)))
        return {"segments": segments, "frames": len(frames),
                "speech_ms": sum((e - s) for s, e in segments) * cfg.frame_ms}

    def first_utterance(self, pcm: bytes) -> bytes:
        """Cut PCM to the first VAD speech segment (with pre-roll)."""
        cfg = self.config
        found = self.segment(pcm)["segments"]
        if not found:
            return b""
        start, end = found[0]
        pre = cfg.pre_roll_ms // cfg.frame_ms
        lo = max(0, (start - pre) * self.frame_bytes)
        return pcm[lo:end * self.frame_bytes]


# -- mic capture -------------------------------------------------------------------
class MicRecorder:
    """Records 16kHz mono PCM via arecord (preferred) or sounddevice."""

    def __init__(self, rate: int = 16000) -> None:
        self.rate = rate

    def available(self) -> bool:
        if shutil.which("arecord"):
            return True
        try:
            import sounddevice  # noqa: F401
            return True
        except ImportError:
            return False

    def record(self, seconds: float, dest: str) -> dict[str, Any]:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        if shutil.which("arecord"):
            try:
                proc = subprocess.run(
                    ["arecord", "-q", "-f", "S16_LE", "-r", str(self.rate),
                     "-c", "1", "-d", str(int(seconds)), dest],
                    capture_output=True, text=True, timeout=seconds + 10)
                if proc.returncode == 0 and Path(dest).exists():
                    return {"ok": True, "path": dest, "backend": "arecord"}
                return {"ok": False, "error": proc.stderr[-300:] or "arecord failed"}
            except (OSError, subprocess.SubprocessError) as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        try:
            import sounddevice as sd
            import numpy as np
            frames = sd.rec(int(seconds * self.rate), samplerate=self.rate,
                            channels=1, dtype="int16", blocking=True)
            with wave.open(dest, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.rate)
                w.writeframes(frames.tobytes())
            return {"ok": True, "path": dest, "backend": "sounddevice"}
        except ImportError:
            return {"ok": False, "error": "no mic backend (arecord/sounddevice) available"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def record_until_silence(self, dest: str, vad: EnergyVAD,
                             poll_seconds: float = 0.5,
                             max_seconds: float = 15.0) -> dict[str, Any]:
        """Record in chunks, stop at VAD end-of-utterance. Needs arecord."""
        if shutil.which("arecord") is None:
            return self.record(max_seconds, dest)
        chunks: list[bytes] = []
        elapsed = 0.0
        heard_speech = False
        import tempfile
        while elapsed < max_seconds:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                part = tmp.name
            result = self.record(poll_seconds, part)
            if not result.get("ok"):
                return result
            try:
                pcm, _ = read_wav_mono16(part)
            finally:
                Path(part).unlink(missing_ok=True)
            chunks.append(pcm)
            elapsed += poll_seconds
            seg = vad.segment(b"".join(chunks))
            if seg["segments"]:
                heard_speech = True
                last_end = seg["segments"][-1][1] * vad.frame_bytes
                trailing = len(b"".join(chunks)) - last_end
                trailing_ms = trailing / vad.frame_bytes * vad.config.frame_ms
                if trailing_ms >= vad.config.end_silence_ms:
                    break
            elif heard_speech:
                break
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(dest, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(vad.first_utterance(b"".join(chunks)) or b"".join(chunks))
        return {"ok": True, "path": dest, "seconds": round(elapsed, 1)}


# -- STT ------------------------------------------------------------------------------
class Transcriber:
    """faster-whisper → SpeechRecognition/Google → honest failure.

    Default model is 'tiny' (verified ~2s for 2.4s audio on CPU).
    'medium' is ~9x slower; use it for difficult audio only.
    Robotic TTS voices transcribe poorly on any size — this is a
    sample-quality limit, not a pipeline defect.
    """

    def __init__(self, model: str = "tiny") -> None:
        self.model = model
        self._whisper: Any = None
        self.backend = self._resolve()

    def _resolve(self) -> str:
        try:
            import faster_whisper  # noqa: F401
            return "faster-whisper"
        except ImportError:
            pass
        try:
            import speech_recognition  # noqa: F401
            return "speech_recognition"
        except ImportError:
            return "none"

    def available(self) -> bool:
        return self.backend != "none"

    def transcribe(self, wav_path: str, language: str = "en") -> dict[str, Any]:
        try:
            pcm, _rate = read_wav_mono16(wav_path)
        except (OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": f"unreadable audio: {exc}"}
        if not pcm.strip(b"\x00"):
            return {"ok": False, "error": "silence: no audio energy"}
        if self.backend == "faster-whisper":
            return self._whisper_transcribe(pcm, language)
        if self.backend == "speech_recognition":
            return self._google_transcribe(wav_path)
        return {"ok": False, "error": "no STT backend installed",
                "hint": "use the project .venv (faster-whisper) for offline STT"}

    def _whisper_transcribe(self, pcm: bytes, language: str) -> dict[str, Any]:
        try:
            import numpy as np
            from faster_whisper import WhisperModel
        except ImportError as exc:
            return {"ok": False, "error": f"missing dependency: {exc}",
                    "backend": "faster-whisper"}
        try:
            if self._whisper is None:
                self._whisper = WhisperModel(self.model, device="cpu",
                                             compute_type="int8")
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, info = self._whisper.transcribe(audio, language=language,
                                                      vad_filter=True)
            text = " ".join(s.text for s in segments).strip()
            if not text:
                return {"ok": False, "error": "nothing recognized",
                        "backend": "faster-whisper"}
            return {"ok": True, "text": text, "backend": "faster-whisper",
                    "language": info.language,
                    "confidence": round(info.language_probability, 3)}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "backend": "faster-whisper"}

    @staticmethod
    def _google_transcribe(wav_path: str) -> dict[str, Any]:
        try:
            import speech_recognition as sr
        except ImportError:
            return {"ok": False, "error": "speech_recognition not installed"}
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as src:
                audio = recognizer.record(src)
            return {"ok": True, "text": recognizer.recognize_google(audio),
                    "backend": "google"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# -- speaking TTS with barge-in ----------------------------------------------------------
class Speaker:
    """Speaks via espeak-ng subprocess so speech can be interrupted."""

    def __init__(self, tts: TextToSpeech | None = None) -> None:
        self.tts = tts or TextToSpeech()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def say(self, text: str) -> dict[str, Any]:
        self.stop()
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if binary is None:
            record = self.tts.speak(text)
            record["spoken_aloud"] = False
            return record
        try:
            with self._lock:
                self._proc = subprocess.Popen(
                    [binary, "-v", "en", "-s", str(self.tts.rate
                                                  if hasattr(self.tts, "rate") else 145),
                     text[:800]],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._proc.wait()
            return {"ok": True, "backend": "espeak-ng", "spoken_aloud": True,
                    "interrupted": self._proc.returncode not in (0, None)}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def stop(self) -> bool:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            return True
        return False

    @property
    def speaking(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None


# -- conversational loop --------------------------------------------------------------------
@dataclass
class VoiceLoop:
    pipeline: VoicePipeline = field(default_factory=VoicePipeline)
    vad: EnergyVAD = field(default_factory=EnergyVAD)
    mic: MicRecorder = field(default_factory=MicRecorder)
    stt: Transcriber = field(default_factory=Transcriber)
    speaker: Speaker = field(default_factory=Speaker)
    workdir: str = "/tmp/jarvis-voice"
    always_listen: bool = False
    session: Any = field(default_factory=lambda: VoiceSession())
    jarvis_voice: bool = False
    voice_config: Any = field(default_factory=dict)
    max_turns: int = 0
    _stop: Any = field(default=None, repr=False)

    def stop(self) -> bool:
        """Foundation for interruption: halt speech, signal the run
        loop to exit after the current turn. Never strands audio."""
        stopped = False
        try:
            stopped = bool(self.speaker.stop())
        except Exception:
            pass
        if self._stop is not None:
            try:
                self._stop.set()
            except Exception:
                pass
        return stopped

    def status(self) -> dict[str, Any]:
        return {"mic": self.mic.available(), "stt": self.stt.backend,
                "tts": self.speaker.tts.backend,
                "wake_word": self.pipeline.config.wake_word,
                "vad": {"speech": self.vad.config.speech_threshold,
                        "silence": self.vad.config.silence_threshold}}

    def check_ready(self) -> tuple[bool, list[str]]:
        missing = []
        if not self.mic.available():
            missing.append("microphone (arecord/sounddevice)")
        if not self.stt.available():
            missing.append("STT (faster-whisper in .venv, or speech_recognition)")
        if not self.speaker.tts.available():
            missing.append("TTS (espeak-ng/piper)")
        return (not missing), missing

    def listen_once(self, addressed: bool = True) -> dict[str, Any]:
        """Record one utterance → transcribe → wake-gate. Returns transcript."""
        ready, missing = self.check_ready()
        if not ready:
            return {"ok": False, "error": "voice not ready",
                    "missing": missing}
        Path(self.workdir).mkdir(parents=True, exist_ok=True)
        dest = str(Path(self.workdir) / "utterance.wav")
        rec = self.mic.record_until_silence(dest, self.vad)
        if not rec.get("ok"):
            return {"ok": False, "error": rec.get("error", "record failed")}
        heard = self.stt.transcribe(dest)
        if not heard.get("ok"):
            return {"ok": False, "error": heard.get("error", "transcribe failed")}
        gate = self.pipeline.handle(heard["text"], addressed=addressed)
        if not gate["for_jarvis"]:
            return {"ok": False, "error": "not addressed to JARVIS",
                    "transcript": heard["text"]}
        return {"ok": True, "text": gate["text"], "raw": heard["text"],
                "backend": heard.get("backend", "")}

    def converse_once(self, jarvis: Any, addressed: bool = True) -> dict[str, Any]:
        """Full turn: listen → think → speak. Barge-in stops speech on wake.

        Turns share the loop's VoiceSession: each turn mints fresh
        audio/transcript/cognition ids while the session id stays
        constant, so a multi-turn conversation reconstructs from
        metadata (no raw audio stored)."""
        heard = self.listen_once(addressed=addressed)
        if not heard.get("ok"):
            return heard
        turn = self.session.next_turn()
        think_started = time.monotonic()
        result = jarvis.cycle_once(heard["text"], source="voice",
                                   session_id=self.session.session_id)
        think_ms = round((time.monotonic() - think_started) * 1000.0, 1)
        if self.jarvis_voice:
            from .speak import VoiceSpeaker
            speaker = VoiceSpeaker(config=self.voice_config or None)
            spoken = speaker.say(result.response, workdir=self.workdir,
                                 correlation_id=turn["cognition_id"])
        else:
            spoken = self.speaker.say(result.response)
        return {"ok": True, "heard": heard["text"], "response": result.response,
                "intent": result.intent, "spoken": spoken,
                "voice_session_id": self.session.session_id,
                "think_ms": think_ms,
                "turn": turn}

    def run(self, jarvis: Any, on_turn: Callable[[dict[str, Any]], None] | None = None,
            stop: threading.Event | None = None) -> dict[str, Any]:
        """Continuous loop until stop is set. Ctrl-C safe via the event.

        Each run gets a fresh voice session so separate conversations
        never share turn linkage."""
        self.session = VoiceSession()
        stop = stop or threading.Event()
        self._stop = stop
        turns = 0
        latencies: list[float] = []
        while not stop.is_set():
            turn_started = time.monotonic()
            turn = self.converse_once(jarvis, addressed=self.always_listen)
            turns += 1
            latencies.append(round(
                (time.monotonic() - turn_started) * 1000.0, 1))
            if on_turn:
                on_turn(turn)
            if not turn.get("ok") and "not ready" in str(turn.get("error", "")):
                return {"ok": False, "turns": turns, "error": turn.get("error")}
            if self.max_turns > 0 and turns >= self.max_turns:
                break
        summary: dict[str, Any] = {"ok": True, "turns": turns}
        if latencies:
            ordered = sorted(latencies)
            summary["turn_ms"] = {
                "avg": round(sum(ordered) / len(ordered), 1),
                "p95": ordered[min(len(ordered) - 1,
                                   int(len(ordered) * 0.95))],
                "max": ordered[-1]}
        return summary
