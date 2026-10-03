"""World Intelligence facade (1.0).

Composes existing JARVIS systems (live providers, research engine,
browser, world registry, knowledge graph, guards, policy) with the new
evidence-reasoning pieces in this package. Nothing here duplicates a
subsystem; see the gap matrix in the final report.
"""

from .briefing import build_briefing
from .cache import EvidenceCache, cache_key
from .changes import diff_snapshots, snapshot_claims
from .claims import Claim, extract_claims
from .conflicts import corroboration, dedupe_claims, detect_conflicts
from .freshness import FreshnessState, assess
from .local import (computer_snapshot, device_snapshot,
                    home_assistant_spec, openclaw_spec)
from .research import Answer, Researcher
from .routing import route
from .sources import (EvidenceItem, Source, SourceRegistry,
                      default_sources)
from .telemetry import WorldTelemetry
from .worldsync import sync_answer

__all__ = ["Answer", "Claim", "EvidenceCache", "EvidenceItem",
           "Researcher", "Source", "SourceRegistry", "WorldTelemetry",
           "assess", "build_briefing", "cache_key",
           "computer_snapshot", "corroboration", "dedupe_claims",
           "default_sources", "detect_conflicts", "device_snapshot",
           "diff_snapshots", "extract_claims", "home_assistant_spec",
           "openclaw_spec", "route", "snapshot_claims", "sync_answer",
           "FreshnessState"]
