"""JARVIS OMNINET — Universal Internet Gateway (M1) + Global Web Discovery (M2)
+ Advanced Browser Intelligence (M3) + Public Data Connectors (M4)
+ Bounded Web Crawler (M5) + Multilingual Intelligence (M6)
+ Live Internet Observatory (M7) + Global Knowledge Graph (M8)
+ Privacy & Threat Research (M9) + Distributed Intelligence (M10).

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

from .connectors import (
    Connector,
    ConnectorRegistry,
    ConnectorResult,
    ConnectorSpec,
)
from .discovery import (
    BraveSearchProvider,
    DuckDuckGoProvider,
    SearchEngine,
    SearchProvider,
    SearchProviderSpec,
    SearchResult,
    SearXNGProvider,
)
from .exploration import (
    ChangeDetector,
    EnhancedBrowserAgent,
    PageChange,
    PageMetadata,
    extract_metadata,
    extract_tables,
)
from .http_connector import HttpConnector
from .crawler import (
    BoundedCrawler,
    CrawlBudget,
    CrawlResult,
    RobotsCache,
    RobotsPolicy,
    _parse_robots_txt,
)
from .public_data import (
    ArxivConnector,
    CommonCrawlConnector,
    CisaConnector,
    CrossrefConnector,
    DataConnectorResult,
    DockerHubConnector,
    GitHubConnector,
    HuggingFaceConnector,
    InternetArchiveConnector,
    MultimediaConnector,
    OsvConnector,
    OpenAlexConnector,
    OpenStreetMapConnector,
    PublicDataConnector,
    PublicDataRegistry,
    PubMedConnector,
    PyPIConnector,
    SemanticScholarConnector,
    UrlhausConnector,
    WikidataConnector,
    WorldBankConnector,
    ZenodoConnector,
    default_public_data_registry,
)
from .multilingual import (
    TranslationResult,
    TranslationService,
    cross_language_search_queries,
    identify_language,
    summarize_multilingual,
)
from .neural_networking import (
    NeuralNetwork,
    NeuralNetworkConfig,
    NeuralNetworkLayer,
    MixtureOfExperts,
    Expert,
    NeuralSymbolicBridge,
    NeuralNetworkRegistry,
    get_neural_registry,
    create_neural_network,
    create_moe_network,
)
from .observatory import (
    LiveObservatory,
    MonitorEvent,
    MonitorSource,
    ObservatoryReport,
)
from .knowledge_graph import (
    Entity,
    EvidenceRecord,
    KnowledgeGraphStore,
    Relationship,
)
from .threat_intel import (
    PrivacyNetworkReport,
    PrivacyResearch,
    ThreatIndicator,
    ThreatIntel,
)
from .distributed import (
    DistributedIntelligence,
    DistributedTask,
    WorkerHealth,
    WorkerNode,
)
from .integration import (
    DotExecution,
    JarvisIntegratedSystem,
    StarkJob,
    dispatch_stark_ai,
    get_integrated_system,
)
from .gods_eye_view import (
    GodsEyeView,
    GeoContact,
    GlobeView,
    get_gods_eye_view,
)
from .see_through_walls import (
    SeeThroughWalls,
    ARPose,
    ARSession,
    get_see_through_walls,
)
from .build_your_own_x import (
    BuildYourOwnX,
    BuildGuide,
    BuildProject,
    get_build_your_own_x,
)
from .web_search_intelligence import (
    WebSearchIntelligence,
    SearchResult,
    SearchResponse,
    get_web_search_intelligence,
)
from .security_scanning_intelligence import (
    SecurityScanningIntelligence,
    SecurityFinding,
    ScanReport,
    get_security_scanning_intelligence,
)
from .knowledge_graph_expansion import (
    KnowledgeGraphExpansion,
    KnowledgeEntity,
    KnowledgeRelationship,
    get_knowledge_graph_expansion,
)
from .audio_intelligence import (
    AudioIntelligence,
    AudioEvent,
    TranscriptionResult,
    TTSRequest,
    get_audio_intelligence,
)
from .vision_intelligence import (
    VisionIntelligence,
    VisualObservation,
    ImageClassification,
    get_vision_intelligence,
)
from .weather_intelligence import (
    WeatherIntelligence,
    WeatherObservation,
    WeatherForecast,
    WeatherAlert,
    get_weather_intelligence,
)
from .geospatial_intelligence import (
    GeospatialIntelligence,
    GeoLocation,
    GeoDistance,
    GeoMap,
    get_geospatial_intelligence,
)
from .calendar_intelligence import (
    CalendarIntelligence,
    CalendarEvent,
    MeetingRequest,
    Reminder,
    get_calendar_intelligence,
)
from .translation_intelligence import (
    TranslationIntelligence,
    Translation,
    LanguageDetection,
    get_translation_intelligence,
)
from .document_intelligence import (
    DocumentIntelligence,
    DocumentParse,
    OCRResult,
    FormAnalysis,
    get_document_intelligence,
)
from ..agents.stark import SecurityAgentExecutor
from .security import (
    SecurityAuditor,
    SecurityEvent,
    SecurityManager,
    SecurityMetrics,
    ProviderMetric,
)
from .dashboard import (
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
    # M13: Neural Networking
    "NeuralNetworkConfig",
    "NeuralNetworkLayer",
    "NeuralNetwork",
    "Expert",
    "MixtureOfExperts",
    "NeuralSymbolicBridge",
    "NeuralNetworkRegistry",
    "get_neural_registry",
    "create_neural_network",
    "create_moe_network",
    # M13b: Integration (Stark AI → DOTS → OMNINET → Neural Network)
    "StarkJob",
    "DotExecution",
    "JarvisIntegratedSystem",
    "dispatch_stark_ai",
    "get_integrated_system",
    # M13c: God's Eye View
    "GodsEyeView",
    "GeoContact",
    "GlobeView",
    "get_gods_eye_view",
    # M13d: See-Through-Walls AR
    "SeeThroughWalls",
    "ARPose",
    "ARSession",
    "get_see_through_walls",
    # M13e: Build-Your-Own-X
    "BuildYourOwnX",
    "BuildGuide",
    "BuildProject",
    "get_build_your_own_x",
    # M13f: Web Search Intelligence
    "WebSearchIntelligence",
    "SearchResult",
    "SearchResponse",
    "get_web_search_intelligence",
    # M13g: Security Scanning Intelligence
    "SecurityScanningIntelligence",
    "SecurityFinding",
    "ScanReport",
    "get_security_scanning_intelligence",
    # M13h: Knowledge Graph Expansion
    "KnowledgeGraphExpansion",
    "KnowledgeEntity",
    "KnowledgeRelationship",
    "get_knowledge_graph_expansion",
    # M13i: Audio Intelligence
    "AudioIntelligence",
    "AudioEvent",
    "TranscriptionResult",
    "TTSRequest",
    "get_audio_intelligence",
    # M13j: Vision Intelligence
    "VisionIntelligence",
    "VisualObservation",
    "ImageClassification",
    "get_vision_intelligence",
    # M13k: Weather Intelligence
    "WeatherIntelligence",
    "WeatherObservation",
    "WeatherForecast",
    "WeatherAlert",
    "get_weather_intelligence",
    # M13l: Geospatial Intelligence
    "GeospatialIntelligence",
    "GeoLocation",
    "GeoDistance",
    "GeoMap",
    "get_geospatial_intelligence",
    # M13m: Calendar Intelligence
    "CalendarIntelligence",
    "CalendarEvent",
    "MeetingRequest",
    "Reminder",
    "get_calendar_intelligence",
    # M13n: Translation Intelligence
    "TranslationIntelligence",
    "Translation",
    "LanguageDetection",
    "get_translation_intelligence",
    # M13o: Document Intelligence
    "DocumentIntelligence",
    "DocumentParse",
    "OCRResult",
    "FormAnalysis",
    "get_document_intelligence",
]
