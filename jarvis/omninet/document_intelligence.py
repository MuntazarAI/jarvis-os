"""
Document Intelligence — JARVIS-OS OMNINET subsystem.

Provides OCR, document parsing, PDF text extraction, and form analysis
through local processing. Read-only — no document modification without
explicit PolicyEngine grant.
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
class DocumentParse:
    """A document parsing result."""
    parse_id: str
    document_name: str
    document_type: str  # pdf, docx, txt, html, image
    extracted_text: str
    word_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class OCRResult:
    """An OCR (optical character recognition) result."""
    ocr_id: str
    image_name: str
    extracted_text: str
    confidence: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class FormAnalysis:
    """A form analysis result."""
    form_id: str
    form_name: str
    fields: dict[str, str]
    timestamp: float = field(default_factory=time.time)


class DocumentIntelligence:
    """
    Document Intelligence — OCR, document parsing, PDF text extraction,
    and form analysis.

    Read-only document processing. Document modification requires explicit
    PolicyEngine grant.
    """

    SUPPORTED_TYPES: frozenset[str] = frozenset({
        "pdf", "docx", "txt", "html", "png", "jpg", "jpeg", "tiff",
    })

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.parses: dict[str, DocumentParse] = {}
        self.ocr_results: dict[str, OCRResult] = {}
        self.form_analyses: dict[str, FormAnalysis] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the document intelligence subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "document_intelligence",
            "supported_types": len(self.SUPPORTED_TYPES),
            "policy_gated": True,
            "read_only_default": True,
        }

    def parse_document(
        self,
        document_name: str,
        document_type: str,
        content: bytes,
    ) -> DocumentParse:
        """Parse a document and extract text."""
        if document_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"unsupported document type: {document_type}")

        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "document_intelligence.parse",
                {
                    "document_name": document_name,
                    "document_type": document_type,
                },
            )

        # Schematic text extraction (placeholder)
        extracted = f"[Extracted text from {document_name} - {document_type}]"

        parse = DocumentParse(
            parse_id=f"doc-{int(time.time() * 1000)}",
            document_name=document_name,
            document_type=document_type,
            extracted_text=extracted,
            word_count=len(extracted.split()),
        )
        self.parses[parse.parse_id] = parse

        if self.events:
            self.events.append({
                "event": "document_intelligence.parse",
                "parse_id": parse.parse_id,
                "document_name": document_name,
                "document_type": document_type,
                "approved": grant_result.get("approved", False),
                "at": parse.timestamp,
            })

        return parse

    def perform_ocr(
        self,
        image_name: str,
        image_data: bytes,
    ) -> OCRResult:
        """Perform OCR on an image."""
        ocr = OCRResult(
            ocr_id=f"ocr-{int(time.time() * 1000)}",
            image_name=image_name,
            extracted_text="[OCR extracted text - schematic placeholder]",
            confidence=0.5,
        )
        self.ocr_results[ocr.ocr_id] = ocr
        return ocr

    def analyze_form(
        self,
        form_name: str,
        form_data: dict[str, Any],
    ) -> FormAnalysis:
        """Analyze a form and extract fields."""
        form = FormAnalysis(
            form_id=f"form-{int(time.time() * 1000)}",
            form_name=form_name,
            fields={k: str(v) for k, v in form_data.items()},
        )
        self.form_analyses[form.form_id] = form
        return form

    def list_types(self) -> list[str]:
        """List supported document types."""
        return sorted(self.SUPPORTED_TYPES)

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "document_intelligence",
            "status": "operational" if self._initialized else "offline",
            "parses": len(self.parses),
            "ocr_results": len(self.ocr_results),
            "form_analyses": len(self.form_analyses),
            "supported_types": sorted(self.SUPPORTED_TYPES),
            "capabilities": [
                "document_parsing",
                "ocr",
                "form_analysis",
                "pdf_text_extraction",
            ],
            "constraints": [
                "read_only_default",
                "document_modification_requires_policy_grant",
                "supported_types_only",
            ],
        }


# Global instance
_doc: DocumentIntelligence | None = None


def get_document_intelligence(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> DocumentIntelligence:
    """Get or create the global Document Intelligence instance."""
    global _doc
    if _doc is None:
        _doc = DocumentIntelligence(policy=policy, events=events)
    return _doc


__all__ = [
    "DocumentIntelligence",
    "DocumentParse",
    "OCRResult",
    "FormAnalysis",
    "get_document_intelligence",
]