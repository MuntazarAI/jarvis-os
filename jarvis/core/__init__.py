"""JARVIS Core - Configuration, Loop, Service, Types, Logging, Internet, Skills."""

from .config import JarvisConfig
from .internet import InternetAccess, InternetGrant
from .service import ServiceManager, HealthCheck, check_dependencies
from .types import (
    now, new_id, content_hash,
    Confidence, RiskLevel, TaskState, Modality,
    Provenance, Observation, Evidence, Hypothesis, Contradiction,
    Task, ActionPlan, CognitiveReport, dumps,
)
from .logging import (
    configure_logging, get_logger, get_module_logger,
    get_correlation_id, set_correlation_id, clear_correlation_id,
    correlation_context, trace, trace_operation,
    StructuredLogger, LogRecord,
)

# Lazy import for Jarvis to avoid circular imports
_Jarvis = None
_CycleResult = None

def _get_loop():
    global _Jarvis, _CycleResult
    if _Jarvis is None:
        from .loop import Jarvis, CycleResult
        _Jarvis = Jarvis
        _CycleResult = CycleResult
    return _Jarvis, _CycleResult


__all__ = [
    "JarvisConfig",
    "InternetAccess",
    "InternetGrant",
    "ServiceManager",
    "HealthCheck",
    "check_dependencies",
    "now", "new_id", "content_hash",
    "Confidence", "RiskLevel", "TaskState", "Modality",
    "Provenance", "Observation", "Evidence", "Hypothesis", "Contradiction",
    "Task", "ActionPlan", "CognitiveReport", "dumps",
    "configure_logging", "get_logger", "get_module_logger",
    "get_correlation_id", "set_correlation_id", "clear_correlation_id",
    "correlation_context", "trace", "trace_operation",
    "StructuredLogger", "LogRecord",
]