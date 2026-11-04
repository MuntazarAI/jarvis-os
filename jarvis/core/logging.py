"""Structured JSON logging with correlation IDs for JARVIS."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional
from pathlib import Path


# Thread-local storage for correlation IDs
_local = threading.local()


def get_correlation_id() -> str:
    """Get the current correlation ID, generating one if needed."""
    if not hasattr(_local, "correlation_id"):
        _local.correlation_id = uuid.uuid4().hex[:16]
    return _local.correlation_id


def set_correlation_id(cid: Optional[str] = None) -> str:
    """Set a new correlation ID (or generate one) and return it."""
    _local.correlation_id = cid or uuid.uuid4().hex[:16]
    return _local.correlation_id


def clear_correlation_id() -> None:
    """Clear the correlation ID for this thread."""
    if hasattr(_local, "correlation_id"):
        del _local.correlation_id


@contextmanager
def correlation_context(cid: Optional[str] = None):
    """Context manager to temporarily set a correlation ID."""
    old_cid = getattr(_local, "correlation_id", None)
    _local.correlation_id = cid or uuid.uuid4().hex[:16]
    try:
        yield _local.correlation_id
    finally:
        if old_cid is not None:
            _local.correlation_id = old_cid
        else:
            clear_correlation_id()


@dataclass
class LogRecord:
    """Structured log record with correlation ID and standard fields."""
    timestamp: float = field(default_factory=time.time)
    level: str = "INFO"
    logger: str = ""
    message: str = ""
    correlation_id: str = field(default_factory=get_correlation_id)
    module: str = ""
    function: str = ""
    line: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str, sort_keys=True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JSONFormatter(logging.Formatter):
    """Format log records as JSON with correlation IDs."""

    def format(self, record: logging.LogRecord) -> str:
        log_record = LogRecord(
            timestamp=record.created,
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            correlation_id=get_correlation_id(),
            module=record.module,
            function=record.funcName,
            line=record.lineno,
            extra=getattr(record, "extra", {}),
        )
        return log_record.to_json()


class StructuredLogger:
    """Wrapper around stdlib logging with structured extras."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._name = name

    def _log(self, level: int, msg: str, **extra: Any) -> None:
        if self._logger.isEnabledFor(level):
            record = self._logger.makeRecord(
                self._name, level, "", 0, msg, (), None
            )
            record.extra = extra
            self._logger.handle(record)

    def debug(self, msg: str, **extra: Any) -> None:
        self._log(logging.DEBUG, msg, **extra)

    def info(self, msg: str, **extra: Any) -> None:
        self._log(logging.INFO, msg, **extra)

    def warning(self, msg: str, **extra: Any) -> None:
        self._log(logging.WARNING, msg, **extra)

    def error(self, msg: str, **extra: Any) -> None:
        self._log(logging.ERROR, msg, **extra)

    def critical(self, msg: str, **extra: Any) -> None:
        self._log(logging.CRITICAL, msg, **extra)

    def exception(self, msg: str, **extra: Any) -> None:
        extra.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, **extra)

    def with_correlation(self, cid: str) -> "StructuredLogger":
        """Return a logger that uses the given correlation ID."""
        return CorrelatedLogger(self, cid)


class CorrelatedLogger:
    """Logger bound to a specific correlation ID."""

    def __init__(self, base: StructuredLogger, correlation_id: str):
        self._base = base
        self._correlation_id = correlation_id

    def _log(self, level: int, msg: str, **extra: Any) -> None:
        extra.setdefault("correlation_id", self._correlation_id)
        self._base._log(level, msg, **extra)

    def debug(self, msg: str, **extra: Any) -> None:
        self._log(logging.DEBUG, msg, **extra)

    def info(self, msg: str, **extra: Any) -> None:
        self._log(logging.INFO, msg, **extra)

    def warning(self, msg: str, **extra: Any) -> None:
        self._log(logging.WARNING, msg, **extra)

    def error(self, msg: str, **extra: Any) -> None:
        self._log(logging.ERROR, msg, **extra)

    def critical(self, msg: str, **extra: Any) -> None:
        self._log(logging.CRITICAL, msg, **extra)

    def exception(self, msg: str, **extra: Any) -> None:
        extra.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, **extra)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger for the given module name."""
    return StructuredLogger(name)


def configure_logging(
    level: int = logging.INFO,
    json_format: bool = True,
    log_file: Optional[Path] = None,
    console: bool = True,
) -> None:
    """Configure global logging with JSON format and correlation IDs."""
    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    formatter = JSONFormatter() if json_format else logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


# Convenience: module-level logger
def get_module_logger(module: str = None) -> StructuredLogger:
    """Get logger for the calling module (or specified module)."""
    if module is None:
        import inspect
        frame = inspect.currentframe().f_back
        module = frame.f_globals.get("__name__", "jarvis")
    return get_logger(module)


# Decorator for tracing function calls with correlation IDs
def trace(logger: StructuredLogger = None, include_args: bool = False, include_result: bool = False):
    """Decorator to trace function entry/exit with correlation ID."""
    def decorator(func: Callable) -> Callable:
        import functools
        log = logger or get_module_logger(func.__module__)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cid = get_correlation_id()
            call_id = uuid.uuid4().hex[:8]
            log.info(
                f"{func.__name__} called",
                function=func.__name__,
                call_id=call_id,
                correlation_id=cid,
                args=args if include_args else None,
                kwargs=kwargs if include_args else None,
            )
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                log.info(
                    f"{func.__name__} completed",
                    function=func.__name__,
                    call_id=call_id,
                    correlation_id=cid,
                    duration_ms=round(duration * 1000, 2),
                    result=result if include_result else None,
                )
                return result
            except Exception as e:
                duration = time.time() - start
                log.error(
                    f"{func.__name__} failed",
                    function=func.__name__,
                    call_id=call_id,
                    correlation_id=cid,
                    duration_ms=round(duration * 1000, 2),
                    error=str(e),
                    exc_info=True,
                )
                raise
        return wrapper
    return decorator


# Context manager for operation tracing
@contextmanager
def trace_operation(name: str, logger: StructuredLogger = None, **extra: Any):
    """Context manager to trace an operation with timing."""
    log = logger or get_module_logger("jarvis")
    cid = get_correlation_id()
    op_id = uuid.uuid4().hex[:8]
    start = time.time()
    log.info(f"{name} started", operation=name, operation_id=op_id, correlation_id=cid, **extra)
    try:
        yield op_id
        duration = time.time() - start
        log.info(f"{name} completed", operation=name, operation_id=op_id, correlation_id=cid,
                 duration_ms=round(duration * 1000, 2), **extra)
    except Exception as e:
        duration = time.time() - start
        log.error(f"{name} failed", operation=name, operation_id=op_id, correlation_id=cid,
                  duration_ms=round(duration * 1000, 2), error=str(e), exc_info=True, **extra)
        raise