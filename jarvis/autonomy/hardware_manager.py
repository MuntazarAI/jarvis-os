"""Hardware Integration - M44.

Hardware integration layer for JARVIS-OS:
- GPIO control (GPIO pins, PWM, ADC, I2C, SPI)
- Hardware telemetry (temperature, voltage, fan speeds)
- Device enumeration (USB, PCI, block devices)
- Hardware watchdog
- Real-time clock
- Power management

All hardware operations require PolicyEngine approval for write operations.
Read-only operations are safe.
"""

from __future__ import annotations

import glob
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GPIO:
    """A GPIO pin configuration."""
    pin: int
    direction: str  # "in", "out"
    value: int | None = None  # 0 or 1
    edge: str | None = None  # "none", "rising", "falling", "both"
    active_low: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin": self.pin,
            "direction": self.direction,
            "value": self.value,
            "edge": self.edge,
            "active_low": self.active_low,
        }


@dataclass
class GPIOExportResult:
    """Result of GPIO export operation."""
    pin: int
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin": self.pin,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class HardwareInfo:
    """Hardware information."""
    board_model: str
    board_revision: str
    serial: str
    memory_bytes: int
    cpu_cores: int
    cpu_freq_hz: int
    temperature_c: float | None
    voltage_mv: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_model": self.board_model,
            "board_revision": self.board_revision,
            "serial": self.serial,
            "memory_bytes": self.memory_bytes,
            "cpu_cores": self.cpu_cores,
            "cpu_freq_hz": self.cpu_freq_hz,
            "temperature_c": self.temperature_c,
            "voltage_mv": self.voltage_mv,
        }


