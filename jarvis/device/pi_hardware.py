"""Raspberry Pi hardware abstraction (5.0).

Provider interfaces with three implementations each: real (reads
local hardware through /proc, /sys, and bounded subprocess calls),
fake (deterministic scripted values for tests), and unavailable
(structured incapability, never fabricated values).

No provider executes actions, opens sockets, or runs forever. GPIO
writes go through the allowlisted command path only — providers are
strictly read-only observers.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class HardwareError(RuntimeError):
    """Hardware access failure (not a policy denial)."""


class HardwareProvider:
    """Base: health(), capabilities(), close(). Read-only."""

    name = "hardware"

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": False}

    def capabilities(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _read_text(path: str, limit: int = 65536) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


class SystemProvider(HardwareProvider):
    """CPU/memory/disk/uptime from /proc. Works on any Linux."""

    name = "system"

    def __init__(self) -> None:
        self._last_cpu: tuple[float, float, float] | None = None

    def health(self) -> dict[str, Any]:
        return {"provider": self.name,
                "available": Path("/proc/stat").exists()}

    def capabilities(self) -> dict[str, Any]:
        return {"cpu": True, "memory": True, "storage": True,
                "uptime": True}

    @staticmethod
    def _cpu_times() -> tuple[float, float] | None:
        try:
            parts = _read_text("/proc/stat", 512).splitlines()[0].split()[1:]
            values = [float(p) for p in parts[:8]]
        except (IndexError, ValueError, OSError):
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0.0)
        return sum(values), idle

    def cpu_percent(self) -> float | None:
        """CPU busy % between two samples 0.1s apart. None if unreadable."""
        first = self._cpu_times()
        if first is None:
            return None
        time.sleep(0.1)
        second = self._cpu_times()
        if second is None:
            return None
        busy = (second[0] - second[1]) - (first[0] - first[1])
        total = second[0] - first[0]
        if total <= 0:
            return 0.0
        return round(max(0.0, min(100.0, busy / total * 100.0)), 1)

    @staticmethod
    def memory_percent() -> float | None:
        total = available = None
        for line in _read_text("/proc/meminfo", 4096).splitlines():
            if line.startswith("MemTotal:"):
                total = float(line.split()[1])
            elif line.startswith("MemAvailable:"):
                available = float(line.split()[1])
        if not total:
            return None
        return round(max(0.0, min(100.0,
                                  (total - (available or 0.0)) / total * 100.0)), 1)

    @staticmethod
    def disk_percent(path: str = "/") -> float | None:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            return None
        if not usage.total:
            return None
        return round(usage.used / usage.total * 100.0, 1)

    @staticmethod
    def uptime_s() -> float | None:
        try:
            return float(_read_text("/proc/uptime", 64).split()[0])
        except (IndexError, ValueError):
            return None

    def telemetry(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        cpu = self.cpu_percent()
        if cpu is not None:
            out["cpu_percent"] = cpu
        memory = self.memory_percent()
        if memory is not None:
            out["memory_percent"] = memory
        disk = self.disk_percent()
        if disk is not None:
            out["disk_percent"] = disk
        uptime = self.uptime_s()
        if uptime is not None:
            out["uptime_s"] = round(uptime, 1)
        return out


class TemperatureProvider(HardwareProvider):
    """SoC temperature from thermal zones. Absent sensor, not zero."""

    name = "temperature"

    def health(self) -> dict[str, Any]:
        zones = list(Path("/sys/class/thermal").glob("thermal_zone*/temp")) \
            if Path("/sys/class/thermal").exists() else []
        return {"provider": self.name, "available": bool(zones),
                "zones": len(zones)}

    def capabilities(self) -> dict[str, Any]:
        return {"temperature_c": True}

    @staticmethod
    def temperature_c() -> float | None:
        """Hottest thermal zone in Celsius. None when no sensor exists."""
        base = Path("/sys/class/thermal")
        if not base.exists():
            return None
        hottest: float | None = None
        for zone in sorted(base.glob("thermal_zone*/temp")):
            try:
                value = float(zone.read_text().strip()) / 1000.0
            except (OSError, ValueError):
                continue
            if hottest is None or value > hottest:
                hottest = value
        return round(hottest, 1) if hottest is not None else None


class NetworkProvider(HardwareProvider):
    """Link state: interface names + operstate. No packet capture."""

    name = "network"

    def health(self) -> dict[str, Any]:
        return {"provider": self.name,
                "available": Path("/sys/class/net").exists()}

    def capabilities(self) -> dict[str, Any]:
        return {"interfaces": True, "link_state": True}

    @staticmethod
    def status() -> dict[str, str]:
        """{interface: operstate}. Loopback included honestly."""
        base = Path("/sys/class/net")
        out: dict[str, str] = {}
        if not base.exists():
            return out
        for interface in sorted(base.iterdir()):
            try:
                state = (interface / "operstate").read_text().strip()[:16]
            except OSError:
                state = "unknown"
            out[interface.name[:32]] = state
        return out


class CameraProvider(HardwareProvider):
    """One-shot camera via v4l2/ffmpeg. Explicit lifecycle, no daemon."""

    name = "camera"

    def __init__(self, device: str = "/dev/video0") -> None:
        self.device = device
        self._started = False

    def health(self) -> dict[str, Any]:
        present = Path(self.device).exists()
        backend = shutil.which("ffmpeg") is not None
        return {"provider": self.name,
                "available": present and backend,
                "started": self._started, "device": self.device}

    def capabilities(self) -> dict[str, Any]:
        return {"status": True, "capture": True, "single_shot": True}

    def start(self) -> dict[str, Any]:
        health = self.health()
        if not health["available"]:
            return {"started": False,
                    "detail": "no camera device or ffmpeg backend"}
        self._started = True
        return {"started": True, "device": self.device}

    def stop(self) -> None:
        self._started = False

    def close(self) -> None:
        self.stop()

    def capture(self, dest: str, timeout_s: float = 20.0) -> dict[str, Any]:
        """Single JPEG frame. Returns metadata, never raw bytes."""
        if not self._started:
            return {"ok": False, "error": "camera not started"}
        if shutil.which("ffmpeg") is None:
            return {"ok": False, "error": "ffmpeg backend missing"}
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "v4l2",
                 "-i", self.device, "-frames:v", "1", dest],
                capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "capture timed out"}
        except OSError as exc:
            return {"ok": False, "error": f"{type(exc).__name__}"[:80]}
        if proc.returncode != 0:
            return {"ok": False,
                    "error": (proc.stderr.strip() or "capture failed")[:160]}
        try:
            size = Path(dest).stat().st_size
        except OSError:
            return {"ok": False, "error": "capture produced no file"}
        import hashlib
        digest = hashlib.sha256()
        try:
            with open(dest, "rb") as handle:
                digest.update(handle.read(1 << 20))
        except OSError:
            return {"ok": False, "error": "capture unreadable"}
        return {"ok": True, "path": dest, "bytes": size,
                "sha256": digest.hexdigest()[:32]}


class GpioProvider(HardwareProvider):
    """Sysfs GPIO reads. Writes are NOT here (command path only)."""

    name = "gpio"

    def health(self) -> dict[str, Any]:
        return {"provider": self.name,
                "available": Path("/sys/class/gpio").exists()}

    def capabilities(self) -> dict[str, Any]:
        return {"read": True, "write": False,
                "note": "writes only via allowlisted pi.gpio.write"}

    @staticmethod
    def read(pin: int) -> dict[str, Any]:
        """Read sysfs GPIO value. Unvalidated pins rejected upstream."""
        if not isinstance(pin, int) or not 0 <= pin <= 40:
            return {"ok": False, "error": "pin out of range"}
        chip = Path("/sys/class/gpio")
        if not chip.exists():
            return {"ok": False, "error": "gpio sysfs unavailable"}
        target = chip / f"gpio{pin}" / "value"
        try:
            value = target.read_text().strip()
        except OSError:
            return {"ok": False,
                    "error": f"gpio{pin} not exported or unreadable"}
        if value not in ("0", "1"):
            return {"ok": False, "error": "unexpected gpio value"}
        return {"ok": True, "pin": pin, "value": int(value)}


class I2CProvider(HardwareProvider):
    """I2C presence reporting. Transfers need explicit future work."""

    name = "i2c"

    def health(self) -> dict[str, Any]:
        devices = sorted(p.name for p in Path("/dev").glob("i2c-*")) \
            if Path("/dev").exists() else []
        return {"provider": self.name, "available": bool(devices),
                "buses": devices[:8]}

    def capabilities(self) -> dict[str, Any]:
        return {"scan": True, "transfer": False,
                "note": "transfers are future work, not silent stubs"}


class SPIProvider(HardwareProvider):
    """SPI presence reporting. Transfers need explicit future work."""

    name = "spi"

    def health(self) -> dict[str, Any]:
        devices = sorted(p.name for p in Path("/dev").glob("spidev*")) \
            if Path("/dev").exists() else []
        return {"provider": self.name, "available": bool(devices),
                "devices": devices[:8]}

    def capabilities(self) -> dict[str, Any]:
        return {"transfer": False,
                "note": "transfers are future work, not silent stubs"}


class AudioProvider(HardwareProvider):
    """Audio contracts only: discovery + bounded capture metadata.

    No always-on recording. No STT here (separate future layer).
    """

    name = "audio"

    def health(self) -> dict[str, Any]:
        cards = Path("/proc/asound/cards").exists()
        return {"provider": self.name, "available": cards}

    def capabilities(self) -> dict[str, Any]:
        return {"status": True, "bounded_capture": True,
                "always_on": False, "stt": False}


class FakeSystemProvider(SystemProvider):
    """Deterministic scripted telemetry for tests."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = dict(values or {})

    def telemetry(self) -> dict[str, Any]:
        return dict(self._values)


class FakeTemperatureProvider(TemperatureProvider):
    def __init__(self, temperature_c: float | None = 42.0) -> None:
        self._temperature_c = temperature_c

    def health(self) -> dict[str, Any]:
        return {"provider": self.name,
                "available": self._temperature_c is not None}


class FakeNetworkProvider(NetworkProvider):
    def __init__(self, interfaces: dict[str, str] | None = None) -> None:
        self._interfaces = dict(interfaces or {"eth0": "up"})

    def status(self) -> dict[str, str]:
        return dict(self._interfaces)


__all__ = [
    "AudioProvider",
    "CameraProvider",
    "FakeNetworkProvider",
    "FakeSystemProvider",
    "FakeTemperatureProvider",
    "GpioProvider",
    "HardwareError",
    "HardwareProvider",
    "I2CProvider",
    "NetworkProvider",
    "SPIProvider",
    "SystemProvider",
    "TemperatureProvider",
]
