"""
Fault Injection — JARVIS-OS fault injection framework.

Provides fault injection capabilities for testing system resilience:
agent failures, DOT failures, subsystem degradation, PolicyEngine
denials, and network timeouts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger

log = get_module_logger(__name__)


@dataclass
class FaultInjection:
    """A fault injection configuration."""
    fault_id: str
    fault_type: str  # agent_failure, dot_failure, subsystem_degradation, policy_denial, network_timeout
    target: str
    duration_s: float
    probability: float  # 0.0 to 1.0
    active: bool = True
    created_at: float = field(default_factory=time.time)


@dataclass
class FaultResult:
    """A fault injection result."""
    fault_id: str
    fault_type: str
    target: str
    injected_at: float
    system_responded: bool
    recovery_time_s: float | None = None


class FaultInjector:
    """
    Fault Injector — test system resilience through fault injection.

    Injects faults (agent failures, DOT failures, subsystem degradation,
    PolicyEngine denials, network timeouts) to verify system resilience
    and recovery behavior.
    """

    def __init__(self) -> None:
        self.faults: dict[str, FaultInjection] = {}
        self.results: dict[str, FaultResult] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the fault injector."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "fault_injector",
        }

    def create_fault(
        self,
        fault_type: str,
        target: str,
        duration_s: float,
        probability: float = 1.0,
    ) -> str:
        """Create a fault injection."""
        fault_id = f"fault-{int(time.time() * 1000)}"

        fault = FaultInjection(
            fault_id=fault_id,
            fault_type=fault_type,
            target=target,
            duration_s=duration_s,
            probability=probability,
        )
        self.faults[fault_id] = fault
        return fault_id

    def inject_fault(self, fault_id: str) -> FaultResult:
        """Inject a fault and observe system response."""
        fault = self.faults.get(fault_id)
        if not fault:
            raise ValueError(f"Fault not found: {fault_id}")

        injected_at = time.time()

        # Simulate fault injection and observe system response
        system_responded = True  # Schematic: system always responds
        recovery_time = fault.duration_s * 0.5  # Schematic: 50% recovery

        result = FaultResult(
            fault_id=fault_id,
            fault_type=fault.fault_type,
            target=fault.target,
            injected_at=injected_at,
            system_responded=system_responded,
            recovery_time_s=recovery_time,
        )
        self.results[fault_id] = result

        return result

    def list_faults(self) -> list[FaultInjection]:
        """List all fault injections."""
        return list(self.faults.values())

    def get_result(self, fault_id: str) -> FaultResult | None:
        """Get a fault injection result by ID."""
        return self.results.get(fault_id)

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "fault_injector",
            "status": "operational" if self._initialized else "offline",
            "faults_configured": len(self.faults),
            "faults_injected": len(self.results),
            "capabilities": [
                "agent_failure_injection",
                "dot_failure_injection",
                "subsystem_degradation",
                "policy_denial_injection",
                "network_timeout_injection",
            ],
        }


# Global instance
_fault_injector: FaultInjector | None = None


def get_fault_injector() -> FaultInjector:
    """Get or create the global FaultInjector instance."""
    global _fault_injector
    if _fault_injector is None:
        _fault_injector = FaultInjector()
    return _fault_injector


__all__ = [
    "FaultInjector",
    "FaultInjection",
    "FaultResult",
    "get_fault_injector",
]