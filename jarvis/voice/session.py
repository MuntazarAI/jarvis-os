"""Voice session + correlation model (5.1).

A VoiceSession groups one spoken interaction end-to-end without
duplicating existing session infrastructure: session/audio/
transcript/cognition/response/tts ids chain together so a full turn
can be reconstructed from metadata alone (no raw audio stored).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class VoiceSession:
    session_id: str = field(default_factory=lambda: _new_id("voice"))
    started_at: float = field(default_factory=time.time)
    source: str = "microphone"
    wake_state: str = "idle"
    interaction_count: int = 0
    privacy_mode: str = "transient"
    audio_id: str = ""
    transcript_id: str = ""
    cognition_id: str = ""
    response_id: str = ""
    tts_id: str = ""

    def next_turn(self, *, audio_id: str = "",
                  transcript_id: str = "") -> dict[str, str]:
        self.interaction_count += 1
        self.audio_id = audio_id or _new_id("audio")
        self.transcript_id = transcript_id or _new_id("stt")
        self.cognition_id = _new_id("cog")
        self.response_id = _new_id("resp")
        self.tts_id = _new_id("tts")
        return {"voice_session_id": self.session_id,
                "audio_id": self.audio_id,
                "transcript_id": self.transcript_id,
                "cognition_id": self.cognition_id,
                "response_id": self.response_id,
                "tts_id": self.tts_id}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["VoiceSession"]
