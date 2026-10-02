"""Live intelligence service: facade over sync + bridge + JARVIS subsystems.

Observe-only by default. Sync records provider data; explicit calls
promote (trusted apply), notify (proactive), route (dots), propose
(missions), and remember (memory). Nothing here auto-executes tools,
auto-approves actions, or writes canonical state on its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.types import now as _now
from ...security.guards import is_safe_url, sanitize_for_context, scan_injection
from .models import LiveConfig
from .normalize import to_geo_observation
from .query import by_kind, nearest, summarize, within_radius
from .sync import SyncEngine


class LiveIntelligenceService:
    """Owns live state file + coordinates bridge and subsystem hooks."""

    def __init__(self, home: str | Path, *,
                 config: LiveConfig | None = None,
                 bridge: Any | None = None,
                 world_registry: Any | None = None,
                 spatial: Any | None = None,
                 proactive: Any | None = None,
                 dots: Any | None = None,
                 missions: Any | None = None,
                 palace: Any | None = None,
                 engine: SyncEngine | None = None) -> None:
        self.home = Path(home)
        self.config = config or LiveConfig()
        self.bridge = bridge
        self.world_registry = world_registry
        self.spatial = spatial
        self.proactive = proactive
        self.dots = dots
        self.missions = missions
        self.palace = palace
        state_path = self.home / self.config.state_path
        self.engine = engine or SyncEngine(state_path, config=self.config)

    # -- observe ---------------------------------------------------------
    def sync(self, provider_names: list[str] | None = None,
             params: dict[str, dict[str, Any]] | None = None,
             *, allow_remote: bool = False,
             force: bool = False) -> dict[str, Any]:
        """Explicit live sync. Emits untrusted proactive signals for alerts."""
        summary = self.engine.sync(provider_names, params,
                                   allow_remote=allow_remote, force=force)
        candidates: list[str] = []
        if self.proactive is not None:
            from ...proactive.engine import ProactiveEvent
            for alert in self.engine.alerts[-summary.get("alerts", 0):] or []:
                try:
                    event = ProactiveEvent(
                        type="world_changed", source="gods-eye-live",
                        entity=alert.title, summary=alert.detail,
                        payload={"kind": alert.kind, "severity": alert.severity,
                                 "provider": alert.provider,
                                 "observation_key": alert.observation_key},
                        confidence=0.6,
                        provenance={"observer": "gods-eye-live",
                                    "provider": alert.provider},
                        trusted=False)
                    candidate = self.proactive.notify(event)
                    if candidate is not None:
                        candidates.append(candidate.candidate_id)
                except Exception:
                    continue
        summary["proactive_candidates"] = candidates
        return summary

    def query(self, latitude: float, longitude: float, radius_km: float = 500.0,
              kind: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Deterministic radius/kind query over cached live records."""
        records = self.engine.all()
        if kind:
            records = by_kind(records, kind)
            ranked = within_radius(records, latitude, longitude, radius_km)
        else:
            ranked = nearest(records, latitude, longitude, limit=len(records))
            ranked = [(o, d) for o, d in ranked if d <= radius_km]
        out = [{"key": obs.key(), "kind": obs.kind, "name": obs.name,
                "latitude": obs.latitude, "longitude": obs.longitude,
                "distance_km": round(dist, 2), "provider": obs.provider,
                "confidence": obs.confidence, "attributes": obs.attributes}
               for obs, dist in ranked[: max(0, limit)]]
        return out

    def describe(self, latitude: float, longitude: float,
                 radius_km: float = 500.0, limit: int = 10) -> str:
        """Sanitized human/machine summary. External text stays quoted."""
        rows = self.query(latitude, longitude, radius_km, limit=limit)
        if not rows:
            return "no live records cached in range."
        lines = [f"- {r['kind']}: {r['name']} ({r['distance_km']} km, {r['provider']})"
                 for r in rows]
        return sanitize_for_context("\n".join(lines))

    # -- explicit promotion -----------------------------------------------
    def promote(self, observation_key: str, *, approved: bool = False,
                by: str = "user") -> dict[str, Any]:
        """Ingest-then-apply one live record. Requires explicit approval."""
        if self.bridge is None:
            raise RuntimeError("no God's Eye bridge bound")
        live = self.engine.observations.get(observation_key)
        if live is None:
            raise KeyError(f"unknown live observation: {observation_key}")
        if not approved:
            raise PermissionError(
                "live data is untrusted; promotion needs approved=True")
        geo = to_geo_observation(live)
        stored = self.bridge.get(geo.id)
        if stored is None:
            stored = self.bridge.ingest(geo)
        stored.trusted = True
        self.bridge.history.append({"event": "live-promoted",
                                    "id": stored.id,
                                    "live_key": observation_key,
                                    "by": by, "at": _now()})
        result = self.bridge.apply(stored.id)
        if self.palace is not None:
            try:
                self.palace.store_fact(
                    f"promoted live {live.kind} {live.name} ({live.provider})",
                    source="gods-eye-live", confidence=live.confidence,
                    provenance="live-promotion")
            except Exception:
                pass
        return result

    # -- subsystem hooks (propose only) --------------------------------------
    def route_dots(self, event: dict[str, Any]) -> list[str]:
        """Fan one normalized event out to subscribed Dots. No execution."""
        if self.dots is None:
            return []
        scan = scan_injection(str(event.get("summary", "")))
        if not scan["clean"]:
            return []
        try:
            return list(self.dots.route_event(event))
        except Exception:
            return []

    def propose_mission(self, title: str, reason: str, *,
                        source: str = "event",
                        source_refs: list[str] | None = None,
                        priority: int = 5) -> Any:
        """Create a PROPOSED mission proposal. Never a mission, never runs."""
        if self.missions is None:
            raise RuntimeError("no mission manager bound")
        from ...missions.proposals import (MissionProposal, ProposalStatus,
                                           proposal_dedup_key)
        proposal = MissionProposal(
            title=title[:160], description=reason[:500], reason=reason[:500],
            source=source, source_refs=list(source_refs or []),
            priority=priority, confidence=0.55,
            uncertainty=["live data is observational, not authoritative"],
            provenance={"observer": "gods-eye-live"},
            dedup_key=proposal_dedup_key("gods-eye-live", title, reason, "live"))
        proposal.transition(ProposalStatus.PROPOSED)
        return self.missions.save_proposal(proposal)

    def remember_summary(self, text: str) -> Any:
        """Store one observation-tier memory. Raw sync summaries only."""
        if self.palace is None:
            raise RuntimeError("no memory palace bound")
        return self.palace.store_observation(sanitize_for_context(text, 500),
                                             source="gods-eye-live",
                                             confidence=0.6)

    # -- status / doctor / persistence ------------------------------------------
    def status(self) -> dict[str, Any]:
        engine = self.engine.status()
        engine["summary"] = summarize(self.engine.all())
        engine["state_path"] = str(self.engine.path)
        return engine

    def doctor(self) -> list[dict[str, Any]]:
        """Offline checks: config, state path, provider URL safety, errors."""
        checks: list[dict[str, Any]] = [{
            "name": "live:enabled", "ok": bool(self.config.enabled),
            "detail": "enabled" if self.config.enabled else "disabled by config"}]
        try:
            self.engine.path.parent.mkdir(parents=True, exist_ok=True)
            checks.append({"name": "live:state-path", "ok": True,
                           "detail": str(self.engine.path)})
        except OSError as exc:
            checks.append({"name": "live:state-path", "ok": False, "detail": str(exc)})
        for name, spec in self.engine.providers.items():
            if not self.config.providers.get(name, True):
                continue
            try:
                probe_params: dict[str, Any] = {"q": "test"} if name == "photon-places" else {}
                url = spec.build_url(probe_params)
            except Exception as exc:
                checks.append({"name": f"live:{name}", "ok": False,
                               "detail": f"bad URL: {exc}"})
                continue
            ok, reason = is_safe_url(url)
            checks.append({"name": f"live:{name}", "ok": ok,
                           "detail": "ok" if ok else reason})
        for name, error in self.engine.last_error.items():
            checks.append({"name": f"live:last-error:{name}", "ok": False,
                           "detail": error})
        return checks

    def save(self) -> None:
        self.engine.save()
