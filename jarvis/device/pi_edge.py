"""Pi edge intelligence: routing, anomaly, prediction, automation (5.0).

Pure, bounded, deterministic helpers over Pi telemetry. No I/O, no
sockets, no execution — they compute recommendations and findings
that the existing policy/service layers authorize and deliver.

- decide_execution_site: RUN_LOCAL | RUN_CORE | RUN_ANDROID |
  RUN_LAPTOP | ASK_HUMAN from explicit inputs.
- AnomalyDetector: bounded per-metric series, threshold + spike
  rules. Returns NORMAL | ANOMALY | UNKNOWN, never a root cause.
- predict_pressure: linear-trend forecasts with confidence/basis.
- evaluate_automation_rules: threshold crossings become ALERT
  events only. Destructive recovery is never emitted.
- replay_events: idempotent offline replay (dedupe by id, keep
  original timestamps and provenance).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from ..world.state import linear_trend

EXECUTION_SITES = (
    "RUN_LOCAL",
    "RUN_CORE",
    "RUN_ANDROID",
    "RUN_LAPTOP",
    "ASK_HUMAN",
)

ANOMALY_SERIES_MAX = 60

#: Metric -> (warn_at, critical_at, unit). Conservative Pi-5 values.
THRESHOLDS: dict[str, tuple[float, float, str]] = {
    "temperature_c": (70.0, 80.0, "C"),
    "disk_percent": (85.0, 95.0, "%"),
    "cpu_percent": (85.0, 95.0, "%"),
    "memory_percent": (85.0, 95.0, "%"),
}


def decide_execution_site(*, capability: str = "",
                          latency_ms: float | None = None,
                          privacy: str = "local",
                          compute: str = "light",
                          network: str = "up",
                          risk: str = "low",
                          authorized: bool = False) -> dict[str, Any]:
    """Explicit routing decision. Pure function, fully inspectable."""
    reasons: list[str] = []
    if not authorized:
        return {"site": "ASK_HUMAN",
                "reasons": ["not authorized: human decision required"]}
    if privacy in ("private", "sensitive"):
        return {"site": "RUN_LOCAL",
                "reasons": [f"privacy {privacy} keeps data on-device"]}
    if risk in ("high",):
        reasons.append("high risk: policy path required")
        return {"site": "RUN_CORE", "reasons": reasons}
    if network in ("down", "unknown"):
        return {"site": "RUN_LOCAL",
                "reasons": [f"network {network}: edge autonomy"]}
    if compute in ("heavy",):
        return {"site": "RUN_CORE",
                "reasons": ["heavy compute exceeds edge budget"]}
    if capability.startswith("device."):
        return {"site": "RUN_ANDROID",
                "reasons": ["android capability belongs to its node"]}
    if capability.startswith("pi."):
        return {"site": "RUN_LOCAL",
                "reasons": ["pi capability served at the edge"] + reasons}
    if latency_ms is not None and latency_ms > 500:
        return {"site": "RUN_LAPTOP",
                "reasons": ["latency budget favors the laptop core"]}
    return {"site": "RUN_LOCAL" if network == "up" else "RUN_CORE",
            "reasons": reasons or ["default: cheapest capable site"]}


class AnomalyDetector:
    """Bounded per-metric anomaly detection. Facts, not diagnoses."""

    def __init__(self, max_points: int = ANOMALY_SERIES_MAX) -> None:
        self.max_points = max(1, max_points)
        self._series: dict[str, deque] = {}
        self.metrics: dict[str, int] = {"points": 0, "anomalies": 0}

    def observe(self, metric: str, value: float,
                at: float = 0.0) -> dict[str, Any]:
        """Record one sample, return NORMAL | ANOMALY | UNKNOWN."""
        try:
            point = float(value)
        except (TypeError, ValueError):
            return {"status": "UNKNOWN", "reasons": ["non-numeric sample"]}
        if point != point or point in (float("inf"), float("-inf")):
            return {"status": "UNKNOWN", "reasons": ["non-finite sample"]}
        series = self._series.setdefault(metric, deque())
        series.append(point)
        while len(series) > self.max_points:
            series.popleft()
        self.metrics["points"] += 1
        thresholds = THRESHOLDS.get(metric)
        if thresholds is None:
            return {"status": "UNKNOWN",
                    "reasons": [f"no thresholds for {metric}"]}
        warn_at, critical_at, unit = thresholds
        if point >= critical_at:
            self.metrics["anomalies"] += 1
            return {"status": "ANOMALY",
                    "reasons": [f"{metric} {point}{unit} >= {critical_at}"]}
        if len(series) >= 5:
            recent = list(series)[-5:]
            baseline = sum(list(series)[:-5][-5:] or [recent[0]]) / max(
                1, len(list(series)[:-5][-5:] or [recent[0]]))
            if baseline > 0 and (recent[-1] - baseline) / baseline >= 0.5 \
                    and recent[-1] >= warn_at:
                self.metrics["anomalies"] += 1
                return {"status": "ANOMALY",
                        "reasons": [f"{metric} spiked 50%+ over baseline"]}
        if point >= warn_at:
            return {"status": "ANOMALY",
                    "reasons": [f"{metric} {point}{unit} >= {warn_at}"]}
        return {"status": "NORMAL", "reasons": []}

    def series(self, metric: str) -> list[float]:
        return list(self._series.get(metric, []))


def predict_pressure(metric: str, points: list[tuple[float, float]],
                     *, threshold: float = 0.0,
                     horizon_s: float = 3600.0) -> dict[str, Any]:
    """Trend forecast: EXPECTED | UNEXPECTED | PARTIAL | UNKNOWN.

    Uses the existing linear_trend evidence gate (<2 points -> None).
    Never writes facts; predictions stay predictions.
    """
    if len(points) < 2:
        return {"status": "UNKNOWN",
                "reasons": ["fewer than 2 points: no evidence"],
                "confidence": 0.0, "basis": []}
    trend = linear_trend([(float(x), float(y)) for x, y in points])
    if trend is None:
        return {"status": "UNKNOWN",
                "reasons": ["no measurable trend"],
                "confidence": 0.0, "basis": []}
    rate = float(trend.get("rate_per_second", 0.0))
    last_t, last_v = points[-1][0], points[-1][1]
    projected = last_v + rate * horizon_s
    basis = [f"linear trend {rate:+.4f}/s over "
             f"{trend.get('points', 0)} points"]
    confidence = min(0.6, 0.3 + 0.05 * len(points))
    if threshold and ((rate > 0 and projected >= threshold)
                      or (rate < 0 and projected <= threshold)):
        return {"status": "EXPECTED", "projected": round(projected, 2),
                "confidence": round(confidence, 2), "basis": basis,
                "reasons": [f"trend crosses {threshold} within horizon"]}
    if abs(rate) < 1e-9:
        return {"status": "EXPECTED", "projected": round(last_v, 2),
                "confidence": round(confidence, 2), "basis": basis,
                "reasons": ["steady: no pressure change"]}
    return {"status": "PARTIAL",
            "projected": round(projected, 2),
            "confidence": round(confidence, 2), "basis": basis,
            "reasons": ["trend exists but threshold outcome unclear"]}


def evaluate_automation_rules(
        telemetry: dict[str, Any],
        rules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Threshold crossings become ALERT events. Nothing destructive."""
    alerts: list[dict[str, Any]] = []
    for rule in (rules or [])[:16]:
        metric = str(rule.get("metric", ""))
        threshold = rule.get("above")
        if metric not in telemetry or threshold is None:
            continue
        try:
            value = float(telemetry[metric])
            limit = float(threshold)
        except (TypeError, ValueError):
            continue
        if value >= limit:
            alerts.append({
                "type": "pi.alert",
                "metric": metric, "value": value, "threshold": limit,
                "severity": str(rule.get("severity", "warning"))[:16],
                "action": "alert",  # alerts only, never recovery actions
            })
    return alerts


