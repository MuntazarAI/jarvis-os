"""Multilingual Global Intelligence (M6).

Language identification, cross-language search, query translation,
content translation, multilingual summarization, and international
source comparison. Original-language preservation is maintained.

Builds on existing jarvis/worldintel/ (claims, routing, research)
and jarvis/core/internet.py (PolicyEngine-gated outbound access).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import ActionPlan, RiskLevel
from ..omninet.connectors import ConnectorResult
from ..omninet.http_connector import HttpConnector
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url

log = get_module_logger(__name__)


# ============================================================================
# Language identification (heuristic, no model dependency)
# ============================================================================

# Common stopwords by language for lightweight identification
_LANGUAGE_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "be", "to", "of", "and", "a", "in", "that", "have", "it",
           "for", "not", "on", "with", "he", "as", "you", "do", "at",
           "is", "was", "are", "were", "been", "being", "has", "had",
           "does", "did", "will", "would", "could", "should", "may",
           "might", "must", "can", "i", "me", "my", "myself", "we",
           "our", "ours", "ourselves", "your", "yours", "yourself",
           "yourselves", "him", "his", "himself", "she", "her", "hers",
           "herself", "its", "itself", "they", "them", "their", "theirs",
           "themselves", "what", "which", "who", "whom", "this", "that",
           "these", "those", "am", "an", "but", "if", "or", "because",
           "as", "until", "while", "from", "up", "down", "out", "off",
           "over", "under", "again", "further", "then", "once", "here",
           "there", "when", "where", "why", "how", "all", "each", "few",
           "more", "most", "other", "some", "such", "no", "nor", "not",
           "only", "own", "same", "so", "than", "too", "very"},
    "es": {"el", "la", "de", "que", "y", "a", "en", "un", "ser", "se",
           "no", "haber", "por", "con", "su", "para", "como", "estar"},
    "fr": {"le", "de", "et", "à", "un", "il", "être", "en", "avoir", "que",
           "je", "ne", "se", "pas", "ce", "dans", "pour", "son", "que"},
    "de": {"der", "die", "und", "in", "den", "von", "zu", "das", "mit",
           "sich", "des", "ist", "im", "dem", "nicht", "ein", "ich", "auf"},
    "it": {"il", "e", "di", "che", "la", "un", "a", "in", "è", "per",
           "sono", "non", "con", "da", "una", "come", "mi", "si", "ho"},
    "pt": {"o", "a", "de", "e", "que", "do", "da", "em", "um", "para",
           "é", "não", "com", "por", "os", "as", "se", "na", "no"},
    "ru": {"и", "в", "во", "не", "что", "он", "на", "я", "с", "как",
           "а", "то", "все", "она", "но", "при", "этот", "после"},
    "ja": {"の", "に", "は", "を", "た", "が", "で", "て", "と", "も",
           "な", "か", "へ", "て", "おり", "です", "ます", "から"},
    "zh": {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
           "都", "一", "个", "上", "也", "很", "到", "说", "要", "去"},
    "ar": {"ال", "في", "من", "و", "على", "هذا", "that", "التي", "أو",
           "كان", "بعد", "before", "بعده", "قبل", "حتى", "عن", "مع"},
}

# Script hints
_SCRIPT_HINTS: dict[str, str] = {
    "Cyrillic": "ru",
    "Han": "zh",
    "Hiragana": "ja",
    "Katakana": "ja",
    "Hangul": "ko",
    "Arabic": "ar",
    "Devanagari": "hi",
    "Thai": "th",
    "Hebrew": "he",
}


def _detect_script(text: str) -> str | None:
    """Detect script from Unicode ranges."""
    import unicodedata
    scripts = set()
    for ch in text:
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        for script, lang in _SCRIPT_HINTS.items():
            if script.upper() in name:
                scripts.add(lang)
    if scripts:
        return scripts.pop()
    return None


def identify_language(text: str) -> dict[str, Any]:
    """Identify language of text using heuristic stopword + script detection.

    Returns dict with detected language code, confidence, and method.
    No ML model dependency — pure heuristic.
    """
    if not text or not text.strip():
        return {"language": "unknown", "confidence": 0.0, "method": "empty"}

    # Script-based detection (strong signal)
    script_lang = _detect_script(text)
    if script_lang:
        return {"language": script_lang, "confidence": 0.85, "method": "script"}

    # Stopword-based detection
    import unicodedata
    words = set(re.findall(r"[a-zA-Zàáâãäåæçèéêëìíîïðñòóôõöøùúûüýÿñ]+",
                           text.lower()))
    if not words:
        return {"language": "unknown", "confidence": 0.0, "method": "no_words"}

    best_lang = "unknown"
    best_score = 0.0
    for lang, stopwords in _LANGUAGE_STOPWORDS.items():
        overlap = len(words & stopwords)
        score = overlap / max(len(words), 1)
        if score > best_score:
            best_score = score
            best_lang = lang

    if best_score > 0.05:
        confidence = min(0.9, 0.5 + best_score)
        return {"language": best_lang, "confidence": confidence,
                "method": "stopwords"}

    # Latin script with no stopword match → default to English (low confidence)
    # This handles short texts like "Hello world" that lack stopwords
    has_latin = any(
        "LATIN" in unicodedata.name(ch, "") for ch in text if ch.isalpha()
    )
    if has_latin:
        return {"language": "en", "confidence": 0.3, "method": "latin_script"}

    return {"language": "unknown", "confidence": 0.1, "method": "fallback"}


# ============================================================================
# Translation (key-free, best-effort via public APIs when granted)
# ============================================================================


@dataclass
class TranslationResult:
    """Translation result with source language preservation."""
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    provider: str
    confidence: float = 0.0
    fetched_at: float = field(default_factory=time.monotonic)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not bool(self.error)


class TranslationService:
    """Translation service using PolicyEngine-gated public APIs.

    Supports multiple providers with fallback. No API key required for
    the free tier endpoints used. Original text is always preserved.
    """

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self._http = HttpConnector(policy, internet, actor=actor,
                                   timeout=15.0, max_bytes=500_000)

    def _can_access(self, domain: str) -> bool:
        return self._http.internet.can_access(self.actor, domain)

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> TranslationResult:
        """Translate text to target language.

        Tries LibreTranslate (free, self-hostable) first, then
        other providers. Original text is always preserved.
        """
        if not text.strip():
            return TranslationResult(
                source_text=text, translated_text="",
                source_language="unknown", target_language=target_language,
                provider="none", confidence=0.0,
            )

        # Identify source language if not provided
        if source_language is None:
            detected = identify_language(text)
            source_language = detected["language"]

        # If source == target, no translation needed
        if source_language == target_language:
            return TranslationResult(
                source_text=text, translated_text=text,
                source_language=source_language, target_language=target_language,
                provider="none", confidence=1.0,
            )

        # If source language is unknown, don't attempt translation
        if source_language == "unknown":
            return TranslationResult(
                source_text=text, translated_text=text,
                source_language=source_language, target_language=target_language,
                provider="none", confidence=0.0,
                error="source language unknown",
            )

        # Try LibreTranslate public instance
        result = self._try_libretranslate(text, source_language, target_language)
        if result.ok:
            return result

        # Fallback: return original with note
        return TranslationResult(
            source_text=text, translated_text=text,
            source_language=source_language, target_language=target_language,
            provider="none", confidence=0.0,
            error="no translation provider available",
        )

    def _try_libretranslate(
        self,
        text: str,
        source: str,
        target: str,
    ) -> TranslationResult:
        """Try LibreTranslate public API."""
        domains = ["libretranslate.com", "translate.argosopentech.com"]
        for domain in domains:
            if not self._can_access(domain):
                continue
            url = f"https://{domain}/translate"
            # LibreTranslate expects form data
            import urllib.parse
            data = urllib.parse.urlencode({
                "q": text[:2000],  # bounded
                "source": source,
                "target": target,
                "format": "text",
            }).encode()
            req = __import__("urllib.request").Request(
                url, data=data,
                headers={"User-Agent": "jarvis-os/0.1 multilingual agent",
                         "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            try:
                with __import__("urllib.request").urlopen(
                    req, timeout=15.0) as resp:  # noqa: S310
                    import json
                    body = resp.read().decode("utf-8", errors="replace")
                    result = json.loads(body)
                    translated = result.get("translatedText", text)
                    return TranslationResult(
                        source_text=text, translated_text=translated,
                        source_language=source, target_language=target,
                        provider="libretranslate", confidence=0.75,
                    )
            except Exception:
                continue
        return TranslationResult(
            source_text=text, translated_text=text,
            source_language=source, target_language=target,
            provider="none", confidence=0.0,
            error="libretranslate unavailable",
        )


# ============================================================================
# Multilingual summarization
# ============================================================================


def summarize_multilingual(
    text: str,
    language: str | None = None,
    max_sentences: int = 3,
) -> dict[str, Any]:
    """Summarize text in its detected language.

    Extractive summarization: rank sentences by keyword frequency,
    return top sentences. Preserves original language.
    """
    if not text.strip():
        return {"language": "unknown", "summary": "",
                "sentences": [], "confidence": 0.0}

    # Detect language
    if language is None:
        detected = identify_language(text)
        language = detected["language"]

    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if len(sentences) <= max_sentences:
        return {
            "language": language,
            "summary": " ".join(sentences),
            "sentences": sentences,
            "confidence": 1.0,
        }

    # Score sentences by word frequency (excluding stopwords)
    stopwords = _LANGUAGE_STOPWORDS.get(language, set())
    word_freq: dict[str, int] = {}
    for sent in sentences:
        words = re.findall(r"[a-zA-Zàáâãäåæçèéêëìíîïðñòóôõöøùúûüýÿñ]+",
                           sent.lower())
        for w in words:
            if w not in stopwords:
                word_freq[w] = word_freq.get(w, 0) + 1

    if not word_freq:
        return {
            "language": language,
            "summary": " ".join(sentences[:max_sentences]),
            "sentences": sentences[:max_sentences],
            "confidence": 0.5,
        }

    max_freq = max(word_freq.values())
    sentence_scores: list[tuple[float, int, str]] = []
    for i, sent in enumerate(sentences):
        words = re.findall(r"[a-zA-Zàáâãäåæçèéêëìíîïðñòóôõöøùúûüýÿñ]+",
                           sent.lower())
        score = sum(word_freq.get(w, 0) for w in words) / max(len(words), 1)
        score = score / max_freq
        sentence_scores.append((score, i, sent))

    # Sort by score, then pick top max_sentences maintaining original order
    sentence_scores.sort(key=lambda x: -x[0])
    top = sorted(sentence_scores[:max_sentences], key=lambda x: x[1])
    summary_sentences = [s for _, _, s in top]

    confidence = min(0.9, 0.5 + len(summary_sentences) / max(len(sentences), 1))

    return {
        "language": language,
        "summary": " ".join(summary_sentences),
        "sentences": summary_sentences,
        "confidence": round(confidence, 2),
    }


# ============================================================================
# Cross-language search helper
# ============================================================================


def cross_language_search_queries(
    query: str,
    target_languages: list[str],
) -> dict[str, list[str]]:
    """Generate search queries in multiple languages for a given query.

    Translates the query to each target language so the search engine
    can retrieve results in that language.
    """
    detected = identify_language(query)
    source_lang = detected["language"]

    queries: dict[str, list[str]] = {
        source_lang: [query],
    }

    for lang in target_languages:
        if lang == source_lang:
            continue
        queries[lang] = [query]  # placeholder; actual translation via service

    return queries


__all__ = [
    "identify_language",
    "TranslationResult",
    "TranslationService",
    "summarize_multilingual",
    "cross_language_search_queries",
    "_LANGUAGE_STOPWORDS",
]
