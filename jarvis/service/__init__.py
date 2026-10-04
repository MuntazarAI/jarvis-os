"""Background service package (24/7 runtime). See runtime.py."""

from .runtime import (
    MAX_ATTEMPTS,
    MAX_QUEUE,
    STALE_HEARTBEAT_S,
    BackgroundService,
    ServiceLock,
    Trigger,
    evaluate_state,
    read_pid_info,
)

__all__ = ["BackgroundService", "ServiceLock", "Trigger",
           "evaluate_state", "read_pid_info", "MAX_QUEUE",
           "MAX_ATTEMPTS", "STALE_HEARTBEAT_S"]