def replay_events(events: list[dict[str, Any]],
                  seen_ids: set[str] | None = None) -> dict[str, Any]:
    """Idempotent offline replay: dedupe by id, keep timestamps."""
    seen: set[str] = set(seen_ids or ())
    replayed: list[dict[str, Any]] = []
    skipped = 0
    for event in events[:500]:
        if not isinstance(event, dict):
            skipped += 1
            continue
        event_id = str(event.get("event_id", ""))
        if not event_id or event_id in seen:
            skipped += 1
            continue
        seen.add(event_id)
        replayed.append(event)
    return {"replayed": replayed, "skipped": skipped,
            "seen": len(seen)}


def observation_from_pi_telemetry(device_id: str,
                                  telemetry: dict[str, Any],
                                  *, event_type: str = "pi.telemetry",
                                  privacy: str = "local") -> dict[str, Any]:
    """Build a perception-Observation dict from Pi telemetry.

    Returns a plain dict matching the perception contract (the caller
    validates via Observation). Bounded scalars only, never raw media.
    """
    summary_bits = []
    for key in ("temperature_c", "cpu_percent", "memory_percent",
                "disk_percent"):
        if key in telemetry:
            summary_bits.append(f"{key}={telemetry[key]}")
    return {
        "source": "pi-telemetry",
        "source_device": str(device_id)[:120],
        "modality": "sensor",
        "payload": {"status": "ok",
                    "telemetry": {k: v for k, v in telemetry.items()
                                  if isinstance(v, (str, int, float, bool))},
                    "summary": ("pi telemetry: " + ", ".join(
                        summary_bits))[:300]},
        "confidence": 0.7,
        "provenance": {"provider": "pi-telemetry",
                       "event": event_type},
        "privacy_class": privacy,
    }


__all__ = [
    "AnomalyDetector",
    "decide_execution_site",
    "evaluate_automation_rules",
    "observation_from_pi_telemetry",
    "predict_pressure",
    "replay_events",
]
