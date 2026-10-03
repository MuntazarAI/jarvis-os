"""Audio domain contracts for 5.1 voice intelligence (5.1).

Typed, bounded, validated audio structures: frames, segments, VAD
events, transcripts, sources, and metadata. No capture, no inference,
no execution here — only shapes and bounds. Fail closed throughout.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# -- explicit bounds (not magic numbers) ---------------------------------------

SAMPLE_RATES = (8000, 16000, 22050, 44100, 48000)
CHANNELS = (1, 2)
SAMPLE_FORMATS = ("pcm_s16le",)
MAX_FRAME_BYTES = 256 * 1024
MAX_FRAME_DURATION_S = 10.0
MAX_SEGMENT_DURATION_S = 60.0
MAX_SEGMENT_BYTES = 4 * 1024 * 1024
MAX_BUFFER_FRAMES = 300
MAX_TRANSCRIPT_CHARS = 2000
MAX_SEGMENTS_PER_UTTERANCE = 8
SCHEMA_VERSION = 1


class VADState(str, Enum):
    SILENCE = "silence"
    SPEECH_START = "speech_start"
    SPEECH = "speech"
    SPEECH_END = "speech_end"
    UNKNOWN = "unknown"


class SegmentStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ERROR = "error"


class AudioError(ValueError):
    """Malformed audio structure or bound violation (fail closed)."""


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class AudioFrame:
    frame_id: str = field(default_factory=lambda: _new_id("frm"))
    timestamp: float = field(default_factory=_utcnow)
    source: str = ""
    device_id: str = ""
    sequence: int = 0
    sample_rate: int = 16000
    channels: int = 1
    sample_format: str = "pcm_s16le"
    duration_s: float = 0.0
    payload_bytes: int = 0
    provenance: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source:
            raise AudioError("audio frame source is required")
        if self.sample_rate not in SAMPLE_RATES:
            raise AudioError(f"invalid sample rate: {self.sample_rate!r}")
        if self.channels not in CHANNELS:
            raise AudioError(f"invalid channels: {self.channels!r}")
        if self.sample_format not in SAMPLE_FORMATS:
            raise AudioError(
                f"invalid sample format: {self.sample_format!r}")
        if not isinstance(self.timestamp, (int, float)) \
                or self.timestamp <= 0:
            raise AudioError(f"malformed timestamp: {self.timestamp!r}")
        if self.sequence < 0:
            raise AudioError("sequence must be >= 0")
        if not 0.0 < self.duration_s <= MAX_FRAME_DURATION_S:
            raise AudioError(
                f"frame duration out of bounds: {self.duration_s!r}")
        if not 0 <= self.payload_bytes <= MAX_FRAME_BYTES:
            raise AudioError(
                f"frame payload out of bounds: {self.payload_bytes!r}")
        expected = int(self.sample_rate * self.channels * 2
                       * self.duration_s)
        if abs(self.payload_bytes - expected) > max(64, expected // 10):
            raise AudioError("payload bytes inconsistent with audio format")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AudioSegment:
    segment_id: str = field(default_factory=lambda: _new_id("seg"))
    source: str = ""
    device_id: str = ""
    start_timestamp: float = 0.0
    end_timestamp: float = 0.0
    duration_s: float = 0.0
    sequence_start: int = 0
    sequence_end: int = 0
    status: SegmentStatus = SegmentStatus.UNKNOWN
    provenance: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                self.status = SegmentStatus(self.status)
            except ValueError:
                raise AudioError(f"invalid status: {self.status!r}")
        if not self.source:
            raise AudioError("segment source is required")
        if self.duration_s < 0 or self.duration_s > MAX_SEGMENT_DURATION_S:
            raise AudioError(
                f"segment duration out of bounds: {self.duration_s!r}")
        if self.sequence_end < self.sequence_start:
            raise AudioError("segment sequence inverted")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class VoiceActivityEvent:
    event_id: str = field(default_factory=lambda: _new_id("vad"))
    timestamp: float = field(default_factory=_utcnow)
    source: str = ""
    state: VADState = VADState.UNKNOWN
    confidence: float = 0.5
    segment_id: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.state, str):
            try:
                self.state = VADState(self.state)
            except ValueError:
                raise AudioError(f"invalid VAD state: {self.state!r}")
        if not self.source:
            raise AudioError("VAD event source is required")
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            raise AudioError("invalid VAD confidence")
        if not 0.0 <= confidence <= 1.0:
            raise AudioError("VAD confidence out of range")
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass
class AudioSource:
    source_id: str = ""
    kind: str = "microphone"  # microphone|file|fixture|pi
    device_id: str = ""
    sample_rate: int = 16000
    channels: int = 1
    available: bool = True
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.source_id:
            raise AudioError("audio source needs an id")
        if self.kind not in ("microphone", "file", "fixture", "pi"):
            raise AudioError(f"invalid source kind: {self.kind!r}")
        if self.sample_rate not in SAMPLE_RATES:
            raise AudioError(f"invalid sample rate: {self.sample_rate!r}")
        if self.channels not in CHANNELS:
            raise AudioError(f"invalid channels: {self.channels!r}")


@dataclass
class AudioMetadata:
    duration_s: float = 0.0
    size_bytes: int = 0
    segments: int = 0
    speech_ms: int = 0


class AudioBuffer:
    """Bounded frame buffer. Drops oldest on overflow (counts it)."""

    def __init__(self, max_frames: int = MAX_BUFFER_FRAMES) -> None:
        self.max_frames = max(1, max_frames)
        self._frames: deque[AudioFrame] = deque()
        self.dropped = 0
        self.expected_sequence = 0

    def append(self, frame: AudioFrame) -> bool:
        """Append if sequence is sane. Returns accepted or not."""
        if not isinstance(frame, AudioFrame):
            return False
        if frame.sequence < self.expected_sequence:
            return False  # stale/duplicate: refuse, do not reorder
        self._frames.append(frame)
        self.expected_sequence = frame.sequence + 1
        while len(self._frames) > self.max_frames:
            self._frames.popleft()
            self.dropped += 1
        return True

    def frames(self) -> list[AudioFrame]:
        return list(self._frames)

    def clear(self) -> int:
        count = len(self._frames)
        self._frames.clear()
        return count

    def __len__(self) -> int:
        return len(self._frames)


__all__ = [
    "AudioBuffer",
    "AudioError",
    "AudioFrame",
    "AudioMetadata",
    "AudioSegment",
    "AudioSource",
    "VoiceActivityEvent",
]
