"""Self-model, collaboration modes, explanations (5.0).

CapabilityModel: what JARVIS can/cannot do right now, probed live
where cheap (provider health checks), declared honestly otherwise.
DecisionMode: ACT | ASK | WAIT | EXPLAIN | STOP | ESCALATE, derived
from policy, uncertainty, and capability — using the existing
policy/approval architecture, never a parallel one.
explain(): evidence-based decision summaries; chain-of-thought is
never exposed, secrets never included.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CapabilityState(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    NOT_PRODUCTION_READY = "not_production_ready"


class DecisionMode(str, Enum):
    ACT = "act"
    ASK = "ask"
    WAIT = "wait"
    EXPLAIN = "explain"
    STOP = "stop"
    ESCALATE = "escalate"


@dataclass
class Capability:
    name: str
    state: CapabilityState = CapabilityState.UNAVAILABLE
    latency_ms: float | None = None
    reliability: float = 0.5
    confidence: float = 0.5
    detail: str = ""
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


class CapabilityModel:
    """Live capability inventory. Honest about gaps."""

    def __init__(self) -> None:
        self._static: dict[str, Capability] = {
            "SCREEN_OCR": Capability(
                "SCREEN_OCR", CapabilityState.AVAILABLE,
                detail="tesseract CLI where installed"),
            "CAMERA": Capability(
                "CAMERA", CapabilityState.AVAILABLE,
                detail="v4l2 where /dev/video* exists"),
            "AUDIO_STT": Capability(
                "AUDIO_STT", CapabilityState.DEGRADED,
                detail="adapter wired; faster-whisper runtime broken "
                       "by PyAV incompatibility (graceful FAILED)"),
            "AUDIO_CAPTURE": Capability(
                "AUDIO_CAPTURE", CapabilityState.AVAILABLE,
                detail="arecord where installed; mic presence probed"),
            "AUDIO_VAD": Capability(
                "AUDIO_VAD", CapabilityState.AVAILABLE,
                detail="energy VAD, stdlib only"),
            "MICROPHONE": Capability(
                "MICROPHONE", CapabilityState.UNAVAILABLE,
                detail="probed at check time, never assumed"),
            "PHYSICAL_PI_AUDIO": Capability(
                "PHYSICAL_PI_AUDIO", CapabilityState.NOT_PRODUCTION_READY,
                detail="no Pi audio hardware validated"),
            "ANDROID_COMMAND": Capability(
                "ANDROID_COMMAND", CapabilityState.AVAILABLE,
                detail="paired trusted lanes via DeviceCommandService"),
            "TLS_TRANSPORT": Capability(
                "TLS_TRANSPORT", CapabilityState.NOT_PRODUCTION_READY,
                detail="trusted-LAN HMAC only; mTLS is future work"),
            "COGNITIVE_LOOP": Capability(
                "COGNITIVE_LOOP", CapabilityState.AVAILABLE,
                detail="13-stage supervised cycle"),
            "LEARNING": Capability(
                "LEARNING", CapabilityState.AVAILABLE,
                detail="bounded deterministic engine"),
        }

    def check(self, name: str, providers: Any = None) -> Capability:
        """Refresh one capability against live providers if given."""
        capability = self._static.get(name)
        if capability is None:
            return Capability(name, CapabilityState.UNAVAILABLE,
                              detail="unknown capability")
        if providers is not None and name in ("SCREEN_OCR", "CAMERA"):
            try:
                health = providers.health()
                available = bool(health.get("available", False))
                capability = Capability(
                    name, CapabilityState.AVAILABLE if available
                    else CapabilityState.UNAVAILABLE,
                    detail=str(health.get("detail", ""))[:200])
                self._static[name] = capability
            except Exception:
                pass
        if name == "MICROPHONE":
            capability = self._probe_microphone()
            self._static[name] = capability
        if name == "AUDIO_CAPTURE":
            capability = self._probe_capture()
            self._static[name] = capability
        capability.checked_at = time.time()
        return capability

    @staticmethod
    def _probe_microphone() -> Capability:
        """arecord device list. No recording, just presence."""
        import shutil
        import subprocess
        if shutil.which("arecord") is None:
            return Capability("MICROPHONE", CapabilityState.UNAVAILABLE,
                              detail="arecord not installed")
        try:
            proc = subprocess.run(
                ["arecord", "-l"], capture_output=True, text=True,
                timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            return Capability("MICROPHONE", CapabilityState.UNAVAILABLE,
                              detail="arecord probe failed")
        cards = [line.strip()[:80] for line in
                 (proc.stdout or "").splitlines()
                 if line.strip().startswith("card ")]
        if not cards:
            return Capability("MICROPHONE", CapabilityState.UNAVAILABLE,
                              detail="no capture hardware listed")
        return Capability("MICROPHONE", CapabilityState.AVAILABLE,
                          detail=f"{len(cards)} card(s): "
                                 f"{cards[0]}")

    @staticmethod
    def _probe_capture() -> Capability:
        import shutil
        if shutil.which("arecord") is None:
            return Capability("AUDIO_CAPTURE", CapabilityState.UNAVAILABLE,
                              detail="arecord not installed")
        return Capability("AUDIO_CAPTURE", CapabilityState.AVAILABLE,
                          detail="arecord present; device probed per use")

    def inventory(self) -> list[Capability]:
        return [self._static[key] for key in sorted(self._static)]

    def missing_for(self, required: list[str]) -> list[str]:
        """Capabilities in `required` that are not AVAILABLE."""
        missing = []
        for name in required:
            capability = self._static.get(name)
            if capability is None or capability.state != \
                    CapabilityState.AVAILABLE:
                missing.append(name)
        return missing


def decide_mode(*, policy_allowed: bool | None,
                requires_approval: bool = False,
                uncertainty: str = "unknown",
                missing_capabilities: list[str] | None = None,
                blocked: bool = False) -> DecisionMode:
    """ACT | ASK | WAIT | EXPLAIN | STOP | ESCALATE from explicit inputs.

    No hidden heuristics: denied policy -> STOP; missing capability ->
    ESCALATE; approval pending -> WAIT; high uncertainty ->
    ASK/EXPLAIN; otherwise ACT.
    """
    if blocked or policy_allowed is False:
        return DecisionMode.STOP
    if missing_capabilities:
        return DecisionMode.ESCALATE
    if requires_approval:
        return DecisionMode.WAIT
    if uncertainty in ("contradicted", "unknown"):
        return DecisionMode.ASK
    if uncertainty == "uncertain":
        return DecisionMode.EXPLAIN
    return DecisionMode.ACT


def explain(outcome: dict[str, Any] | Any) -> dict[str, Any]:
    """Evidence-based decision summary. Secrets never included."""
    if not isinstance(outcome, dict):
        to_dict = getattr(outcome, "to_dict", None)
        outcome = to_dict() if callable(to_dict) else {}
    if not isinstance(outcome, dict):
        return {"what": "unknown outcome", "why": "unreadable record"}
    action = outcome.get("action", {}) or {}
    verification = outcome.get("verification", {}) or {}
    stages = outcome.get("stages", []) or []
    failed = [s.get("stage") for s in stages if isinstance(s, dict)
              and not s.get("ok", True)]
    evidence = []
    decision = outcome.get("decision", {}) or {}
    for ref in (decision.get("evidence_refs", []) or [])[:5]:
        evidence.append(str(ref)[:80])
    return {
        "what": str(action.get("action", "") or "no action")[:120],
        "why": str(decision.get("conclusion", ""))[:300],
        "evidence": evidence,
        "alternatives": ["no action taken"] if not action.get("action")
        else ["action as planned"],
        "uncertainty": [str(u)[:120] for u in
                        (decision.get("uncertainty", []) or [])][:5],
        "risk": str((outcome.get("policy") or {}).get("reason", ""))[:200],
        "action": str(action.get("action", ""))[:120],
        "result": str((outcome.get("result") or {}).get("error", "")
                      or ("ok" if (outcome.get("result") or {}).get(
                          "ok") else "no result"))[:200],
        "verification": str(verification.get("verdict", "UNKNOWN"))[:32],
        "failed_stages": failed[:8],
    }


__all__ = [
    "Capability",
    "CapabilityModel",
    "CapabilityState",
    "DecisionMode",
    "decide_mode",
    "explain",
]
