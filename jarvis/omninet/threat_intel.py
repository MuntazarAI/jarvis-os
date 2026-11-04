"""Privacy and Defensive Threat Research (M9).

Defensive, educational research subsystem for privacy networks and
threat intelligence. Strictly defensive:

ALLOWED:
- Tor/onion routing research from published reports
- I2P, Lokinet, IPFS, ActivityPub, Matrix, Nostr research
- Encryption and privacy protocol analysis
- CVE monitoring and public IOC analysis
- Authorized breach-notification sources

FORBIDDEN (never implemented):
- Criminal marketplace access
- Stolen credential collection
- Stolen database acquisition
- Illegal goods procurement
- Unauthorized private-system access
- Circumvention of access restrictions

All research is isolated from personal data and the main OS.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import ActionPlan, RiskLevel, now
from ..omninet.http_connector import HttpConnector
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url

log = get_module_logger(__name__)


@dataclass
class ThreatIndicator:
    """A defensive threat indicator (IOC, CVE, etc.)."""
    indicator_id: str
    type: str  # cve | ioc | malware | url | domain | ip | advisory
    value: str
    description: str = ""
    source: str = ""
    severity: str = "medium"  # low | medium | high | critical
    confidence: float = 0.5
    published_at: float = 0.0
    retrieved_at: float = field(default_factory=now)
    tags: list[str] = field(default_factory=list)
    is_defensive: bool = True  # always True — defensive only

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator_id": self.indicator_id,
            "type": self.type,
            "value": self.value,
            "description": self.description,
            "source": self.source,
            "severity": self.severity,
            "confidence": self.confidence,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "tags": self.tags,
            "is_defensive": self.is_defensive,
        }


@dataclass
class PrivacyNetworkReport:
    """Report on a privacy network (Tor, I2P, etc.) — educational only."""
    network: str
    description: str
    how_it_works: str
    defensive_use_cases: list[str]
    limitations: list[str]
    sources: list[str]
    generated_at: float = field(default_factory=now)


class PrivacyResearch:
    """Defensive privacy network research.

    Analyzes reputable published reports about privacy networks,
    encryption, and decentralized networking. No access to criminal
    marketplaces or stolen data.
    """

    PRIVACY_NETWORKS = {
        "tor": {
            "description": "The Onion Router — anonymizing network that routes traffic through multiple relays",
            "defensive_uses": [
                "Protecting whistleblowers and journalists",
                "Evading censorship in restricted regions",
                "Researching traffic analysis resistance",
            ],
            "limitations": [
                "Exit node traffic can be observed",
                "Not a guarantee of complete anonymity",
                "Can be used for both defensive and offensive purposes",
            ],
        },
        "i2p": {
            "description": "Invisible Internet Project — peer-to-peer anonymous network layer",
            "defensive_uses": [
                "Secure peer-to-peer communication",
                "Resisting traffic correlation attacks",
            ],
            "limitations": [
                "Smaller network than Tor",
                "Limited exit node infrastructure",
            ],
        },
        "ipfs": {
            "description": "InterPlanetary File System — content-addressed, decentralized storage",
            "defensive_uses": [
                "Censorship-resistant content distribution",
                "Permanent web archiving",
            ],
            "limitations": [
                "Content persistence depends on pinning",
                "Not anonymous by default",
            ],
        },
        "activitypub": {
            "description": "Decentralized social networking protocol (Mastodon, etc.)",
            "defensive_uses": [
                "Federated communication without central control",
                "Community moderation",
            ],
            "limitations": [
                "Instance administrators can moderate content",
                "Metadata may be visible to instances",
            ],
        },
        "nostr": {
            "description": "Notes and Other Stuff Transmitted by Relays — decentralized identity protocol",
            "defensive_uses": [
                "Censorship-resistant identity and messaging",
                "Client-relay architecture",
            ],
            "limitations": [
                "Relay operators can see metadata",
                "No built-in encryption for all message types",
            ],
        },
    }

    def __init__(self) -> None:
        pass

    def network_report(self, network: str) -> PrivacyNetworkReport:
        """Generate an educational report about a privacy network."""
        net = network.lower()
        if net not in self.PRIVACY_NETWORKS:
            return PrivacyNetworkReport(
                network=network,
                description="Unknown network",
                how_it_works="No information available",
                defensive_use_cases=[],
                limitations=["No data available for this network"],
                sources=[],
            )
        info = self.PRIVACY_NETWORKS[net]
        return PrivacyNetworkReport(
            network=net,
            description=info["description"],
            how_it_works=info["description"],
            defensive_use_cases=info["defensive_uses"],
            limitations=info["limitations"],
            sources=["Published technical documentation"],
        )

    def list_networks(self) -> list[str]:
        return sorted(self.PRIVACY_NETWORKS.keys())


class ThreatIntel:
    """Defensive threat intelligence engine.

    Public CVE monitoring, IOC analysis, vulnerability correlation,
    security advisory analysis. All data from authorized public sources.
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
        self._indicators: dict[str, ThreatIndicator] = {}
        self._indicator_counter: int = 0

    # -- CVE monitoring --------------------------------------------------

    def query_cve(self, cve_id: str) -> ThreatIndicator | None:
        """Query a specific CVE from public sources (NVD, CVE.org)."""
        domain = "nvd.nist.gov"
        if not self.internet.can_access(self.actor, domain):
            log.warning("No internet grant for NVD", domain=domain)
            return None

        url = f"https://{domain}/vuln/detail/{cve_id}"
        safe, reason = is_safe_url(url)
        if not safe:
            log.warning("CVE URL blocked by SSRF guard", cve=cve_id, reason=reason)
            return None

        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "jarvis-os/0.1 defensive threat research"},
            )
            with urllib.request.urlopen(req, timeout=15.0) as resp:  # noqa: S310
                html = resp.read(200_000).decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("CVE query failed", cve=cve_id, error=str(exc)[:120])
            return None

        # Extract basic info from the page (heuristic)
        severity = "unknown"
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            if sev.lower() in html.lower():
                severity = sev.lower()
                break

        self._indicator_counter += 1
        indicator = ThreatIndicator(
            indicator_id=f"cve-{self._indicator_counter}",
            type="cve",
            value=cve_id,
            description=f"CVE {cve_id} — vulnerability reported in NVD",
            source="nvd.nist.gov",
            severity=severity,
            confidence=0.8,
            tags=["cve", "vulnerability", "nvd"],
            is_defensive=True,
        )
        self._indicators[indicator.indicator_id] = indicator
        return indicator

    # -- OSV (Open Source Vulnerabilities) ------------------------------

    def query_osv(self, package: str, version: str | None = None) -> list[ThreatIndicator]:
        """Query OSV database for vulnerabilities in a package."""
        domain = "api.osv.dev"
        if not self.internet.can_access(self.actor, domain):
            log.warning("No internet grant for OSV", domain=domain)
            return []

        url = f"https://{domain}/v1/query"
        import urllib.request
        import json
        data = json.dumps({"package": {"name": package, "ecosystem": "PyPI"},
                           "version": version or "latest"}).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"User-Agent": "jarvis-os/0.1 defensive threat research",
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:  # noqa: S310
                result = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            log.warning("OSV query failed", package=package, error=str(exc)[:120])
            return []

        vulns = result.get("vulns", [])
        indicators: list[ThreatIndicator] = []
        for v in vulns[:10]:  # bounded
            cve_id = v.get("id", "unknown")
            summary = v.get("summary", "")[:200]
            self._indicator_counter += 1
            indicator = ThreatIndicator(
                indicator_id=f"osv-{self._indicator_counter}",
                type="cve",
                value=cve_id,
                description=summary,
                source="osv.dev",
                severity="medium",
                confidence=0.7,
                tags=["osv", "vulnerability", package],
                is_defensive=True,
            )
            self._indicators[indicator.indicator_id] = indicator
            indicators.append(indicator)
        return indicators

    # -- URL reputation --------------------------------------------------

    def check_url_reputation(self, url: str) -> dict[str, Any]:
        """Check a URL against public reputation sources (URLhaus, etc.).

        Defensive only — reports whether a URL is known malicious.
        Does not access the URL itself if flagged.
        """
        domain = url.split("/")[2] if "//" in url else url
        if not self.internet.can_access(self.actor, domain):
            return {"url": url, "error": "no internet grant", "malicious": False}

        safe, reason = is_safe_url(url)
        if not safe:
            return {"url": url, "error": f"SSRF guard: {reason}", "malicious": False}

        result: dict[str, Any] = {
            "url": url,
            "domain": domain,
            "malicious": False,
            "sources": [],
            "confidence": 0.0,
        }

        # Check URLhaus
        try:
            import urllib.request
            import json
            data = json.dumps({"url": url}).encode()
            req = urllib.request.Request(
                "https://urlhaus-api.abuse.ch/v1/url/",
                data=data,
                headers={"User-Agent": "jarvis-os/0.1 defensive threat research",
                         "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15.0) as resp:  # noqa: S310
                response = json.loads(resp.read().decode("utf-8", errors="replace"))
            if response.get("query_status") == "ok":
                result["malicious"] = True
                result["sources"].append("urlhaus")
                result["confidence"] = 0.9
                result["threat_type"] = response.get("threat", "unknown")
                result["blacklist"] = response.get("blacklist", [])
        except Exception:
            pass

        return result

    # -- indicators -----------------------------------------------------

    def add_indicator(self, indicator: ThreatIndicator) -> None:
        """Add a threat indicator manually."""
        self._indicators[indicator.indicator_id] = indicator

    def list_indicators(
        self,
        type: str | None = None,
        min_severity: str | None = None,
    ) -> list[ThreatIndicator]:
        """List threat indicators, optionally filtered."""
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_order.get(min_severity, 0) if min_severity else 0

        results = []
        for ind in self._indicators.values():
            if type is not None and ind.type != type:
                continue
            if min_severity is not None and severity_order.get(ind.severity, 0) < min_level:
                continue
            results.append(ind)
        return results

    def get_indicator(self, indicator_id: str) -> ThreatIndicator | None:
        return self._indicators.get(indicator_id)

    def stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for ind in self._indicators.values():
            by_type[ind.type] = by_type.get(ind.type, 0) + 1
            by_severity[ind.severity] = by_severity.get(ind.severity, 0) + 1
        return {
            "total_indicators": len(self._indicators),
            "by_type": by_type,
            "by_severity": by_severity,
            "all_defensive": all(i.is_defensive for i in self._indicators.values()),
        }


__all__ = [
    "ThreatIndicator",
    "PrivacyNetworkReport",
    "PrivacyResearch",
    "ThreatIntel",
]
