"""Jarvis Foundation AI Models (M13).

Foundation Model Research Lab - builds the JARVIS family of foundation models.

Research targets (not yet implemented - research roadmap):

JARVIS-LLM      - General-purpose language model
JARVIS-REASONER - Advanced problem decomposition, inference, verification, reasoning
JARVIS-CODE     - Programming and software engineering model
JARVIS-VISION   - Visual perception and image understanding model
JARVIS-AUDIO    - Audio perception and speech understanding model
JARVIS-EMBEDDING - Semantic representation and retrieval model
JARVIS-RERANKER - Knowledge relevance ranking model
JARVIS-WORLD    - Environmental and temporal representations model
JARVIS-ACTION   - Structured action and tool-selection model

Each model profile is a StarkAI-compatible definition that can be registered
with the Stark AI roster system (jarvis.agents.stark).

Research architectures:
- Decoder-only Transformers
- Encoder-only Transformers
- Encoder-decoder Transformers
- Vision Transformers
- Mixture of Experts
- State Space Models
- Hybrid neural architectures
- Multimodal architectures
- Retrieval-augmented architectures

Each model profile includes:
- Research hypothesis
- Architecture specification
- Dataset requirements
- Training configuration
- Evaluation methodology
- Expected capabilities
- Limitations and risks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agents.stark import StarkAI
from ..core.types import new_id


def _make_stark_ai(
    ai_id: str,
    name: str,
    role: str,
    description: str,
    tools: list[str] | None = None,
    permissions: list[str] | None = None,
    max_tool_calls: int = 4,
    max_seconds: float = 60.0,
    dispatchable: bool = True,
    risk_tier: str = "medium",
    team: str = "core",
    may_act: bool = True,
    signature: str = "",
    internet_domains: tuple[str, ...] = (),
    learned_skills: tuple[str, ...] = (),
    personality: tuple[str, ...] = (),
    origin: str = "",
    duties: tuple[str, ...] = (),
    works: tuple[str, ...] = (),
    limits: tuple[str, ...] = (),
    roles: tuple[tuple[str, str], ...] = (),
    acronym: str = "",
    title: str = "",
    lineage: str = "stark",
    origin_text: str = "",
    personality_desc: str = "",
) -> StarkAI:
    """Build a StarkAI from model specification parameters."""
    return StarkAI(
        ai_id=ai_id,
        name=name,
        acronym=acronym,
        title=title,
        lineage=lineage,
        origin=origin_text,
        personality=personality,
        duties=duties,
        works=works,
        limits=limits,
        roles=roles,
        team=team,
        may_act=may_act,
        max_tool_calls=max_tool_calls,
        max_seconds=max_seconds,
        dispatchable=dispatchable,
        signature=signature,
        role=role,
        risk_tier=risk_tier,
        tools=tuple(tools or []),
        internet_domains=internet_domains,
        learned_skills=learned_skills,
    )


# ---------------------------------------------------------------------------
# JARVIS-LLM — General-Purpose Language Model
# ------------------------------------------------------------------

JARVIS_LLM = StarkAI(
    ai_id="jarvis-llm-1",
    name="JARVIS-LLM-1",
    acronym="JLLM-1",
    title="General-Purpose Language Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "General-purpose language model trained on diverse text corpus."
    ),
    personality=("calm", "precise", "helpful", "honest", "curious"),
    duties=(
        "Answer general knowledge questions",
        "Assist with writing and editing tasks",
        "Explain complex topics in simple terms",
        "Engage in helpful dialogue",
    ),
    works=(
        "Answer questions",
        "Write and edit text",
        "Explain concepts",
        "Have conversations",
    ),
    limits=(
        "May hallucinate facts",
        "Cannot access real-time information without tools",
        "May reflect training data biases",
        "Cannot perform actions without tools",
    ),
    roles=(("assistant", "general"), ("assistant", "chat")),
    team="core",
    may_act=True,
    max_tool_calls=8,
    max_seconds=60.0,
    dispatchable=True,
    signature="JARVIS-LLM-1 — Your capable general assistant",
    risk_tier="medium",
    tools=(),
    internet_domains=("pypi.org", "docs.python.org", "github.com", "en.wikipedia.org"),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-REASONER — Advanced Reasoning Model
# ------------------------------------------------------------------

JARVIS_REASONER = StarkAI(
    ai_id="jarvis-reasoner-1",
    name="JARVIS-REASONER-1",
    acronym="JREASON-1",
    title="Advanced Reasoning Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "Advanced reasoning model for complex problem decomposition and analysis."
    ),
    personality=("analytical", "logical", "precise", "methodical", "thorough"),
    duties=(
        "Break down complex problems into steps",
        "Identify contradictions and inconsistencies",
        "Verify claims against evidence",
        "Recommend optimal solutions",
    ),
    works=(
        "Reason through problems",
        "Identify contradictions",
        "Verify claims",
        "Recommend solutions",
    ),
    limits=(
        "Reasoning quality depends on input quality",
        "May miss creative solutions",
        "Cannot access external information without tools",
        "Requires clear problem statements",
    ),
    roles=(("reasoner", "analyst"), ("reasoner", "verifier")),
    team="core",
    may_act=True,
    max_tool_calls=6,
    max_seconds=120.0,
    dispatchable=True,
    signature="JARVIS-REASONER-1 — Analytical reasoning specialist",
    risk_tier="medium",
    tools=(),
    internet_domains=("arxiv.org", "stackexchange.com", "stackexchange.com"),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-CODE — Programming and Software Engineering Model
# ------------------------------------------------------------------

JARVIS_CODE = StarkAI(
    ai_id="jarvis-code-1",
    name="JARVIS-CODE-1",
    acronym="JCODE-1",
    title="Programming and Software Engineering Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "Specialized model for programming, debugging, and software engineering."
    ),
    personality=("precise", "logical", "systematic", "patient", "thorough"),
    duties=(
        "Write clean, documented code",
        "Debug and fix code issues",
        "Review code for bugs and security",
        "Recommend best practices",
    ),
    works=(
        "Write code",
        "Debug programs",
        "Review code",
        "Recommend best practices",
    ),
    limits=(
        "May introduce subtle bugs",
        "Cannot execute code without tools",
        "May not know latest library versions",
        "Requires clear specifications",
    ),
    roles=(("developer", "coder"), ("developer", "reviewer")),
    team="core",
    may_act=True,
    max_tool_calls=8,
    max_seconds=120.0,
    dispatchable=True,
    signature="JARVIS-CODE-1 — Programming and software engineering assistant",
    risk_tier="medium",
    tools=("filesystem_read", "filesystem_write", "terminal_run", "git_status"),
    internet_domains=("github.com", "stackoverflow.com", "docs.python.org", "pypi.org"),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-VISION — Visual Perception Model
# ------------------------------------------------------------------

JARVIS_VISION = StarkAI(
    ai_id="jarvis-vision-1",
    name="JARVIS-VISION-1",
    acronym="JVIS-1",
    title="Visual Perception Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "Vision model for image understanding and visual question answering."
    ),
    personality=("observant", "precise", "descriptive", "careful"),
    duties=(
        "Describe image content",
        "Answer visual questions",
        "Identify objects and scenes",
        "Extract text from images (OCR)",
    ),
    works=(
        "Describe images",
        "Answer visual questions",
        "Identify objects",
        "Extract text (OCR)",
    ),
    limits=(
        "Cannot see real-time without camera",
        "May misinterpret ambiguous images",
        "Cannot browse web images without tools",
        "Limited to provided images",
    ),
    roles=(("perception", "vision"), ("perception", "ocr")),
    team="perception",
    may_act=True,
    max_tool_calls=4,
    max_seconds=30.0,
    dispatchable=True,
    signature="JARVIS-VISION-1 — Visual perception specialist",
    risk_tier="medium",
    tools=("screen_capture", "screen_ocr", "screen_understand"),
    internet_domains=(),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-AUDIO — Audio Perception Model
# ------------------------------------------------------------------

JARVIS_AUDIO = StarkAI(
    ai_id="jarvis-audio-1",
    name="JARVIS-AUDIO-1",
    acronym="JAUD-1",
    title="Audio Perception Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "Audio processing model for speech recognition and audio understanding."
    ),
    personality=("attentive", "precise", "patient", "clear"),
    duties=(
        "Transcribe speech to text",
        "Identify speakers",
        "Detect emotions in speech",
        "Analyze audio content",
    ),
    works=(
        "Transcribe speech",
        "Identify speakers",
        "Detect emotions",
        "Analyze audio content",
    ),
    limits=(
        "Cannot access microphone without permission",
        "May miss quiet or unclear speech",
        "Cannot process audio without input",
        "Limited to provided audio",
    ),
    roles=(("perception", "audio"), ("perception", "transcription")),
    team="perception",
    may_act=True,
    max_tool_calls=4,
    max_seconds=60.0,
    dispatchable=True,
    signature="JARVIS-AUDIO-1 — Audio perception specialist",
    risk_tier="medium",
    tools=(),
    internet_domains=(),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-EMBEDDING — Semantic Representation Model
# ------------------------------------------------------------------

JARVIS_EMBEDDING = StarkAI(
    ai_id="jarvis-embedding-1",
    name="JARVIS-EMBEDDING-1",
    acronym="JEMB-1",
    title="Semantic Representation Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "Embedding model for semantic search and retrieval."
    ),
    personality=("precise", "consistent", "neutral", "technical"),
    duties=(
        "Encode text into embeddings",
        "Compute semantic similarity",
        "Cluster similar content",
        "Support semantic search",
    ),
    works=(
        "Encode text to embeddings",
        "Compute similarities",
        "Cluster content",
        "Support search",
    ),
    limits=(
        "Cannot understand context beyond training",
        "May miss domain-specific terminology",
        "Cannot generate text",
        "Limited to embedding tasks",
    ),
    roles=(("embedding", "retrieval"), ("embedding", "similarity")),
    team="core",
    may_act=True,
    max_tool_calls=10,
    max_seconds=15.0,
    dispatchable=True,
    signature="JARVIS-EMBEDDING-1 — Semantic embedding specialist",
    risk_tier="low",
    tools=(),
    internet_domains=(),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-RERANKER — Knowledge Relevance Ranking Model
# ------------------------------------------------------------------

JARVIS_RERANKER = StarkAI(
    ai_id="jarvis-reranker-1",
    name="JARVIS-RERANKER-1",
    acronym="JRER-1",
    title="Knowledge Relevance Ranking Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "Ranking model for relevance scoring in search and retrieval."
    ),
    personality=("precise", "discerning", "analytical", "consistent"),
    duties=(
        "Rank search results by relevance",
        "Score document-query relevance",
        "Filter irrelevant results",
        "Improve search quality",
    ),
    works=(
        "Rank search results",
        "Score relevance",
        "Filter irrelevant content",
        "Improve search quality",
    ),
    limits=(
        "Cannot generate new content",
        "Depends on input quality",
        "May miss niche relevance",
        "Requires good candidate set",
    ),
    roles=(("ranking", "rerank"), ("ranking", "score")),
    team="core",
    may_act=True,
    max_tool_calls=6,
    max_seconds=15.0,
    dispatchable=True,
    signature="JARVIS-RERANKER-1 — Relevance ranking specialist",
    risk_tier="low",
    tools=(),
    internet_domains=(),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-WORLD — Environmental and Temporal Representations Model
# ------------------------------------------------------------------

JARVIS_WORLD = StarkAI(
    ai_id="jarvis-world-1",
    name="JARVIS-WORLD-1",
    acronym="JWRLD-1",
    title="Environmental and Temporal Representations Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "World model for environmental understanding and temporal reasoning."
    ),
    personality=("deliberate", "systematic", "ethical", "thorough"),
    duties=(
        "Model environmental states",
        "Track temporal changes",
        "Predict future states",
        "Synthesize evidence",
    ),
    works=(
        "Model environments",
        "Track temporal changes",
        "Predict future states",
        "Synthesize evidence",
    ),
    limits=(
        "Dependent on sensor quality",
        "Predictions are probabilistic",
        "Cannot access unobserved areas",
        "Requires consistent data",
    ),
    roles=(("world", "model"), ("world", "verifier")),
    team="core",
    may_act=True,
    max_tool_calls=6,
    max_seconds=45.0,
    dispatchable=True,
    signature="JARVIS-WORLD-1 — Environmental verification specialist",
    risk_tier="medium",
    tools=("filesystem_read", "system_probe"),
    internet_domains=(),
    learned_skills=(),
)

# ---------------------------------------------------------------------------
# JARVIS-ACTION — Structured Action and Tool-Selection Model
# ------------------------------------------------------------------

JARVIS_ACTION = StarkAI(
    ai_id="jarvis-action-1",
    name="JARVIS-ACTION-1",
    acronym="JACT-1",
    title="Structured Action and Tool-Selection Model",
    lineage="stark",
    origin=(
        "JARVIS-OS Foundation Model Research Lab. "
        "Action selection model for tool selection and action planning."
    ),
    personality=("decisive", "structured", "precise", "efficient"),
    duties=(
        "Select appropriate tools",
        "Plan action sequences",
        "Verify action outcomes",
        "Recommend next actions",
    ),
    works=(
        "Select tools",
        "Plan actions",
        "Verify outcomes",
        "Recommend actions",
    ),
    limits=(
        "Cannot execute actions without tools",
        "May suggest suboptimal actions",
        "Depends on available tools",
        "Requires clear goals",
    ),
    roles=(("action", "selector"), ("action", "verifier")),
    team="core",
    may_act=True,
    max_tool_calls=6,
    max_seconds=30.0,
    dispatchable=True,
    signature="JARVIS-ACTION-1 — Action selection specialist",
    risk_tier="medium",
    tools=(),
    internet_domains=(),
    learned_skills=(),
)

# Registry of all Stark AI models
STARK_ROSTER_LIST = [
    JARVIS_LLM,
    JARVIS_REASONER,
    JARVIS_CODE,
    JARVIS_VISION,
    JARVIS_AUDIO,
    JARVIS_EMBEDDING,
    JARVIS_RERANKER,
    JARVIS_WORLD,
    JARVIS_ACTION,
]


def create_all_stark_models() -> list:
    """Create all Stark AI models and return the list."""
    return [
        JARVIS_LLM,
        JARVIS_REASONER,
        JARVIS_CODE,
        JARVIS_VISION,
        JARVIS_AUDIO,
        JARVIS_EMBEDDING,
        JARVIS_RERANKER,
        JARVIS_WORLD,
        JARVIS_ACTION,
    ]


def get_stark_model(ai_id: str) -> StarkAI | None:
    """Get a Stark AI model by ID."""
    for stark in STARK_ROSTER_LIST:
        if stark.ai_id == ai_id:
            return stark
    return None


def get_stark_models_by_role(role: str) -> list:
    """Get all Stark AI models with a given role."""
    return [s for s in STARK_ROSTER_LIST if s.role == role]


def get_all_stark_models() -> list:
    """Get all Stark AI models."""
    return STARK_ROSTER_LIST.copy()