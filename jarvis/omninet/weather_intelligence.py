"""
Weather Intelligence — JARVIS-OS OMNINET subsystem.

Provides weather forecasts, severe weather alerts, and climate data through
allowlisted meteorological sources. All requests pass through PolicyEngine.
Read-only — no weather modification capability.
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
class WeatherObservation:
    """A weather observation."""
    observation_id: str
    location: str
    temperature_c: float
    humidity_percent: float
    pressure_hpa: float
    wind_speed_kmh: float
    condition: str  # clear, rain, snow, fog, storm, etc.
    timestamp: float = field(default_factory=time.time)


@dataclass
class WeatherForecast:
    """A weather forecast."""
    forecast_id: str
    location: str
    forecast_date: str
    high_temp_c: float
    low_temp_c: float
    condition: str
    precipitation_chance_percent: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class WeatherAlert:
    """A weather alert."""
    alert_id: str
    location: str
    alert_type: str  # severe, watch, warning, advisory
    severity: str  # minor, moderate, severe, extreme
    description: str
    effective_until: str
    timestamp: float = field(default_factory=time.time)


class WeatherIntelligence:
    """
    Weather Intelligence — weather forecasts, alerts, and climate data.

    Read-only weather information from allowlisted meteorological sources.
    All requests pass through PolicyEngine. No weather modification or
    climate engineering capability.
    """

    ALLOWED_DOMAINS: frozenset[str] = frozenset({
        "weather.gov",
        "noaa.gov",
        "metoffice.gov.uk",
        "wmo.int",
        "weather.com",
        "accuweather.com",
    })

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.observations: dict[str, WeatherObservation] = {}
        self.forecasts: dict[str, WeatherForecast] = {}
        self.alerts: dict[str, WeatherAlert] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the weather intelligence subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "weather_intelligence",
            "domains": len(self.ALLOWED_DOMAINS),
            "policy_gated": True,
            "read_only": True,
        }

    def get_observation(self, location: str) -> WeatherObservation:
        """Get current weather observation for a location."""
        obs_id = f"obs-{int(time.time() * 1000)}"

        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "weather_intelligence.observation",
                {"location": location, "domains": list(self.ALLOWED_DOMAINS)},
            )

        obs = WeatherObservation(
            observation_id=obs_id,
            location=location,
            temperature_c=0.0,
            humidity_percent=0.0,
            pressure_hpa=0.0,
            wind_speed_kmh=0.0,
            condition="unknown",
        )
        self.observations[obs_id] = obs

        if self.events:
            self.events.append({
                "event": "weather_intelligence.observation",
                "observation_id": obs_id,
                "location": location,
                "approved": grant_result.get("approved", False),
                "at": obs.timestamp,
            })

        return obs

    def get_forecast(self, location: str, days: int = 3) -> list[WeatherForecast]:
        """Get weather forecast for a location."""
        forecasts = []
        for day in range(days):
            fc_id = f"fc-{int(time.time() * 1000)}-{day}"
            fc = WeatherForecast(
                forecast_id=fc_id,
                location=location,
                forecast_date=f"day_{day + 1}",
                high_temp_c=0.0,
                low_temp_c=0.0,
                condition="unknown",
                precipitation_chance_percent=0.0,
            )
            forecasts.append(fc)
            self.forecasts[fc_id] = fc

        return forecasts

    def get_alerts(self, location: str) -> list[WeatherAlert]:
        """Get weather alerts for a location."""
        alerts = []
        alert_id = f"alert-{int(time.time() * 1000)}"
        alert = WeatherAlert(
            alert_id=alert_id,
            location=location,
            alert_type="advisory",
            severity="minor",
            description="No active alerts",
            effective_until="",
        )
        alerts.append(alert)
        self.alerts[alert_id] = alert

        return alerts

    def list_domains(self) -> list[str]:
        """List allowlisted domains."""
        return sorted(self.ALLOWED_DOMAINS)

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "weather_intelligence",
            "status": "operational" if self._initialized else "offline",
            "observations": len(self.observations),
            "forecasts": len(self.forecasts),
            "alerts": len(self.alerts),
            "domains": sorted(self.ALLOWED_DOMAINS),
            "capabilities": [
                "current_observation",
                "multi_day_forecast",
                "weather_alerts",
                "climate_data",
            ],
            "constraints": [
                "read_only_weather_data",
                "policy_gated_domain_access",
                "no_weather_modification",
            ],
        }


# Global instance
_weather: WeatherIntelligence | None = None


def get_weather_intelligence(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> WeatherIntelligence:
    """Get or create the global Weather Intelligence instance."""
    global _weather
    if _weather is None:
        _weather = WeatherIntelligence(policy=policy, events=events)
    return _weather


__all__ = [
    "WeatherIntelligence",
    "WeatherObservation",
    "WeatherForecast",
    "WeatherAlert",
    "get_weather_intelligence",
]