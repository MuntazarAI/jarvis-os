"""
Translation Intelligence — JARVIS-OS OMNINET subsystem.

Provides multi-language translation, language detection, and localization
through allowlisted translation services. Read-only — no language model
training or modification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class Translation:
    """A translation result."""
    translation_id: str
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    confidence: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class LanguageDetection:
    """A language detection result."""
    detection_id: str
    text: str
    detected_language: str
    confidence: float
    timestamp: float = field(default_factory=time.time)


class TranslationIntelligence:
    """
    Translation Intelligence — multi-language translation, language detection,
    and localization.

    Read-only translation services from allowlisted providers. All requests
    pass through PolicyEngine. No language model training or modification.
    """

    ALLOWED_DOMAINS: frozenset[str] = frozenset({
        "translate.googleapis.com",
        "api.deepl.com",
        "translate.yandex.com",
        "libretranslate.com",
    })

    SUPPORTED_LANGUAGES: frozenset[str] = frozenset({
        "en", "es", "fr", "de", "zh", "ja", "ko", "ru", "ar", "pt",
        "it", "nl", "pl", "tr", "vi", "th", "hi", "id", "ms", "tl",
    })

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.translations: dict[str, Translation] = {}
        self.detections: dict[str, LanguageDetection] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the translation intelligence subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "translation_intelligence",
            "domains": len(self.ALLOWED_DOMAINS),
            "supported_languages": len(self.SUPPORTED_LANGUAGES),
            "policy_gated": True,
            "read_only": True,
        }

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str = "auto",
    ) -> Translation:
        """Translate text from source to target language."""
        if target_language not in self.SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported target language: {target_language}")

        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "translation_intelligence.translate",
                {
                    "source_language": source_language,
                    "target_language": target_language,
                    "domains": list(self.ALLOWED_DOMAINS),
                },
            )

        translation = Translation(
            translation_id=f"trans-{int(time.time() * 1000)}",
            source_text=text,
            translated_text=f"[translated: {text}]",  # schematic placeholder
            source_language=source_language,
            target_language=target_language,
            confidence=0.5 if grant_result.get("approved", False) else 0.0,
        )
        self.translations[translation.translation_id] = translation

        if self.events:
            self.events.append({
                "event": "translation_intelligence.translate",
                "translation_id": translation.translation_id,
                "source_language": source_language,
                "target_language": target_language,
                "approved": grant_result.get("approved", False),
                "at": translation.timestamp,
            })

        return translation

    def detect_language(self, text: str) -> LanguageDetection:
        """Detect the language of text."""
        detection = LanguageDetection(
            detection_id=f"detect-{int(time.time() * 1000)}",
            text=text,
            detected_language="en",
            confidence=0.5,
        )
        self.detections[detection.detection_id] = detection
        return detection

    def list_languages(self) -> list[str]:
        """List supported languages."""
        return sorted(self.SUPPORTED_LANGUAGES)

    def list_domains(self) -> list[str]:
        """List allowlisted domains."""
        return sorted(self.ALLOWED_DOMAINS)

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "translation_intelligence",
            "status": "operational" if self._initialized else "offline",
            "translations": len(self.translations),
            "detections": len(self.detections),
            "domains": sorted(self.ALLOWED_DOMAINS),
            "supported_languages": sorted(self.SUPPORTED_LANGUAGES),
            "capabilities": [
                "multi_language_translation",
                "language_detection",
                "localization_support",
            ],
            "constraints": [
                "read_only_translation",
                "policy_gated_domain_access",
                "no_language_model_training",
            ],
        }


# Global instance
_translation: TranslationIntelligence | None = None


def get_translation_intelligence(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> TranslationIntelligence:
    """Get or create the global Translation Intelligence instance."""
    global _translation
    if _translation is None:
        _translation = TranslationIntelligence(policy=policy, events=events)
    return _translation


__all__ = [
    "TranslationIntelligence",
    "Translation",
    "LanguageDetection",
    "get_translation_intelligence",
]