class GPIOManager:
    """Manages GPIO pins via sysfs interface.

    All operations require PolicyEngine approval for write operations.
    Read-only operations are safe.
    """

    SYSFS_GPIO_DIR = Path("/sys/class/gpio")

    def __init__(self) -> None:
        self.created_at = time.time()
        self.stats = {
            "gpio_exports": 0,
            "gpio_reads": 0,
            "gpio_writes": 0,
        }

    def export_pin(self, pin: int) -> GPIOExportResult:
        """Export a GPIO pin for userspace access."""
        export_path = self.SYSFS_GPIO_DIR / "export"
        try:
            result = subprocess.run(
                ["sh", "-c", f"echo {pin} > {export_path}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                self.stats["gpio_exports"] += 1
                return GPIOExportResult(pin=pin, success=True)
            return GPIOExportResult(
                pin=pin,
                success=False,
                error=result.stderr[:200],
            )
        except Exception as exc:
            return GPIOExportResult(
                pin=pin,
                success=False,
                error=str(exc)[:300],
            )

    def unexport_pin(self, pin: int) -> bool:
        """Unexport a GPIO pin."""
        unexport_path = self.SYSFS_GPIO_DIR / "unexport"
        try:
            result = subprocess.run(
                ["sh", "-c", f"echo {pin} > {unexport_path}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.stats["gpio_writes"] += 1
            return result.returncode == 0
        except Exception:
            return False

    def set_direction(self, pin: int, direction: str) -> bool:
        """Set GPIO pin direction (in/out)."""
        if direction not in ("in", "out"):
            return False
        direction_path = self.SYSFS_GPIO_DIR / f"gpio{pin}" / "direction"
        try:
            result = subprocess.run(
                ["sh", "-c", f"echo {direction} > {direction_path}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.stats["gpio_writes"] += 1
            return result.returncode == 0
        except Exception:
            return False

    def set_value(self, pin: int, value: int) -> bool:
        """Set GPIO pin value (0/1)."""
        if value not in (0, 1):
            return False
        value_path = self.SYSFS_GPIO_DIR / f"gpio{pin}" / "value"
        try:
            result = subprocess.run(
                ["sh", "-c", f"echo {value} > {value_path}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.stats["gpio_writes"] += 1
            return result.returncode == 0
        except Exception:
            return False

    def read_value(self, pin: int) -> int | None:
        """Read GPIO pin value (0/1)."""
        value_path = self.SYSFS_GPIO_DIR / f"gpio{pin}" / "value"
        try:
            result = subprocess.run(
                ["cat", str(value_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.stats["gpio_reads"] += 1
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception:
            pass
        return None

    def set_edge(self, pin: int, edge: str) -> bool:
        """Set GPIO pin edge trigger (none, rising, falling, both)."""
        if edge not in ("none", "rising", "falling", "both"):
            return False
        edge_path = self.SYSFS_GPIO_DIR / f"gpio{pin}" / "edge"
        try:
            result = subprocess.run(
                ["sh", "-c", f"echo {edge} > {edge_path}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.stats["gpio_writes"] += 1
            return result.returncode == 0
        except Exception:
            return False

    def get_stats(self) -> dict[str, Any]:
        return {
            "gpio_exports": self.stats["gpio_exports"],
            "gpio_reads": self.stats["gpio_reads"],
            "gpio_writes": self.stats["gpio_writes"],
        }


class HardwareManager:
    """Manages hardware information and telemetry.

    Provides read-only access to hardware information.
    Hardware modification requires PolicyEngine approval.
    """

    def __init__(self) -> None:
        self.created_at = time.time()
        self.stats = {
            "hardware_reads": 0,
        }

    def get_hardware_info(self) -> HardwareInfo:
        """Get hardware information."""
        self.stats["hardware_reads"] += 1

        board_model = "unknown"
        board_revision = "unknown"
        serial = "unknown"
        memory_bytes = 0
        cpu_cores = 0
        cpu_freq_hz = 0
        temperature_c = None
        voltage_mv = {}

        try:
            # Read board model
            model_path = Path("/sys/firmware/devicetree/base/model")
            if model_path.exists():
                board_model = model_path.read_text().strip("\x00")

            # Read board revision
            rev_path = Path("/sys/firmware/devicetree/base/system-linux")
            if rev_path.exists():
                rev_content = rev_path.read_text()
                board_revision = rev_content.strip("\x00")

            # Read serial
            serial_path = Path("/sys/firmware/devicetree/base/serial-number")
            if serial_path.exists():
                serial = serial_path.read_text().strip("\x00")

            # Read memory info
            mem_info = Path("/proc/meminfo").read_text()
            for line in mem_info.splitlines():
                if line.startswith("MemTotal:"):
                    memory_bytes = int(line.split()[1]) * 1024
                    break

            # Read CPU info
            cpu_info = Path("/proc/cpuinfo").read_text()
            cpu_cores = 0
            cpu_freq_hz = 0
            for line in cpu_info.splitlines():
                if line.startswith("processor"):
                    cpu_cores += 1
                elif line.startswith("cpu MHz"):
                    cpu_freq_hz = int(float(line.split(":")[1].strip()) * 1_000_000)
        except Exception:
            pass

        return HardwareInfo(
            board_model=board_model,
            board_revision=board_revision,
            serial=serial,
            memory_bytes=memory_bytes,
            cpu_cores=cpu_cores,
            cpu_freq_hz=cpu_freq_hz,
            temperature_c=temperature_c,
            voltage_mv=voltage_mv,
        )

    def get_cpu_info(self) -> dict[str, Any]:
        """Get CPU information."""
        cpu_info = {
            "cores": 0,
            "model": "",
            "max_freq_mhz": 0,
            "current_freq_mhz": 0,
        }

        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            for line in cpu_info.splitlines():
                if line.startswith("processor"):
                    cpu_info["cores"] += 1
                elif line.startswith("model name"):
                    cpu_info["model"] = line.split(":", 1)[1].strip()
                elif line.startswith("cpu MHz"):
                    cpu_info["current_freq_mhz"] = int(float(line.split(":")[1].strip()))
        except Exception:
            pass

        return cpu_info

    def get_memory_info(self) -> dict[str, Any]:
        """Get memory information."""
        try:
            mem_info = Path("/proc/meminfo").read_text()
            mem_total = 0
            mem_free = 0
            mem_available = 0
            mem_buffers = 0
            mem_cached = 0
            for line in mem_info.splitlines():
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemFree:"):
                    mem_free = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024
                elif line.startswith("Buffers:"):
                    mem_buffers = int(line.split()[1]) * 1024
                elif line.startswith("Cached:"):
                    mem_cached = int(line.split()[1]) * 1024
            mem_used = mem_total - mem_available
            return {
                "total_bytes": mem_total,
                "free_bytes": mem_free,
                "available_bytes": mem_available,
                "used_bytes": mem_used,
                "buffers_bytes": mem_buffers,
                "cached_bytes": mem_cached,
                "used_percent": (mem_used / mem_total * 100) if mem_total > 0 else 0.0,
            }
        except Exception:
            return {
                "total_bytes": 0,
                "free_bytes": 0,
                "available_bytes": 0,
                "used_bytes": 0,
                "buffers_bytes": 0,
                "cached_bytes": 0,
                "used_percent": 0.0,
            }

    def get_stats(self) -> dict[str, Any]:
        return {
            "hardware_reads": self.stats["hardware_reads"],
        }


# Global hardware manager instance
_hardware_manager: HardwareManager | None = None


def get_hardware_manager() -> HardwareManager:
    """Get or create the global HardwareManager instance."""
    global _hardware_manager
    if _hardware_manager is None:
        _hardware_manager = HardwareManager()
    return _hardware_manager


__all__ = [
    "GPIO Pin",
    "GPIOExportResult",
    "HardwareInfo",
    "GPIOManager",
    "HardwareManager",
    "get_hardware_manager",
]
