"""Audio playback abstraction (5.1).

One place for Linux playback backends (aplay/paplay/ffplay) plus a
fake sink for tests. No subprocess calls scattered elsewhere. Bounded
timeouts; honest UNAVAILABLE when no backend exists.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PlaybackResult:
    status: str = "unknown"  # played | failed | unavailable
    backend: str = ""
    latency_ms: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "played"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "backend": self.backend,
                "latency_ms": self.latency_ms, "error": self.error}


class AudioOutput:
    name = "output"

    def play(self, audio_path: str | Path) -> PlaybackResult:
        raise NotImplementedError

    def available(self) -> bool:
        raise NotImplementedError

    def stop(self) -> bool:
        return False


class FakeAudioOutput(AudioOutput):
    name = "fake"

    def __init__(self) -> None:
        self.played: list[str] = []
        self.stopped = 0

    def available(self) -> bool:
        return True

    def play(self, audio_path: str | Path) -> PlaybackResult:
        self.played.append(str(audio_path))
        return PlaybackResult(status="played", backend=self.name)

    def stop(self) -> bool:
        self.stopped += 1
        return True


class SystemAudioOutput(AudioOutput):
    """aplay → paplay → ffplay, first present wins. Bounded, blocking."""

    name = "system"

    def __init__(self, backend: str = "auto") -> None:
        self.backend = self._resolve(backend)
        self._proc: subprocess.Popen | None = None

    @staticmethod
    def _resolve(backend: str) -> str:
        if backend != "auto":
            return backend
        for candidate in ("aplay", "paplay", "ffplay"):
            if shutil.which(candidate):
                return candidate
        return "none"

    def available(self) -> bool:
        return self.backend != "none"

    def play(self, audio_path: str | Path) -> PlaybackResult:
        started = time.perf_counter()
        if not self.available():
            return PlaybackResult(status="unavailable",
                                  backend="none",
                                  error="no playback backend")
        path = str(audio_path)
        if not Path(path).exists():
            return PlaybackResult(status="failed", backend=self.backend,
                                  error="audio file missing")
        try:
            if self.backend == "ffplay":
                cmd = [self.backend, "-nodisp", "-autoexit", "-v",
                       "error", path]
            else:
                cmd = [self.backend, path]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=120)
            latency = round((time.perf_counter() - started) * 1000, 2)
            if proc.returncode != 0:
                return PlaybackResult(
                    status="failed", backend=self.backend,
                    latency_ms=latency,
                    error=(proc.stderr or "playback failed")[-200:])
            return PlaybackResult(status="played", backend=self.backend,
                                  latency_ms=latency)
        except (OSError, subprocess.SubprocessError) as exc:
            return PlaybackResult(
                status="failed", backend=self.backend,
                error=f"{type(exc).__name__}: {exc}"[:200])

    def stop(self) -> bool:
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            return True
        return False


def output_for(name: str) -> AudioOutput:
    if name == "fake":
        return FakeAudioOutput()
    if name in ("system", "auto", "aplay", "paplay", "ffplay"):
        backend = "auto" if name in ("system", "auto") else name
        return SystemAudioOutput(backend)
    return SystemAudioOutput("none")


__all__ = ["PlaybackResult", "AudioOutput", "FakeAudioOutput",
           "SystemAudioOutput", "output_for"]
