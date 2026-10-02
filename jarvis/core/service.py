"""Service management: start/stop/restart/status with health checks."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import JarvisConfig


@dataclass
class HealthCheck:
    name: str
    ok: bool
    detail: str = ""
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "required": self.required}


def check_dependencies(config: JarvisConfig | None = None) -> list[HealthCheck]:
    """Automatic dependency + hardware + model checks."""
    import shutil
    checks: list[HealthCheck] = []
    checks.append(HealthCheck("python", True, sys.version.split()[0], True))
    for binary in ("ffmpeg", "espeak-ng", "tesseract", "ollama", "ydotool",
                   "arecord", "wmctrl"):
        found = shutil.which(binary) is not None
        checks.append(HealthCheck(f"bin:{binary}", found,
                                  "found" if found else "missing",
                                  required=binary in ("ffmpeg", "ollama")))
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                    timeout=5) as resp:
            names = [m.get("name", "") for m in
                     json.loads(resp.read()).get("models", [])]
        checks.append(HealthCheck("ollama", True, f"{len(names)} models", True))
        for want in ("qwen2.5:3b", "minicpm-v:latest", "nomic-embed-text:latest"):
            checks.append(HealthCheck(f"model:{want}", want in names,
                                      "pulled" if want in names else "missing"))
    except Exception as exc:
        checks.append(HealthCheck("ollama", False, f"unreachable: {exc}", True))
    checks.append(HealthCheck("camera", bool(list(Path("/dev").glob("video*"))),
                              "video device present"
                              if list(Path("/dev").glob("video*"))
                              else "no /dev/video*"))
    checks.append(HealthCheck("microphone", shutil.which("arecord") is not None,
                              "arecord present"
                              if shutil.which("arecord") else "no capture tool"))
    try:
        from ..geospatial.live import LiveIntelligenceService
        home = str(config.paths.home) if config else ""
        live_checks = LiveIntelligenceService(home=home or ".").doctor()
        for item in live_checks:
            checks.append(HealthCheck(
                f"gods-eye-live:{item['name']}", bool(item["ok"]),
                str(item.get("detail", "")), required=False))
    except Exception as exc:
        checks.append(HealthCheck("gods-eye-live", False, str(exc)[:120],
                                  required=False))
    try:
        from ..device.fabric import DeviceFabric
        from ..policy.policy import PolicyEngine
        home = str(config.paths.home) if config else ""
        fabric_checks = DeviceFabric(
            home=home or ".", policy=PolicyEngine(config)).doctor()
        for item in fabric_checks:
            checks.append(HealthCheck(
                f"device-fabric:{item['name']}", bool(item["ok"]),
                str(item.get("detail", "")), required=False))
    except Exception as exc:
        checks.append(HealthCheck("device-fabric", False, str(exc)[:120],
                                  required=False))
    try:
        from ..device.android import AndroidNodeAdapter
        from ..device.fabric import DeviceFabric
        from ..policy.policy import PolicyEngine
        home = str(config.paths.home) if config else ""
        adapter = AndroidNodeAdapter(DeviceFabric(
            home=home or ".", policy=PolicyEngine(config)))
        for item in adapter.doctor():
            checks.append(HealthCheck(
                f"android-node:{item['name']}", bool(item["ok"]),
                str(item.get("detail", "")), required=False))
    except Exception as exc:
        checks.append(HealthCheck("android-node", False, str(exc)[:120],
                                  required=False))
    try:
        from ..device.android_transport import read_host_status
        home = str(config.paths.home) if config else ""
        info = read_host_status(home or ".")
        if info.get("running") and info.get("live"):
            checks.append(HealthCheck(
                "device-transport:listener", True,
                f"host live on port {info.get('port')} "
                f"(pid {info.get('pid')}, "
                f"{len(info.get('peers') or [])} peer(s))",
                required=False))
        else:
            checks.append(HealthCheck(
                "device-transport:listener", True,
                "no host running (start with: "
                "jarvis device transport serve)",
                required=False))
        checks.append(HealthCheck(
            "device-transport:protocol", True,
            "socket framing u32BE+JSON, 256KiB cap, rotating-HMAC auth, "
            "TRUST_PENDING pairing; see docs/ANDROID_TRANSPORT.md",
            required=False))
    except Exception as exc:
        checks.append(HealthCheck("device-transport", False, str(exc)[:120],
                                  required=False))
    try:
        from ..computer.computer import ComputerController
        ctrl = ComputerController()
        checks.append(HealthCheck("computer:screenshot", ctrl.screen.available(),
                                  "ffmpeg-x11grab" if ctrl.screen.available()
                                  else "unavailable"))
        checks.append(HealthCheck("computer:input", ctrl.input.status()["daemon"],
                                  "ydotoold running"
                                  if ctrl.input.status()["daemon"]
                                  else "ydotoold not running"))
    except Exception as exc:
        checks.append(HealthCheck("computer", False, str(exc)[:100]))
    return checks


class ServiceManager:
    """PID-file supervised API server."""

    def __init__(self, config: JarvisConfig | None = None) -> None:
        self.config = config or JarvisConfig()
        self.home = Path(self.config.paths.home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.pidfile = self.home / "jarvis.pid"
        self.logfile = self.home / "logs" / "serve.log"

    def _read_pid(self) -> int | None:
        try:
            pid = int(self.pidfile.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (OSError, ValueError):
            return None

    def running(self) -> int | None:
        return self._read_pid()

    @staticmethod
    def _free_port() -> int:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self, host: str = "127.0.0.1", port: int = 8765,
              token: str = "") -> dict[str, Any]:
        existing = self._read_pid()
        if existing:
            return {"ok": False, "error": f"already running (pid {existing})"}
        if not port:
            port = self._free_port()
        # Stale pidfile with dead process: clear it.
        if self.pidfile.exists():
            self.pidfile.unlink()
        self.logfile.parent.mkdir(parents=True, exist_ok=True)
        # service.py is jarvis/core/service.py → root is 3 levels up.
        project = Path(__file__).resolve().parent.parent.parent
        cmd = [sys.executable, "-m", "jarvis.cli", "serve",
               "--host", host, "--port", str(port)]
        env = dict(os.environ)
        # Daemon must import jarvis regardless of its working directory.
        env["PYTHONPATH"] = str(project) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        if token:
            cmd += ["--token", token]
        log = open(self.logfile, "ab")
        try:
            proc = subprocess.Popen(cmd, cwd=str(project), env=env,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        finally:
            log.close()
        self.pidfile.write_text(str(proc.pid))
        if self._wait_healthy(port):
            return {"ok": True, "pid": proc.pid, "port": port}
        self.stop()
        tail = self._log_tail()
        return {"ok": False, "error": "server did not become healthy",
                "log_tail": tail}

    def _wait_healthy(self, port: int, timeout: float = 20.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            pid = self._read_pid()
            if not pid:
                return False
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        return False

    def _log_tail(self, lines: int = 20) -> str:
        try:
            return "\n".join(self.logfile.read_text().splitlines()[-lines:])
        except OSError:
            return ""

    def stop(self) -> dict[str, Any]:
        pid = self._read_pid()
        if not pid:
            if self.pidfile.exists():
                self.pidfile.unlink()
            return {"ok": True, "note": "not running (stale pidfile cleared)"}
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(50):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        if self.pidfile.exists():
            self.pidfile.unlink()
        return {"ok": True, "pid": pid}

    def restart(self, **kw: Any) -> dict[str, Any]:
        self.stop()
        time.sleep(0.5)
        return self.start(**kw)

    def status(self) -> dict[str, Any]:
        pid = self._read_pid()
        checks = check_dependencies(self.config)
        failed_required = [c.name for c in checks if c.required and not c.ok]
        return {"running": pid is not None, "pid": pid,
                "checks": [c.to_dict() for c in checks],
                "healthy": pid is not None and not failed_required,
                "missing_required": failed_required}
