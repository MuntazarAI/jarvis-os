"""JARVIS-OS — Local-first Personal AI Operating System.

OMNINET (M1-M12) — Universal Internet Gateway & Global Intelligence Infrastructure:

M1: Universal Internet Gateway — Connector base class, HTTP/REST, registry, quotas, health checks
M2: Global Web Discovery — Multi-provider search (DuckDuckGo, SearXNG, Brave) with fallback chain
M3: Advanced Browser Intelligence — Table extraction, metadata (OG/JSON-LD), change detection
M4: Public Data Connectors — 19 connectors across 6 categories (academic, software, cybersecurity,
     global_data, archive, multimedia)
M5: Bounded Web Crawler — Robots.txt compliance, crawl budgets, content dedup, sitemap discovery
M6: Multilingual Global Intelligence — Heuristic language ID, translation, multilingual summarization
M7: Live Internet Observatory — Source monitoring, change detection, daily/weekly reports
M8: Global Knowledge Graph — Entities, relationships, evidence, provenance
M9: Privacy & Threat Research — Privacy network reports, CVE/IOC monitoring, URL reputation
M10: Distributed Intelligence — Worker nodes, task queue (opt-in, disabled by default)
M11: Security & Reliability — Metrics, auditing, emergency stop, SecurityManager
M12: Global Intelligence Dashboard — Unified status dashboard, diagnostic reports

Builds on existing JARVIS systems:
- jarvis/core/internet.py — controlled internet access
- jarvis/security/guards.py — SSRF blocking, injection scanning
- jarvis/policy/policy.py — PolicyEngine gating
- jarvis/browser/agent.py — existing BrowserAgent (DuckDuckGo keyless search)
- jarvis/worldintel/ — existing world intelligence
- jarvis/memory/palace.py — existing Memory Palace
- jarvis/dots/ — existing DOTS lifecycle manager

Every connector and search provider is PolicyEngine-gated.
"""

from jarvis.omninet import (
    # M1: Connector system
    ConnectorSpec,
    ConnectorResult,
    Connector,
    ConnectorRegistry,
    HttpConnector,
    # M2: Discovery system
    SearchProviderSpec,
    SearchResult,
    SearchProvider,
    DuckDuckGoProvider,
    SearXNGProvider,
    BraveSearchProvider,
    SearchEngine,
    # M3: Advanced Browser Intelligence
    PageMetadata,
    PageChange,
    extract_tables,
    extract_metadata,
    ChangeDetector,
    EnhancedBrowserAgent,
    # M4: Public Data Connectors
    DataConnectorResult,
    PublicDataConnector,
    PublicDataRegistry,
    default_public_data_registry,
    ArxivConnector,
    SemanticScholarConnector,
    OpenAlexConnector,
    CrossrefConnector,
    PubMedConnector,
    ZenodoConnector,
    GitHubConnector,
    PyPIConnector,
    HuggingFaceConnector,
    DockerHubConnector,
    CisaConnector,
    OsvConnector,
    UrlhausConnector,
    WikidataConnector,
    OpenStreetMapConnector,
    WorldBankConnector,
    InternetArchiveConnector,
    CommonCrawlConnector,
    MultimediaConnector,
    # M5: Bounded Web Crawler
    RobotsPolicy,
    RobotsCache,
    CrawlBudget,
    CrawlResult,
    BoundedCrawler,
    _parse_robots_txt,
    # M6: Multilingual Global Intelligence
    identify_language,
    TranslationResult,
    TranslationService,
    summarize_multilingual,
    cross_language_search_queries,
    # M7: Live Internet Observatory
    MonitorSource,
    MonitorEvent,
    ObservatoryReport,
    LiveObservatory,
    # M8: Global Knowledge Graph
    Entity,
    Relationship,
    EvidenceRecord,
    KnowledgeGraphStore,
    # M9: Privacy & Threat Research
    PrivacyNetworkReport,
    PrivacyResearch,
    ThreatIndicator,
    ThreatIntel,
    # M10: Distributed Intelligence
    WorkerNode,
    DistributedTask,
    WorkerHealth,
    DistributedIntelligence,
    # M11: Security & Reliability
    ProviderMetric,
    SecurityEvent,
    SecurityMetrics,
    SecurityAuditor,
    SecurityManager,
    # M12: Global Intelligence Dashboard
    ComponentStatus,
    DashboardReport,
    GlobalIntelligenceDashboard,
)

__all__ = [
    # M1: Connector system
    "ConnectorSpec",
    "ConnectorResult",
    "Connector",
    "ConnectorRegistry",
    "HttpConnector",
    # M2: Discovery system
    "SearchProviderSpec",
    "SearchResult",
    "SearchProvider",
    "DuckDuckGoProvider",
    "SearXNGProvider",
    "BraveSearchProvider",
    "SearchEngine",
    # M3: Advanced Browser Intelligence
    "PageMetadata",
    "PageChange",
    "extract_tables",
    "extract_metadata",
    "ChangeDetector",
    "EnhancedBrowserAgent",
    # M4: Public Data Connectors
    "DataConnectorResult",
    "PublicDataConnector",
    "PublicDataRegistry",
    "default_public_data_registry",
    "ArxivConnector",
    "SemanticScholarConnector",
    "OpenAlexConnector",
    "CrossrefConnector",
    "PubMedConnector",
    "ZenodoConnector",
    "GitHubConnector",
    "PyPIConnector",
    "HuggingFaceConnector",
    "DockerHubConnector",
    "CisaConnector",
    "OsvConnector",
    "UrlhausConnector",
    "WikidataConnector",
    "OpenStreetMapConnector",
    "WorldBankConnector",
    "InternetArchiveConnector",
    "CommonCrawlConnector",
    "MultimediaConnector",
    # M5: Bounded Web Crawler
    "RobotsPolicy",
    "RobotsCache",
    "CrawlBudget",
    "CrawlResult",
    "BoundedCrawler",
    "_parse_robots_txt",
    # M6: Multilingual Global Intelligence
    "identify_language",
    "TranslationResult",
    "TranslationService",
    "summarize_multilingual",
    "cross_language_search_queries",
    # M7: Live Internet Observatory
    "MonitorSource",
    "MonitorEvent",
    "ObservatoryReport",
    "LiveObservatory",
    # M8: Global Knowledge Graph
    "Entity",
    "Relationship",
    "EvidenceRecord",
    "KnowledgeGraphStore",
    # M9: Privacy & Threat Research
    "PrivacyNetworkReport",
    "PrivacyResearch",
    "ThreatIndicator",
    "ThreatIntel",
    # M10: Distributed Intelligence
    "WorkerNode",
    "DistributedTask",
    "WorkerHealth",
    "DistributedIntelligence",
    # M11: Security & Reliability
    "ProviderMetric",
    "SecurityEvent",
    "SecurityMetrics",
    "SecurityAuditor",
    "SecurityManager",
    # M12: Global Intelligence Dashboard
    "ComponentStatus",
    "DashboardReport",
    "GlobalIntelligenceDashboard",
]
