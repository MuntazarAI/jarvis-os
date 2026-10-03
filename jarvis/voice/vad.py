"""Voice activity detection abstraction (5.1).

VAD turns validated frames into state transitions; segmentation
groups them into bounded speech segments. Implementations are
replaceable: the energy detector wraps the existing proven
runtime.EnergyVAD, fakes are deterministic. Bounded always:
fixed frame windows, silence timeouts, maximum speech duration.
"""

from __future__ import annotations

import time
from typing import Any

from .audio import (
    MAX_SEGMENT_BYTES,
    AudioError,
    AudioFrame,
    AudioSegment,
    SegmentStatus,
    VoiceActivityEvent,
    VADState,
)


class VoiceActivityDetector:
    """process_frame -> VADState; segment(pcm) -> spans. Pure where possible."""

    name = "vad"

    def process_frame(self, frame: AudioFrame) -> VoiceActivityEvent:
        raise NotImplementedError

    def segment(self, pcm: bytes, source: str = "") -> list[AudioSegment]:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": True}

    def close(self) -> None:
        return None


class EnergyVADAdapter(VoiceActivityDetector):
    """Adapter over the existing runtime.EnergyVAD (hysteresis segmenter).

    Stateful per-frame tracking with silence timeout; the underlying
    segment() stays the pure reference implementation.
    """

    name = "energy"

    def __init__(self, speech_threshold: float = 0.02,
                 silence_threshold: float = 0.012,
                 silence_timeout_s: float = 0.7,
                 max_speech_s: float = 15.0) -> None:
        from .runtime import EnergyVAD, VADConfig, rms
        self._vad = EnergyVAD(VADConfig(
            speech_threshold=speech_threshold,
            silence_threshold=silence_threshold))
        self._rms = rms
        self._silence_timeout_s = silence_timeout_s
        self._max_speech_s = max_speech_s
        self._in_speech = False
        self._silence_since: float | None = None
        self._speech_since: float | None = None
        self._last_frame: AudioFrame | None = None
        self.transitions = 0

    def process_frame(self, frame: AudioFrame,
                      energy: float = 0.0) -> VoiceActivityEvent:
        """Classify one frame. `energy` is the measured RMS 0..1."""
        if energy >= self._vad.config.speech_threshold:
            if not self._in_speech:
                self._in_speech = True
                self._speech_since = time.time()
                self._silence_since = None
                self.transitions += 1
                return VoiceActivityEvent(
                    source=frame.source, state=VADState.SPEECH_START,
                    confidence=min(1.0, energy * 10.0))
            self._silence_since = None
            if time.time() - (self._speech_since or 0.0) > \
                    self._max_speech_s:
                self._in_speech = False
                self.transitions += 1
                return VoiceActivityEvent(
                    source=frame.source, state=VADState.SPEECH_END,
                    confidence=0.5)
            return VoiceActivityEvent(source=frame.source,
                                      state=VADState.SPEECH,
                                      confidence=min(1.0, energy * 10.0))
        if self._in_speech:
            now = time.time()
            if self._silence_since is None:
                self._silence_since = now
            if now - self._silence_since >= self._silence_timeout_s:
                self._in_speech = False
                self._silence_since = None
                self.transitions += 1
                return VoiceActivityEvent(source=frame.source,
                                          state=VADState.SPEECH_END,
                                          confidence=0.6)
            return VoiceActivityEvent(source=frame.source,
                                      state=VADState.SPEECH, confidence=0.4)
        return VoiceActivityEvent(source=frame.source,
                                  state=VADState.SILENCE, confidence=0.8)

    def segment(self, pcm: bytes, source: str = "") -> list[AudioSegment]:
        """Delegate to the proven pure segmenter, then bound + type it."""
        if len(pcm) > MAX_SEGMENT_BYTES:
            raise AudioError("pcm exceeds segment bound")
        raw = self._vad.segment(pcm)
        frame_bytes = self._vad.frame_bytes
        out: list[AudioSegment] = []
        for start, end in raw.get("segments", [])[:8]:
            out.append(AudioSegment(
                source=source or "energy-vad",
                start_timestamp=0.0,
                end_timestamp=round((end - start) * 0.02, 2),
                duration_s=round((end - start) * 0.02, 2),
                sequence_start=start, sequence_end=end,
                status=SegmentStatus.COMPLETE,
                provenance={"frames": end - start,
                            "frame_bytes": frame_bytes}))
        return out

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": True,
                "transitions": self.transitions}


class FakeVAD(VoiceActivityDetector):
    """Deterministic scripted VAD for tests. No audio needed."""

    name = "fake"

    def __init__(self, pattern: list[str] | None = None) -> None:
        self._pattern = list(pattern or ["silence", "speech_start",
                                         "speech", "speech_end"])
        self._index = 0
        self.calls = 0

    def process_frame(self, frame: AudioFrame,
                      energy: float = 0.0) -> VoiceActivityEvent:
        self.calls += 1
        state = self._pattern[self._index % len(self._pattern)]
        self._index += 1
        return VoiceActivityEvent(source=frame.source,
                                  state=VADState(state), confidence=0.9)

    def segment(self, pcm: bytes, source: str = "") -> list[AudioSegment]:
        if not pcm:
            return []
        return [AudioSegment(
            source=source or "fake-vad", duration_s=1.0,
            sequence_start=0, sequence_end=10,
            status=SegmentStatus.COMPLETE)]


__all__ = [
    "EnergyVADAdapter",
    "FakeVAD",
    "VoiceActivityDetector",
]
