"""Perception contract for 4.3 multimodal perception (4.3).

Typed, bounded, provenance-aware observations. Every observation
carries: id, timestamp, source, device, modality, structured payload,
confidence, provenance, privacy class, and retention metadata.

Raw media is NEVER in the payload — only references (paths), hashes,
dimensions, and extracted bounded content. Validation rejects anything
malformed, oversized, secret-bearing, or unbounded (fail closed).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# -- explicit bounds (not magic numbers) ---------------------------------------

MAX_OCR_CHARS = 4000
MAX_OBJECTS = 50
MAX_METADATA_KEYS = 30
MAX_TEXT_CHARS = 2000
MAX_NESTING_DEPTH = 4
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_DIMENSION_PX = 16384
MAX_OBSERVATION_BYTES = 64 * 1024


class Modality(str, Enum):
    SCREEN = "screen"
    CAMERA = "camera"
    FILE = "file"
    IMAGE = "image"
    DOCUMENT = "document"
    SENSOR = "sensor"


class PrivacyClass(str, Enum):
    """Retention boundary. PUBLIC/LOCAL may persist; SENSITIVE stays in
    working context; PRIVATE is ephemeral (never persisted anywhere)."""
    PUBLIC = "public"
    LOCAL = "local"
    SENSITIVE = "sensitive"
    PRIVATE = "private"


class PerceptionError(ValueError):
    """Malformed observation or provider misuse (fail closed)."""


_SECRET_KEY_HINTS = (
    "password", "passwd", "secret", "token", "credential", "api_key",
    "apikey", "private_key", "privatekey", "auth", "passphrase",
    "seed_phrase", "session", "cookie", "ssn",
)


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise PerceptionError(
            f"payload exceeds nesting depth {MAX_NESTING_DEPTH}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise PerceptionError(f"invalid metadata key: {key!r}")
            _check_depth(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        if len(value) > MAX_OBJECTS:
            raise PerceptionError(
                f"list exceeds {MAX_OBJECTS} items")
        for item in value:
            _check_depth(item, depth + 1)
    elif isinstance(value, str) and len(value) > MAX_TEXT_CHARS:
        raise PerceptionError(
            f"text exceeds {MAX_TEXT_CHARS} chars")


def _check_no_secrets(mapping: dict[str, Any], where: str) -> None:
    for key in mapping:
        lowered = str(key).lower()
        if any(hint in lowered for hint in _SECRET_KEY_HINTS):
            raise PerceptionError(
                f"{where} must not contain secret material "
                f"(key {key!r} refused)")


def validate_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise PerceptionError(f"invalid confidence: {value!r}")
    if not 0.0 <= confidence <= 1.0:
        raise PerceptionError(f"confidence out of range: {value!r}")
    return confidence


# -- payload types ---------------------------------------------------------------


@dataclass
class ScreenPayload:
    visible_text: str = ""
    ui_elements: list[dict[str, Any]] = field(default_factory=list)
    active_app: str = ""
    window_title: str = ""
    width_px: int = 0
    height_px: int = 0
    ocr_confidence: float = 0.0


@dataclass
class CameraPayload:
    objects: list[dict[str, Any]] = field(default_factory=list)
    scene: str = ""
    frame_ref: str = ""  # reference only, never bytes
    width_px: int = 0
    height_px: int = 0


@dataclass
class FilePayload:
    path: str = ""
    file_type: str = ""
    size_bytes: int = 0
    content_hash: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImagePayload:
    path: str = ""
    width_px: int = 0
    height_px: int = 0
    objects: list[dict[str, Any]] = field(default_factory=list)
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    content_hash: str = ""


@dataclass
class DetectedObject:
    label: str
    confidence: float = 0.5
    bbox: list[float] = field(default_factory=list)  # [x,y,w,h] 0..1
    track_id: str = ""
    anonymous: bool = True  # never identity; persons stay anonymous


# -- observation -------------------------------------------------------------------


@dataclass
class Observation:
    observation_id: str = field(
        default_factory=lambda: _new_id("obs"))
    timestamp: float = field(default_factory=_utcnow)
    source: str = ""
    source_device: str = ""
    modality: Modality = Modality.SENSOR
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)
    privacy_class: PrivacyClass = PrivacyClass.LOCAL
    ttl_s: float = 0.0  # 0 = governed by privacy default, not forever
    correlation_id: str = ""
    cycle_id: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.modality, str):
            try:
                self.modality = Modality(self.modality)
            except ValueError:
                raise PerceptionError(
                    f"invalid modality: {self.modality!r}")
        if not self.source:
            raise PerceptionError("observation source is required")
        if not isinstance(self.timestamp, (int, float)) \
                or self.timestamp <= 0:
            raise PerceptionError(
                f"malformed timestamp: {self.timestamp!r}")
        self.confidence = validate_confidence(self.confidence)
        if isinstance(self.privacy_class, str):
            try:
                self.privacy_class = PrivacyClass(self.privacy_class)
            except ValueError:
                raise PerceptionError(
                    f"invalid privacy class: {self.privacy_class!r}")
        if not isinstance(self.payload, dict):
            raise PerceptionError("observation payload must be an object")
        if not isinstance(self.provenance, dict):
            raise PerceptionError("provenance must be an object")
        _check_no_secrets(self.payload, "observation payload")
        _check_no_secrets(self.provenance, "observation provenance")
        _check_depth(self.payload)
        _check_depth(self.provenance)
        try:
            size = len(str(self.payload).encode("utf-8"))
        except Exception:
            raise PerceptionError("payload is not serializable")
        if size > MAX_OBSERVATION_BYTES:
            raise PerceptionError(
                f"observation exceeds {MAX_OBSERVATION_BYTES} bytes")
        if not self.correlation_id:
            self.correlation_id = self.observation_id

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["modality"] = self.modality.value
        data["privacy_class"] = self.privacy_class.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Observation":
        if not isinstance(data, dict):
            raise PerceptionError("observation must be an object")
        known = set(cls.__dataclass_fields__)
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    def fingerprint(self) -> str:
        """Stable hash for change detection (payload + modality)."""
        canonical = json.dumps(
            {"modality": self.modality.value, "payload": self.payload},
            sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_object(item: dict[str, Any]) -> dict[str, Any]:
    """Validate one detected object. Persons stay anonymous, always."""
    if not isinstance(item, dict):
        raise PerceptionError("detected object must be an object")
    label = str(item.get("label", ""))[:80]
    if not label:
        raise PerceptionError("detected object needs a label")
    if re.search(r"\b(face|person)\b.*\b(name|identity|id)\b", label,
                 re.IGNORECASE):
        raise PerceptionError(
            "identity recognition is not permitted (anonymous only)")
    confidence = validate_confidence(item.get("confidence", 0.5))
    bbox = list(item.get("bbox", []) or [])
    if bbox:
        if len(bbox) != 4 or any(not isinstance(v, (int, float))
                                 or not 0.0 <= v <= 1.0 for v in bbox):
            raise PerceptionError(f"invalid bbox: {bbox!r}")
    _check_depth(item)
    return {"label": label, "confidence": confidence, "bbox": bbox,
            "track_id": str(item.get("track_id", ""))[:32],
            "anonymous": True}


def summarize_text(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(text, str):
        raise PerceptionError("text must be a string")
    return text[:limit]


_SECRET_SPAN_RES = (
    re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----.*?-----END "
               r"(?:RSA )?PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bxox[bap]-[A-Za-z0-9\-]{8,}\b"),
)


def redact_secret_spans(text: str) -> tuple[str, list[str]]:
    """Redact high-precision credential spans (PEM blocks, AWS keys,
    GitHub/Slack tokens). Returns (clean_text, matched_kinds) — kinds
    only, never values. Ordinary prose (including the word 'password'
    without a credential shape) passes through untouched; that case
    stays a documented limitation of key-based scrubbing."""
    if not isinstance(text, str):
        return "", []
    kinds: list[str] = []
    clean = text
    for pattern in _SECRET_SPAN_RES:
        if pattern.search(clean):
            kinds.append(pattern.pattern[:24])
            clean = pattern.sub("[redacted credentials]", clean)
    if len(clean) > MAX_TEXT_CHARS:
        clean = clean[:MAX_TEXT_CHARS]
    return clean, kinds


__all__ = [
    "Observation",
    "Modality",
    "PrivacyClass",
    "PerceptionError",
    "ScreenPayload",
    "CameraPayload",
    "FilePayload",
    "ImagePayload",
    "DetectedObject",
    "validate_object",
    "validate_confidence",
    "summarize_text",
    "redact_secret_spans",
    "MAX_OCR_CHARS",
    "MAX_OBJECTS",
    "MAX_METADATA_KEYS",
    "MAX_TEXT_CHARS",
    "MAX_NESTING_DEPTH",
    "MAX_FRAME_BYTES",
    "MAX_FILE_BYTES",
    "MAX_DIMENSION_PX",
    "MAX_OBSERVATION_BYTES",
]
