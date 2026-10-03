"""Multimodal perception for JARVIS (4.3).

Read-only observation providers (screen, camera, image, file),
OCR/object abstractions, and the typed observation contract.
Perception never acts: no sockets, no commands, no loops.
"""

from .contract import (
    MAX_DIMENSION_PX,
    MAX_FILE_BYTES,
    MAX_FRAME_BYTES,
    MAX_METADATA_KEYS,
    MAX_NESTING_DEPTH,
    MAX_OBJECTS,
    MAX_OBSERVATION_BYTES,
    MAX_OCR_CHARS,
    MAX_TEXT_CHARS,
    CameraPayload,
    DetectedObject,
    FilePayload,
    ImagePayload,
    Modality,
    Observation,
    PerceptionError,
    PrivacyClass,
    ScreenPayload,
    summarize_text,
    validate_confidence,
    validate_object,
)
from .objects import FakeObjects, ObjectPerceptionProvider, UnavailableObjects
from .ocr import FakeOCR, OCRProvider, TesseractOCR, UnavailableOCR
from .providers import (
    CameraProvider,
    FileProvider,
    ImageProvider,
    PerceptionProvider,
    ScreenProvider,
)

__all__ = [
    "CameraProvider",
    "DetectedObject",
    "FakeObjects",
    "FakeOCR",
    "FilePayload",
    "FileProvider",
    "ImagePayload",
    "ImageProvider",
    "Modality",
    "ObjectPerceptionProvider",
    "Observation",
    "OCRProvider",
    "PerceptionError",
    "PerceptionProvider",
    "PrivacyClass",
    "ScreenPayload",
    "ScreenProvider",
    "TesseractOCR",
    "UnavailableOCR",
    "UnavailableObjects",
    "validate_confidence",
    "validate_object",
]
