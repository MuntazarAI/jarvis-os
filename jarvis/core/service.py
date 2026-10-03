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


def _voice_worker_detail(config: JarvisConfig | None) -> str:
    """Cheap worker diagnostics: config, executable, orphans. Never
    loads the model (that stays opt-in via `voice worker start`)."""
    voice = getattr(config, "voice", None) if config else None
    if voice is not None and not getattr(voice, "persistent", True):
        return "persistent runtime disabled by config"
    import shutil
    import subprocess
    exe = str(getattr(voice, "chatterbox_python", "")
              if voice else "") or \
        str(Path.home() / ".config" / "jarvis" / "chatterbox-venv"
            / "bin" / "python")
    exe_ok = Path(os.path.expanduser(exe)).exists()
    orphans = 0
    if shutil.which("pgrep") is not None:
        try:
            proc = subprocess.run(
                ["pgrep", "-f", "jarvis.voice.tts_worker"],
                capture_output=True, text=True, timeout=10)
            orphans = len([line for line in
                           (proc.stdout or "").splitlines()
                           if line.strip()])
        except (OSError, subprocess.SubprocessError):
            orphans = 0
    parts = [f"protocol v1 (stdio JSONL)",
             f"runtime {'found' if exe_ok else 'missing'}"]
    if orphans:
        parts.append(f"{orphans} stray worker(s) — "
                     "stop their owner process")
    else:
        parts.append("no stray workers")
    return "; ".join(parts)


def _voice_model_detail() -> str:
    """Weights cached in the HF hub → ready for lazy load; else not."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    cached = [p for p in hub.glob("models--ResembleAI--chatterbox*")
              if p.is_dir()]
    if cached:
        try:
            size = sum(f.stat().st_size for f in cached[0].rglob("*")
                       if f.is_file())
            return (f"weights cached (~{size // 1024 // 1024}MiB, "
                    "lazy-load on synthesis)")
        except OSError:
            return "weights cached (lazy-load on synthesis)"
    return "NOT TESTED (lazy-load on first synthesis; see voice benchmark)"


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
        from ..intelligence import IntelligenceLoop, SensoryBus
        loop = IntelligenceLoop()
        loop.start()
        record = loop.cycle_once({"text": "doctor probe"})
        checks.append(HealthCheck("intelligence:loop", bool(record.ok),
                                  f"cycle ok, {len(record.stages)} stages",
                                  required=False))
        checks.append(HealthCheck("intelligence:bus", True, "sensory bus ready",
                                  required=False))
    except Exception as exc:
        checks.append(HealthCheck("intelligence", False, str(exc)[:120],
                                  required=False))
    try:
        from ..neural.scale import SparseLIFNetwork
        from ..neural.topology import FLY_166K_SCHEMA
        probe = SparseLIFNetwork(8)
        probe.stage_edge(0, 1, 1.5)
        probe.compile()
        fired = probe.step({0: 1.5})
        checks.append(HealthCheck("neural:substrate", fired == [0],
                                  "sparse LIF probe fired",
                                  required=False))
        checks.append(HealthCheck(
            "neural:fly-schema",
            FLY_166K_SCHEMA.total_neurons() == 166000
            and FLY_166K_SCHEMA.origin == "synthetic",
            f"{FLY_166K_SCHEMA.total_neurons()} schematic neurons "
            f"({FLY_166K_SCHEMA.origin})",
            required=False))
    except Exception as exc:
        checks.append(HealthCheck("neural", False, str(exc)[:120],
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
    try:
        from ..worldintel.health import check as world_check
        from ..worldintel.sources import SourceRegistry
        report = world_check(
            getattr(config, "world", None),
            SourceRegistry())
        state = str(report.get("state", "UNKNOWN"))
        checks.append(HealthCheck(
            "world:intel",
            state in ("HEALTHY", "DEGRADED"),
            f"{state}: {report.get('detail', '')}",
            required=False))
        checks.append(HealthCheck(
            "world:sources",
            bool(report.get("sources")),
            f"{len(report.get('sources', {}))} source(s) registered",
            required=False))
    except Exception as exc:
        checks.append(HealthCheck("world", False, str(exc)[:100]))
    try:
        from ..voice.output import output_for
        from ..voice.setup import verify_reference
        from ..voice.tts import provider_for
        voice = getattr(config, "voice", None) if config else None
        provider_name = getattr(voice, "tts_provider", "chatterbox") \
            if voice else "chatterbox"
        cfg = voice.__dict__ if voice is not None else {}
        provider = provider_for(provider_name, cfg)
        ref_path = getattr(voice, "reference_audio", "") if voice \
            else ""
        ref = verify_reference(ref_path) if ref_path else {
            "ok": False, "error": "unconfigured"}
        try:
            cb_health = provider.health()
        except Exception:
            cb_health = {}
        cb_mode = str(cb_health.get("mode", ""))
        out = output_for(getattr(voice, "playback_backend", "auto")
                         if voice else "auto")
        try:
            from ..voice.runtime import EnergyVAD, MicRecorder, Transcriber
            mic_ok = MicRecorder().available()
            stt_backend = Transcriber().backend
            vad_ok = bool(EnergyVAD().segment(b"\x00" * 3200))
        except Exception:
            mic_ok, stt_backend, vad_ok = False, "unknown", False
        try:
            from ..voice.pipeline import WakeWordDetector
            wake_ok = True
            wake_detail = WakeWordDetector().status().get("word", "")
        except Exception:
            wake_ok, wake_detail = False, ""
        checks.append(HealthCheck(
            "voice:provider", True,
            f"{provider_name} ({'available' if provider.available() else 'not installed'})",
            required=False))
        checks.append(HealthCheck(
            "voice:profile", True,
            f"{getattr(voice, 'profile', 'jarvis')} calm/mature/controlled; "
            "chatterbox reference, not an official voice",
            required=False))
        checks.append(HealthCheck(
            "voice:reference", bool(ref.get("ok")),
            f"{ref_path} ({ref.get('format', ref.get('error', ''))})",
            required=False))
        checks.append(HealthCheck(
            "voice:chatterbox", provider.available(),
            f"{cb_mode or 'missing'}: "
            + ("import ok" if cb_mode == "direct"
               else "persistent worker via ~/.config/jarvis/chatterbox-venv"
               if cb_mode == "persistent"
               else "bridge via ~/.config/jarvis/chatterbox-venv"
               if cb_mode == "bridge"
               else "NOT AVAILABLE (isolated venv missing; see "
                    "docs/VOICE_AUDIO_INTELLIGENCE.md)"),
            required=False))
        checks.append(HealthCheck(
            "voice:model", True,
            _voice_model_detail(),
            required=False))
        checks.append(HealthCheck(
            "voice:worker", True,
            _voice_worker_detail(config),
            required=False))
        checks.append(HealthCheck(
            "voice:microphone", mic_ok,
            "arecord/sounddevice ready" if mic_ok
            else "no capture backend",
            required=False))
        checks.append(HealthCheck(
            "voice:stt", True,
            f"{stt_backend} (independent of TTS)",
            required=False))
        checks.append(HealthCheck(
            "voice:vad", vad_ok, "energy VAD ready",
            required=False))
        checks.append(HealthCheck(
            "voice:wake", wake_ok, f"wake word '{wake_detail}' (not auth)",
            required=False))
        checks.append(HealthCheck(
            "voice:output", out.available(),
            getattr(out, "backend", out.name),
            required=False))
    except Exception as exc:
        checks.append(HealthCheck("voice", False, str(exc)[:120],
                                  required=False))
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
