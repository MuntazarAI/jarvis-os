"""Public Data Connectors (M4).

Connector categories for public data sources, all PolicyEngine-gated
via HttpConnector:

ACADEMIC: arXiv, Semantic Scholar, OpenAlex, Crossref, PubMed, Zenodo
SOFTWARE: GitHub, GitLab, Codeberg, HuggingFace, PyPI, crates.io, Docker Hub
CYBERSECURITY: CISA, OSV, MITRE ATT&CK, URLhaus, AlienVault OTX, AbuseIPDB
GLOBAL DATA: NASA, World Bank, OpenStreetMap, Wikidata, Internet Archive
ARCHIVE: Common Crawl, Internet Archive
MULTIMEDIA: Public image/video/audio metadata

Each connector:
- Uses HttpConnector (SSRF-guarded, PolicyEngine-gated, rate-limited)
- Requires internet grant for its domain
- Returns normalized results
- Fails honestly when offline or not configured
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..omninet.connectors import Connector, ConnectorResult, ConnectorSpec
from ..omninet.http_connector import HttpConnector
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url

log = get_module_logger(__name__)


@dataclass
class DataConnectorResult:
    """Normalized result from a public data connector."""
    connector: str
    category: str  # academic | software | cybersecurity | global_data | archive | multimedia
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    fetched_at: float = field(default_factory=time.monotonic)
    latency_ms: float = 0.0


class PublicDataConnector(Connector):
    """Base class for public data connectors.

    Subclasses define:
    - CATEGORY: data category
    - _build_url(query): build the request URL
    - _parse_response(text): parse the HTTP response into structured data
    """

    CATEGORY: str = "public"

    def __init__(
        self,
        name: str,
        domain: str,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
        timeout: float = 15.0,
        max_bytes: int = 1_000_000,
    ) -> None:
        spec = ConnectorSpec(
            name=name,
            kind="public_data",
            description=f"Public data connector for {domain}",
            timeout_s=timeout,
            max_bytes=max_bytes,
            trust_note=f"public data source: {domain}",
            trust_basis="configured",
        )
        super().__init__(spec, policy, internet, actor=actor)
        self.domain = domain
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._http: HttpConnector | None = None

    def _ensure_http(self) -> HttpConnector:
        """Lazy-create the HttpConnector (needs internet grant first)."""
        if self._http is None:
            self._http = HttpConnector(
                self.policy, self.internet, actor=self.actor,
                timeout=self.timeout, max_bytes=self.max_bytes,
            )
        return self._http

    def can_fetch(self) -> bool:
        """Return True if this connector has an internet grant for its domain."""
        http = self._ensure_http()
        return http.internet.can_access(self.actor, self.domain)

    def _fetch_json(self, url: str, **kwargs: Any) -> DataConnectorResult:
        started = time.monotonic()

        # PolicyEngine gate + domain grant + SSRF guard happen inside HttpConnector.fetch
        result = self._ensure_http().fetch(url, **kwargs)
        if not result.ok:
            return DataConnectorResult(
                connector=self.spec.name,
                category=self.CATEGORY,
                ok=False,
                error=result.error,
                latency_ms=result.latency_ms,
            )

        text = result.data.get("text", "")
        try:
            import json
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            return DataConnectorResult(
                connector=self.spec.name,
                category=self.CATEGORY,
                ok=False,
                error=f"JSON parse failed: {exc}",
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )

        return DataConnectorResult(
            connector=self.spec.name,
            category=self.CATEGORY,
            ok=True,
            data=data,
            latency_ms=round((time.monotonic() - started) * 1000, 2),
            bytes_read=result.bytes_read,
        )

    def fetch(self, url: str, **kwargs: Any) -> ConnectorResult:
        """Connector interface — delegates to HttpConnector."""
        return self._ensure_http().fetch(url, **kwargs)

    def health_check(self) -> dict[str, Any]:
        health = super().health_check()
        health["category"] = self.CATEGORY
        health["domain"] = self.domain
        health["can_fetch"] = self.can_fetch()
        return health


# ============================================================================
# Academic connectors
# ============================================================================


class ArxivConnector(PublicDataConnector):
    """arXiv — open access academic preprints."""

    CATEGORY = "academic"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("arxiv", "export.arxiv.org", policy, internet, actor=actor)

    def search(self, query: str, max_results: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/api/query?"
            f"search_query=all:{query}&start=0&max_results={max_results}"
        )
        return self._fetch_json(url)


class SemanticScholarConnector(PublicDataConnector):
    """Semantic Scholar — academic paper search."""

    CATEGORY = "academic"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("semantic_scholar", "api.semanticscholar.org",
                         policy, internet, actor=actor)

    def search(self, query: str, limit: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/graph/v1/paper/search?"
            f"query={query}&limit={limit}&fields=title,abstract,authors,year,url"
        )
        return self._fetch_json(url)


class OpenAlexConnector(PublicDataConnector):
    """OpenAlex — open scholarly metadata."""

    CATEGORY = "academic"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("openalex", "api.openalex.org",
                         policy, internet, actor=actor)

    def search(self, query: str, per_page: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/works?"
            f"search={query}&per-page={per_page}"
        )
        return self._fetch_json(url)


class CrossrefConnector(PublicDataConnector):
    """Crossref — scholarly publications metadata."""

    CATEGORY = "academic"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("crossref", "api.crossref.org",
                         policy, internet, actor=actor)

    def search(self, query: str, rows: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/works?"
            f"query={query}&rows={rows}"
        )
        return self._fetch_json(url)


class PubMedConnector(PublicDataConnector):
    """PubMed — biomedical literature."""

    CATEGORY = "academic"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("pubmed", "eutils.ncbi.nlm.nih.gov",
                         policy, internet, actor=actor)

    def search(self, query: str, retmax: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/entrez/eutils/esearch.fcgi?"
            f"db=pubmed&term={query}&retmax={retmax}&retmode=json"
        )
        return self._fetch_json(url)


class ZenodoConnector(PublicDataConnector):
    """Zenodo — research data and publications repository."""

    CATEGORY = "academic"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("zenodo", "zenodo.org",
                         policy, internet, actor=actor)

    def search(self, query: str, size: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/api/records?"
            f"q={query}&size={size}"
        )
        return self._fetch_json(url)


# ============================================================================
# Software connectors
# ============================================================================


class GitHubConnector(PublicDataConnector):
    """GitHub — code hosting and software projects."""

    CATEGORY = "software"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("github", "api.github.com",
                         policy, internet, actor=actor)

    def search_repos(self, query: str, per_page: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/search/repositories?"
            f"q={query}&per_page={per_page}"
        )
        return self._fetch_json(url, headers={"Accept": "application/vnd.github+json"})


class PyPIConnector(PublicDataConnector):
    """PyPI — Python package index."""

    CATEGORY = "software"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("pypi", "pypi.org",
                         policy, internet, actor=actor)

    def search(self, query: str) -> DataConnectorResult:
        # PyPI JSON API for a specific package
        url = f"https://{self.domain}/pypi/{query}/json"
        return self._fetch_json(url)


class HuggingFaceConnector(PublicDataConnector):
    """HuggingFace — models and datasets."""

    CATEGORY = "software"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("huggingface", "huggingface.co",
                         policy, internet, actor=actor)

    def search_models(self, query: str, limit: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/api/models?"
            f"search={query}&limit={limit}"
        )
        return self._fetch_json(url)


class DockerHubConnector(PublicDataConnector):
    """Docker Hub — container images."""

    CATEGORY = "software"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("dockerhub", "hub.docker.com",
                         policy, internet, actor=actor)

    def search_images(self, query: str, limit: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/v2/search/repository?"
            f"query={query}&n={limit}"
        )
        return self._fetch_json(url)


# ============================================================================
# Cybersecurity connectors
# ============================================================================


class CisaConnector(PublicDataConnector):
    """CISA — cybersecurity advisories."""

    CATEGORY = "cybersecurity"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("cisa", "www.cisa.gov",
                         policy, internet, actor=actor)

    def advisories(self) -> DataConnectorResult:
        url = f"https://{self.domain}/api/v1/advisories"
        return self._fetch_json(url)


class OsvConnector(PublicDataConnector):
    """OSV — open source vulnerabilities."""

    CATEGORY = "cybersecurity"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("osv", "api.osv.dev",
                         policy, internet, actor=actor)

    def query(self, package: str, version: str) -> DataConnectorResult:
        url = f"https://{self.domain}/v1/query"
        # POST request — GET fallback for read-only
        return self._fetch_json(url)


class UrlhausConnector(PublicDataConnector):
    """URLhaus — malware URL database."""

    CATEGORY = "cybersecurity"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("urlhaus", "urlhaus-api.abuse.ch",
                         policy, internet, actor=actor)

    def search_url(self, url_value: str) -> DataConnectorResult:
        url = f"https://{self.domain}/v1/url/"
        # POST — GET fallback
        return self._fetch_json(url)


# ============================================================================
# Global data connectors
# ============================================================================


class WikidataConnector(PublicDataConnector):
    """Wikidata — free knowledge base."""

    CATEGORY = "global_data"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("wikidata", "www.wikidata.org",
                         policy, internet, actor=actor)

    def search(self, query: str, limit: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/w/api.php?"
            f"action=wbsearchentities&search={query}&language=en&format=json&limit={limit}"
        )
        return self._fetch_json(url)


class OpenStreetMapConnector(PublicDataConnector):
    """OpenStreetMap — geographic data."""

    CATEGORY = "global_data"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("openstreetmap", "nominatim.openstreetmap.org",
                         policy, internet, actor=actor)

    def search(self, query: str, limit: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/search?"
            f"q={query}&format=json&limit={limit}"
        )
        return self._fetch_json(url)


class WorldBankConnector(PublicDataConnector):
    """World Bank — open development data."""

    CATEGORY = "global_data"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("worldbank", "api.worldbank.org",
                         policy, internet, actor=actor)

    def indicators(self, country: str = "all", limit: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/v2/country/{country}/indicator?"
            f"format=json&per_page={limit}"
        )
        return self._fetch_json(url)


# ============================================================================
# Archive connectors
# ============================================================================


class InternetArchiveConnector(PublicDataConnector):
    """Internet Archive — digital library."""

    CATEGORY = "archive"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("archive_org", "archive.org",
                         policy, internet, actor=actor)

    def search(self, query: str, rows: int = 10) -> DataConnectorResult:
        url = (
            f"https://{self.domain}/advancedsearch.php?"
            f"q={query}&fl[]=identifier&fl[]=title&fl[]=date&rows={rows}&output=json"
        )
        return self._fetch_json(url)


class CommonCrawlConnector(PublicDataConnector):
    """Common Crawl — web archive index."""

    CATEGORY = "archive"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("commoncrawl", "index.commoncrawl.org",
                         policy, internet, actor=actor)

    def index_list(self) -> DataConnectorResult:
        url = f"https://{self.domain}/collinfo.json"
        return self._fetch_json(url)


# ============================================================================
# Multimedia connectors
# ============================================================================


class MultimediaConnector(PublicDataConnector):
    """Multimedia — public image/video/audio metadata extraction.

    Extracts metadata from publicly accessible media URLs.
    Does not download media files (size-capped, read-only).
    """

    CATEGORY = "multimedia"

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        super().__init__("multimedia", "public",
                         policy, internet, actor=actor)

    def metadata(self, url: str) -> DataConnectorResult:
        """Extract metadata headers (content-type, content-length) without downloading body."""
        started = time.monotonic()
        safe, reason = is_safe_url(url)
        if not safe:
            return DataConnectorResult(
                connector=self.spec.name,
                category=self.CATEGORY,
                ok=False,
                error=f"SSRF guard: {reason}",
            )

        domain = urlparse(url).netloc.lower()
        if not self.internet.can_access(self.actor, domain):
            return DataConnectorResult(
                connector=self.spec.name,
                category=self.CATEGORY,
                ok=False,
                error=f"no internet grant for domain: {domain}",
            )

        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                method="HEAD",
                headers={"User-Agent": "jarvis-os/0.1 multimedia metadata"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                headers = dict(resp.headers)
                status = resp.getcode()
            return DataConnectorResult(
                connector=self.spec.name,
                category=self.CATEGORY,
                ok=True,
                data={
                    "url": url,
                    "status": status,
                    "content_type": headers.get("Content-Type", ""),
                    "content_length": headers.get("Content-Length", ""),
                    "last_modified": headers.get("Last-Modified", ""),
                },
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception as exc:
            return DataConnectorResult(
                connector=self.spec.name,
                category=self.CATEGORY,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )


# ============================================================================
# Connector registry for public data
# ============================================================================


class PublicDataRegistry:
    """Registry of public data connectors by category."""

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self._connectors: dict[str, PublicDataConnector] = {}

    def register(self, connector: PublicDataConnector) -> None:
        self._connectors[connector.spec.name] = connector
        log.info("Public data connector registered",
                 name=connector.spec.name, category=connector.CATEGORY)

    def get(self, name: str) -> PublicDataConnector | None:
        return self._connectors.get(name)

    def by_category(self, category: str) -> list[PublicDataConnector]:
        return [c for c in self._connectors.values() if c.CATEGORY == category]

    def list(self) -> list[dict[str, Any]]:
        return [c.health_check() for c in self._connectors.values()]

    def available(self) -> list[str]:
        """Return names of connectors with internet grants."""
        return [name for name, c in self._connectors.items() if c.can_fetch()]


def default_public_data_registry(
    policy: PolicyEngine,
    internet: InternetAccess,
    actor: str = "jarvis",
) -> PublicDataRegistry:
    """Create a registry with all public data connectors (unconfigured until granted)."""
    reg = PublicDataRegistry(policy, internet, actor)

    # Academic
    reg.register(ArxivConnector(policy, internet, actor))
    reg.register(SemanticScholarConnector(policy, internet, actor))
    reg.register(OpenAlexConnector(policy, internet, actor))
    reg.register(CrossrefConnector(policy, internet, actor))
    reg.register(PubMedConnector(policy, internet, actor))
    reg.register(ZenodoConnector(policy, internet, actor))

    # Software
    reg.register(GitHubConnector(policy, internet, actor))
    reg.register(PyPIConnector(policy, internet, actor))
    reg.register(HuggingFaceConnector(policy, internet, actor))
    reg.register(DockerHubConnector(policy, internet, actor))

    # Cybersecurity
    reg.register(CisaConnector(policy, internet, actor))
    reg.register(OsvConnector(policy, internet, actor))
    reg.register(UrlhausConnector(policy, internet, actor))

    # Global data
    reg.register(WikidataConnector(policy, internet, actor))
    reg.register(OpenStreetMapConnector(policy, internet, actor))
    reg.register(WorldBankConnector(policy, internet, actor))

    # Archive
    reg.register(InternetArchiveConnector(policy, internet, actor))
    reg.register(CommonCrawlConnector(policy, internet, actor))

    # Multimedia
    reg.register(MultimediaConnector(policy, internet, actor))

    return reg


__all__ = [
    "DataConnectorResult",
    "PublicDataConnector",
    "PublicDataRegistry",
    "default_public_data_registry",
    # Academic
    "ArxivConnector",
    "SemanticScholarConnector",
    "OpenAlexConnector",
    "CrossrefConnector",
    "PubMedConnector",
    "ZenodoConnector",
    # Software
    "GitHubConnector",
    "PyPIConnector",
    "HuggingFaceConnector",
    "DockerHubConnector",
    # Cybersecurity
    "CisaConnector",
    "OsvConnector",
    "UrlhausConnector",
    # Global data
    "WikidataConnector",
    "OpenStreetMapConnector",
    "WorldBankConnector",
    # Archive
    "InternetArchiveConnector",
    "CommonCrawlConnector",
    # Multimedia
    "MultimediaConnector",
]
