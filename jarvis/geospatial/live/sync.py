"""Manual sync engine: fetch → parse → store → track → alert.

No background threads, no polling. Every sync is an explicit caller
action (CLI, API, or test). TTL caching avoids hammering anonymous
rate-limited endpoints; `force=True` bypasses the cache. Persistence is
atomic JSON (tmp file + replace), mirroring the bridge pattern.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ...core.types import now as _now
from .client import BoundedHttpClient, LiveHttpError
from .models import LiveAlert, LiveConfig, LiveObservation, clean_text
from .providers import LiveDataError, ProviderSpec, default_providers
from .tracker import EntityTracker


def _alert_for(obs: LiveObservation) -> LiveAlert | None:
    """Deterministic severity thresholds. Returns None when not notable."""
    if obs.kind == "earthquake":
        mag = obs.attributes.get("magnitude")
        if isinstance(mag, (int, float)) and mag >= 6.0:
            return LiveAlert(kind="earthquake", severity="critical" if mag >= 7 else "high",
                             title=f"M{mag} earthquake: {obs.name}",
                             detail=f"magnitude {mag}, depth {obs.attributes.get('depth_km')} km",
                             observation_key=obs.key(), provider=obs.provider)
    elif obs.kind == "cyclone":
        intensity = obs.attributes.get("intensity_kt")
        if isinstance(intensity, (int, float)) and intensity >= 64:
            return LiveAlert(kind="cyclone", severity="high",
                             title=f"Hurricane-strength cyclone: {obs.name}",
                             detail=f"{intensity} kt, {obs.attributes.get('pressure_mb')} mb",
                             observation_key=obs.key(), provider=obs.provider)
    elif obs.kind == "wildfire":
        size = obs.attributes.get("size_acres")
        contained = obs.attributes.get("percent_contained")
        if isinstance(size, (int, float)) and size >= 10000:
            return LiveAlert(kind="wildfire", severity="high",
                             title=f"Large wildfire: {obs.name}",
                             detail=f"{size} acres, {contained}% contained",
                             observation_key=obs.key(), provider=obs.provider)
        if isinstance(contained, (int, float)) and contained < 10 and size:
            return LiveAlert(kind="wildfire", severity="elevated",
                             title=f"Uncontained wildfire: {obs.name}",
                             detail=f"{size} acres, {contained}% contained",
                             observation_key=obs.key(), provider=obs.provider)
    return None


class SyncEngine:
    """Explicit, cached, bounded live-data sync."""

    def __init__(self, path: str | Path | None = None, *,
                 config: LiveConfig | None = None,
                 client: BoundedHttpClient | None = None,
                 providers: dict[str, ProviderSpec] | None = None) -> None:
        self.config = config or LiveConfig()
        self.path = Path(path) if path else Path(self.config.state_path)
        self.client = client or BoundedHttpClient(
            timeout_s=self.config.timeout_s, max_bytes=self.config.max_bytes)
        self.providers = providers or default_providers()
        self.tracker = EntityTracker(max_points=self.config.max_track_points,
                                     ttl_s=self.config.track_ttl_s)
        self.observations: dict[str, LiveObservation] = {}
        self.last_sync: dict[str, float] = {}
        self.last_error: dict[str, str] = {}
        self.alerts: list[LiveAlert] = []
        self._load()

    # -- persistence ---------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, raw in (data.get("observations") or {}).items():
            try:
                self.observations[key] = LiveObservation.from_dict(raw)
            except (TypeError, ValueError, KeyError):
                continue
        try:
            self.tracker = EntityTracker.from_dict(data.get("tracker") or {})
        except (TypeError, ValueError, KeyError):
            pass
        self.last_sync = {k: float(v) for k, v in (data.get("last_sync") or {}).items()
                          if isinstance(v, (int, float))}
        self.last_error = {k: str(v) for k, v in (data.get("last_error") or {}).items()}
        for raw in (data.get("alerts") or [])[-200:]:
            try:
                self.alerts.append(LiveAlert.from_dict(raw))
            except (TypeError, ValueError, KeyError):
                continue

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "observations": {k: v.to_dict() for k, v in self.observations.items()},
            "tracker": self.tracker.to_dict(),
            "last_sync": self.last_sync,
            "last_error": self.last_error,
            "alerts": [a.to_dict() for a in self.alerts[-200:]],
        }
        fd, tmp = tempfile.mkstemp(prefix=".gods-eye-live-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- sync ------------------------------------------------------------
    def sync(self, provider_names: list[str] | None = None,
             params: dict[str, dict[str, Any]] | None = None,
             *, allow_remote: bool = False, force: bool = False,
             at: float | None = None) -> dict[str, Any]:
        """Fetch and store. Explicit remote consent required per call."""
        if not self.config.enabled:
            raise RuntimeError("live God's Eye intelligence is disabled")
        if not (allow_remote or self.config.allow_remote):
            raise RuntimeError(
                "live sync performs network egress; pass allow_remote=True "
                "(CLI: --allow-remote) to consent explicitly")
        stamp = at if at is not None else _now()
        params = params or {}
        names = provider_names or sorted(self.providers)
        summary: dict[str, Any] = {"providers": {}, "ingested": 0, "alerts": 0}
        for name in names:
            spec = self.providers.get(name)
            if spec is None:
                summary["providers"][name] = {"ok": False, "error": "unknown provider"}
                continue
            if not self.config.providers.get(name, True):
                summary["providers"][name] = {"ok": False, "error": "disabled by config"}
                continue
            age = stamp - self.last_sync.get(name, 0.0)
            if not force and age < spec.ttl_s and name in self.last_sync:
                summary["providers"][name] = {"ok": True, "cached": True,
                                              "age_s": round(age, 1)}
                continue
            try:
                url = spec.build_url(params.get(name))
                raw = self.client.fetch_json(url)
                records = [r for r in spec.parse(raw, stamp)
                           if r.confidence >= self.config.min_confidence]
                for obs in records:
                    self.observations[obs.key()] = obs
                    self.tracker.observe(obs, at=stamp)
                    alert = _alert_for(obs)
                    if alert is not None:
                        self.alerts.append(alert)
                        summary["alerts"] += 1
                self._enforce_bounds()
                self.last_sync[name] = stamp
                self.last_error.pop(name, None)
                summary["providers"][name] = {"ok": True, "cached": False,
                                              "records": len(records),
                                              "url": url}
                summary["ingested"] += len(records)
            except (LiveHttpError, LiveDataError, ValueError) as exc:
                self.last_error[name] = clean_text(str(exc), 200)
                summary["providers"][name] = {"ok": False,
                                              "error": self.last_error[name]}
        self.save()
        return summary

    def _enforce_bounds(self) -> None:
        while len(self.observations) > self.config.max_observations:
            oldest_key = min(self.observations,
                             key=lambda k: self.observations[k].observed_at)
            del self.observations[oldest_key]

    # -- read --------------------------------------------------------------
    def all(self) -> list[LiveObservation]:
        return sorted(self.observations.values(),
                      key=lambda o: (o.observed_at, o.name))

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "observations": len(self.observations),
            "tracks": len(self.tracker.tracks),
            "alerts": len(self.alerts),
            "last_sync": dict(self.last_sync),
            "last_error": dict(self.last_error),
            "providers": {
                name: {"enabled": self.config.providers.get(name, True),
                       "kinds": list(spec.kinds),
                       "ttl_s": spec.ttl_s,
                       "attribution": spec.attribution,
                       "license": spec.license}
                for name, spec in self.providers.items()
            },
        }
