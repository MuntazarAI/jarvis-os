"""OMNINET M6-M10 tests.

M6: Multilingual Global Intelligence - language ID, translation, summarization
M7: Live Internet Observatory - source monitoring, event detection, reports
M8: Global Knowledge Graph - entities, relationships, evidence
M9: Privacy & Threat Research - privacy networks, CVE/IOC, threat intel
M10: Distributed Intelligence - worker nodes, task queue (opt-in)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.core.config import JarvisConfig
from jarvis.core.internet import InternetAccess
from jarvis.core.types import ActionPlan, RiskLevel
from jarvis.omninet import (
    BoundedCrawler,
    CrawlBudget,
    DistributedIntelligence,
    DistributedTask,
    EnhancedBrowserAgent,
    Entity,
    EvidenceRecord,
    identify_language,
    KnowledgeGraphStore,
    LiveObservatory,
    MonitorEvent,
    MonitorSource,
    ObservatoryReport,
    PrivacyNetworkReport,
    PrivacyResearch,
    Relationship,
    SearchEngine,
    SemanticScholarConnector,
    ThreatIndicator,
    ThreatIntel,
    TranslationResult,
    TranslationService,
    WorkerNode,
    summarize_multilingual,
)
from jarvis.policy.policy import PolicyEngine


# -- fixtures -----------------------------------------------------------


def _make_policy_and_internet(home: str | None = None):
    cfg = JarvisConfig()
    if home:
        cfg.paths.home = Path(home)
    policy = PolicyEngine(cfg)
    internet = InternetAccess(policy)
    policy.grant("jarvis", "net.fetch")
    for d in ("example.com", "example.org", "nvd.nist.gov",
              "api.osv.dev", "urlhaus-api.abuse.ch"):
        internet.allowed_domains.add(d)
    policy.grant("jarvis", "internet:example.com")
    internet.request_domain_access(
        agent_id="jarvis", domain="example.com",
        max_requests_per_hour=100, grant_seconds=3600,
    )
    return policy, internet


# -- M6: Multilingual ---------------------------------------------------


def test_identify_language_english():
    result = identify_language("The cat sat on the mat and ate some food.")
    assert result["language"] == "en"
    assert result["confidence"] > 0.0
    assert result["method"] in ("script", "stopwords", "fallback")


def test_identify_language_spanish():
    result = identify_language("El gato se sentó en la alfombra y comió comida.")
    assert result["language"] == "es"
    assert result["confidence"] > 0.0


def test_identify_language_french():
    result = identify_language("Le chat était assis sur le tapis et mangeait de la nourriture.")
    assert result["language"] == "fr"


def test_identify_language_empty():
    result = identify_language("")
    assert result["language"] == "unknown"


def test_summarize_multilingual_basic():
    text = ("The quick brown fox jumps over the lazy dog. "
            "The dog was sleeping peacefully in the garden. "
            "A bird flew across the blue sky. "
            "The sun was shining brightly. "
            "Children were playing in the park nearby.")
    result = summarize_multilingual(text, max_sentences=2)
    assert "language" in result
    assert "summary" in result
    assert "sentences" in result
    assert len(result["sentences"]) <= 2


def test_summarize_multilingual_short_text():
    text = "Hello world."
    result = summarize_multilingual(text, max_sentences=5)
    assert result["summary"] == "Hello world."
    assert len(result["sentences"]) == 1


def test_translation_service_init():
    policy, internet = _make_policy_and_internet()
    svc = TranslationService(policy, internet, actor="jarvis")
    assert svc is not None


def test_translation_same_language():
    policy, internet = _make_policy_and_internet()
    svc = TranslationService(policy, internet, actor="jarvis")
    result = svc.translate("Hello world", "en")
    assert result.translated_text == "Hello world"
    assert result.provider == "none"
    assert result.confidence == 1.0


def test_translation_result_creation():
    result = TranslationResult(
        source_text="Hello",
        translated_text="Hola",
        source_language="en",
        target_language="es",
        provider="test",
        confidence=0.8,
    )
    assert result.source_text == "Hello"
    assert result.translated_text == "Hola"
    assert result.source_language == "en"
    assert result.target_language == "es"


# -- M7: Live Observatory -----------------------------------------------


def test_monitor_source_creation():
    source = MonitorSource(
        source_id="test-1",
        name="Test Source",
        url="https://example.com/",
        kind="news",
        check_interval_s=3600.0,
        tags=["test"],
    )
    assert source.source_id == "test-1"
    assert source.name == "Test Source"
    assert source.enabled is True


def test_observatory_add_source():
    policy, internet = _make_policy_and_internet()
    obs = LiveObservatory(policy, internet, actor="jarvis")
    source = MonitorSource(
        source_id="src-1",
        name="Test",
        url="https://example.com/",
        kind="news",
    )
    obs.add_source(source)
    sources = obs.list_sources()
    assert len(sources) == 1
    assert sources[0]["name"] == "Test"


def test_observatory_enable_disable():
    policy, internet = _make_policy_and_internet()
    obs = LiveObservatory(policy, internet, actor="jarvis")
    source = MonitorSource(
        source_id="src-2",
        name="Test",
        url="https://example.com/",
        kind="news",
    )
    obs.add_source(source)
    obs.disable_source("src-2")
    sources = obs.list_sources()
    assert sources[0]["enabled"] is False
    obs.enable_source("src-2")
    sources = obs.list_sources()
    assert sources[0]["enabled"] is True


def test_observatory_check_source_no_grant():
    policy, internet = _make_policy_and_internet()
    obs = LiveObservatory(policy, internet, actor="jarvis")
    # example.com has grant, blocked.com doesn't
    source = MonitorSource(
        source_id="src-3",
        name="Blocked",
        url="https://blocked.com/",
        kind="news",
    )
    obs.add_source(source)
    events = obs.check_source(source)
    assert events == []  # no grant, so no events


def test_observatory_report():
    policy, internet = _make_policy_and_internet()
    obs = LiveObservatory(policy, internet, actor="jarvis")
    report = obs.generate_report("daily")
    assert report.period == "daily"
    assert report.sources_monitored == 0
    assert report.events_detected == 0


def test_observatory_status():
    policy, internet = _make_policy_and_internet()
    obs = LiveObservatory(policy, internet, actor="jarvis")
    status = obs.status()
    assert "sources_monitored" in status
    assert "events_total" in status


# -- M8: Knowledge Graph ------------------------------------------------


def test_kg_add_entity():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    ent = store.add_entity(
        name="TestCorp",
        type="organization",
        description="A test organization",
        confidence=0.8,
    )
    assert ent.name == "TestCorp"
    assert ent.type == "organization"
    assert ent.confidence == 0.8


def test_kg_get_entity():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    ent = store.add_entity(name="Acme", type="company")
    fetched = store.get_entity(ent.entity_id)
    assert fetched is not None
    assert fetched.name == "Acme"


def test_kg_find_entity_by_name():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    store.add_entity(name="Globex Corp", type="organization")
    found = store.find_entity_by_name("globex corp")
    assert found is not None
    assert found.name == "Globex Corp"


def test_kg_entities_by_type():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    store.add_entity(name="CVE-2024-0001", type="vulnerability")
    store.add_entity(name="CVE-2024-0002", type="vulnerability")
    store.add_entity(name="ExampleCorp", type="organization")
    vulns = store.entities_by_type("vulnerability")
    assert len(vulns) == 2


def test_kg_add_relationship():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    e1 = store.add_entity(name="Alice", type="person")
    e2 = store.add_entity(name="Acme Corp", type="organization")
    rel = store.add_relationship(
        e1.entity_id, e2.entity_id, "works_for", confidence=0.9,
    )
    assert rel.source_entity_id == e1.entity_id
    assert rel.target_entity_id == e2.entity_id
    assert rel.relation_type == "works_for"


def test_kg_relationships_for_entity():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    e1 = store.add_entity(name="Bob", type="person")
    e2 = store.add_entity(name="Beta Corp", type="organization")
    store.add_relationship(e1.entity_id, e2.entity_id, "works_for")
    rels = store.relationships_for_entity(e1.entity_id)
    assert len(rels) == 1


def test_kg_add_evidence():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    ent = store.add_entity(name="TestOrg", type="organization")
    ev = store.add_evidence(
        entity_id=ent.entity_id,
        source_url="https://example.com/",
        extracted_text="Test evidence",
        confidence=0.7,
    )
    assert ev.entity_id == ent.entity_id
    assert ev.extracted_text == "Test evidence"


def test_kg_search_entities():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    store.add_entity(name="Alpha Research", type="organization")
    store.add_entity(name="Beta Labs", type="organization")
    results = store.search_entities("Alpha")
    assert len(results) == 1
    assert results[0].name == "Alpha Research"


def test_kg_stats():
    store = KnowledgeGraphStore(home=Path(tempfile.mkdtemp(prefix="kg-test-")))
    store.add_entity(name="Test1", type="concept")
    store.add_entity(name="Test2", type="concept")
    stats = store.stats()
    assert stats["entities"] == 2


# -- M9: Privacy & Threat -----------------------------------------------


def test_privacy_network_report():
    research = PrivacyResearch()
    report = research.network_report("tor")
    assert report.network == "tor"
    assert "Onion Router" in report.description
    assert len(report.defensive_use_cases) > 0
    assert len(report.limitations) > 0


def test_privacy_list_networks():
    research = PrivacyResearch()
    networks = research.list_networks()
    assert "tor" in networks
    assert "i2p" in networks
    assert "ipfs" in networks


def test_threat_indicator_creation():
    ind = ThreatIndicator(
        indicator_id="ind-1",
        type="cve",
        value="CVE-2024-1234",
        description="Test vulnerability",
        source="nvd.nist.gov",
        severity="high",
        confidence=0.8,
        tags=["cve", "test"],
        is_defensive=True,
    )
    assert ind.is_defensive is True
    assert ind.severity == "high"


def test_threat_intel_init():
    policy, internet = _make_policy_and_internet()
    ti = ThreatIntel(policy, internet, actor="jarvis")
    assert ti is not None


def test_threat_intel_add_indicator():
    policy, internet = _make_policy_and_internet()
    ti = ThreatIntel(policy, internet, actor="jarvis")
    ind = ThreatIndicator(
        indicator_id="manual-1",
        type="cve",
        value="CVE-2024-9999",
        description="Manually added",
        source="manual",
        severity="critical",
        confidence=0.9,
        is_defensive=True,
    )
    ti.add_indicator(ind)
    fetched = ti.get_indicator("manual-1")
    assert fetched is not None
    assert fetched.value == "CVE-2024-9999"


def test_threat_intel_list_indicators():
    policy, internet = _make_policy_and_internet()
    ti = ThreatIntel(policy, internet, actor="jarvis")
    ti.add_indicator(ThreatIndicator(
        indicator_id="i1", type="cve", value="CVE-1",
        description="d", source="s", severity="high",
        confidence=0.8, is_defensive=True,
    ))
    ti.add_indicator(ThreatIndicator(
        indicator_id="i2", type="ioc", value="IOC-1",
        description="d", source="s", severity="low",
        confidence=0.5, is_defensive=True,
    ))
    high = ti.list_indicators(min_severity="high")
    assert len(high) == 1
    assert high[0].severity == "high"


def test_threat_intel_stats():
    policy, internet = _make_policy_and_internet()
    ti = ThreatIntel(policy, internet, actor="jarvis")
    ti.add_indicator(ThreatIndicator(
        indicator_id="s1", type="cve", value="CVE-1",
        description="d", source="s", severity="critical",
        confidence=0.9, is_defensive=True,
    ))
    stats = ti.stats()
    assert stats["total_indicators"] == 1
    assert stats["all_defensive"] is True


def test_privacy_research_tor_limitations():
    research = PrivacyResearch()
    report = research.network_report("tor")
    assert len(report.limitations) > 0
    assert "observed" in report.limitations[0].lower()


# -- M10: Distributed Intelligence --------------------------------------


def test_distributed_init_disabled():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    assert di.is_enabled() is False


def test_distributed_enable_disable():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    di.enable()
    assert di.is_enabled() is True
    di.disable()
    assert di.is_enabled() is False


def test_distributed_register_worker_when_disabled():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    try:
        di.register_worker("test-worker", "localhost", 8080)
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass


def test_distributed_register_worker_when_enabled():
    policy, internet = _make_policy_and_internet()
    policy.grant("jarvis", "net.fetch")
    policy.grant("jarvis", "distributed.register")
    internet.request_domain_access(
        agent_id="jarvis", domain="localhost",
        max_requests_per_hour=100, grant_seconds=3600,
    )
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    di.enable()
    node = di.register_worker(
        "test-worker", "localhost", 8080,
        capabilities=["research", "crawl"],
        max_concurrent_tasks=3,
    )
    assert node.name == "test-worker"
    assert node.host == "localhost"
    assert node.port == 8080
    assert "research" in node.capabilities


def test_distributed_list_workers():
    policy, internet = _make_policy_and_internet()
    policy.grant("jarvis", "net.fetch")
    policy.grant("jarvis", "distributed.register")
    internet.request_domain_access(
        agent_id="jarvis", domain="localhost",
        max_requests_per_hour=100, grant_seconds=3600,
    )
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    di.enable()
    di.register_worker("w1", "host1", 8080, capabilities=["research"])
    workers = di.list_workers()
    assert len(workers) == 1
    assert workers[0]["name"] == "w1"


def test_distributed_submit_task_no_workers():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    di.enable()
    task = di.submit_task("research", {"query": "test"})
    assert task.task_id is not None
    assert task.status == "queued"


def test_distributed_task_result_not_found():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    di.enable()
    result = di.get_task_result("nonexistent")
    assert result is None


def test_distributed_cancel_queued_task():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    di.enable()
    task = di.submit_task("research", {"query": "test"})
    assert di.cancel_task(task.task_id) is True
    assert di.get_task(task.task_id).status == "cancelled"


def test_distributed_status():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    status = di.status()
    assert status["enabled"] is False
    assert status["workers"] == 0


def test_distributed_schedule_job():
    policy, internet = _make_policy_and_internet()
    di = DistributedIntelligence(policy, internet, actor="jarvis")
    job_id = di.schedule_job("daily-research", "research", {"query": "AI"}, 86400.0)
    assert job_id is not None
    task = di.get_task(job_id)
    assert task is not None


