"""JARVIS voice identity profile (5.1).

The JARVIS voice is a Chatterbox reference voice selected as the
assistant identity — not an official character voice. Profile keeps
name/provider/reference/language/style plus conservative generation
defaults. Reference path is always configurable, never hard-coded.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

REFERENCE_FILENAME = "male_old_movie.flac"
REFERENCE_URL = ("https://storage.googleapis.com/chatterbox-demo-samples/"
                 "prompts/male_old_movie.flac")
DEFAULT_REFERENCE = "~/.config/jarvis/voices/male_old_movie.flac"


def default_reference_path() -> Path:
    return Path(os.path.expanduser(DEFAULT_REFERENCE))


@dataclass
class VoiceProfile:
    name: str = "jarvis"
    provider: str = "chatterbox"
    reference_audio: str = DEFAULT_REFERENCE
    language: str = "en"
    style: str = "calm"
    emotion: str = "restrained"
    personality: list[str] = field(default_factory=lambda: [
        "calm", "precise", "mature", "composed", "restrained",
        "intelligent", "professional",
    ])
    output_format: str = "wav"
    sample_rate: int = 24000
    output_device: str = "default"
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

    def reference_path(self) -> Path:
        raw = os.environ.get("JARVIS_VOICE_REFERENCE",
                             self.reference_audio)
        return Path(os.path.expanduser(raw))

    def to_dict(self) -> dict:
        return asdict(self)


OVERRIDE_FILENAME = "voice-profile.json"
OVERRIDE_KEYS = ("style", "emotion", "language", "exaggeration",
                 "temperature")


def overrides_path(home: str | Path = "") -> Path:
    base = Path(os.path.expanduser(str(home))) if home else \
        Path.home() / ".jarvis-os"
    return base / OVERRIDE_FILENAME


def load_overrides(home: str | Path = "") -> dict:
    """User speaking-style overrides. Missing/corrupt → {} (defaults)."""
    import json
    try:
        raw = json.loads(overrides_path(home).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for key in OVERRIDE_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value[:40]:
            clean[key] = value[:40]
        elif isinstance(value, (int, float)) and key in (
                "exaggeration", "temperature"):
            clean[key] = max(0.0, min(2.0, float(value)))
    return clean


def save_overrides(home: str | Path, updates: dict) -> dict:
    """Persist style overrides. Unknown keys refused, never merged blindly."""
    import json
    current = load_overrides(home)
    for key, value in (updates or {}).items():
        if key not in OVERRIDE_KEYS:
            raise ValueError(f"unknown profile key: {key}")
        current[key] = value
    path = overrides_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, sort_keys=True),
                    encoding="utf-8")
    return load_overrides(home)


def effective_style(home: str | Path = "", explicit: str = "") -> str:
    """Explicit flag wins, then saved profile, then normal."""
    if explicit in STYLE_GUIDANCE:
        return explicit
    saved = load_overrides(home).get("style", "")
    return saved if saved in STYLE_GUIDANCE else "normal"


def jarvis_profile(overrides: dict | None = None) -> VoiceProfile:
    profile = VoiceProfile()
    for key, value in (overrides or {}).items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    return profile


# Rendering policy: concise/calm/clear; uncertainty stays uncertain.
STYLE_GUIDANCE = {
    "normal": "concise, calm, clear, measured, natural pauses",
    "warning": "slightly firmer, still calm",
    "error": "clear, direct, non-panicked",
    "confirmation": "brief, confident, factual",
    "uncertain": "explicitly preserve uncertainty",
}


def render_style(text: str, kind: str = "normal") -> str:
    """Apply JARVIS speaking style without changing semantics.

    Only trims filler/whitespace; never rewords claims, never upgrades
    uncertainty to certainty.
    """
    _ = STYLE_GUIDANCE.get(kind, "")
    cleaned = " ".join(str(text or "").split())
    return cleaned[:2000]


__all__ = ["VoiceProfile", "jarvis_profile", "render_style",
           "REFERENCE_FILENAME", "REFERENCE_URL", "DEFAULT_REFERENCE",
           "default_reference_path", "STYLE_GUIDANCE"]
