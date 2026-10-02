"""Lifecycle manager for the upstream God's Eye View application.

The browser application stays in its own checkout. JARVIS manages that
checkout as an optional local companion and keeps the upstream project's
code/data licensing boundary intact.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_REPO = "https://github.com/bilawalsidhu/gods-eye-view.git"


@dataclass
class GodsEyeApplicationConfig:
    workspace: str = ""
    repo: str = DEFAULT_REPO
    host: str = "127.0.0.1"
    port: int = 4173
    install_command: tuple[str, ...] = ("npm", "ci")
    start_command: tuple[str, ...] = (
        "npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "4173"
    )


class GodsEyeApplication:
    """Install and control a local God's Eye View companion application."""

    def __init__(
        self,
        *,
        home: str | Path,
        config: GodsEyeApplicationConfig | None = None,
    ) -> None:
        self.home = Path(home)
        self.config = config or GodsEyeApplicationConfig()
        self.workspace = (
            Path(self.config.workspace).expanduser()
            if self.config.workspace
            else self.home / "apps" / "gods-eye-view"
        )
        self.runtime_dir = self.home / "runtime"
        self.pid_path = self.runtime_dir / "gods-eye-view.pid"
        self.log_path = self.runtime_dir / "gods-eye-view.log"

    @property
    def url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def status(self) -> dict[str, Any]:
        pid = self._read_pid()
        running = bool(pid and self._pid_alive(pid))
        if pid and not running:
            self._remove_pid()
        return {
            "installed": (self.workspace / "package.json").exists(),
            "workspace": str(self.workspace),
            "repo": self.config.repo,
            "url": self.url,
            "pid": pid if running else None,
            "running": running,
            "log": str(self.log_path),
            "config": asdict(self.config),
        }

    def install(self) -> dict[str, Any]:
        """Clone/update the upstream checkout and install locked dependencies."""
        self._require_command("git")
        self._require_command("npm")
        self._require_node()

        if (self.workspace / ".git").exists():
            self._run(("git", "pull", "--ff-only"), self.workspace)
        elif self.workspace.exists() and any(self.workspace.iterdir()):
            raise RuntimeError(
                f"God's Eye workspace is not an empty git checkout: {self.workspace}"
            )
        else:
            self.workspace.parent.mkdir(parents=True, exist_ok=True)
            self._run(
                ("git", "clone", self.config.repo, str(self.workspace)),
                self.home,
            )

        self._run(self.config.install_command, self.workspace)
        return self.status()

    def start(self) -> dict[str, Any]:
        """Start the Vite app on localhost without opening a browser."""
        if not (self.workspace / "package.json").exists():
            raise RuntimeError(
                "God's Eye View is not installed; run "
                "'jarvis gods-eye install' first"
            )
        if self.status()["running"]:
            return self.status()

        self._require_command(self.config.start_command[0])
        self._require_node()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("a", encoding="utf-8")
        log.write(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            "starting God's Eye View\n"
        )
        log.flush()

        process = subprocess.Popen(
            list(self.config.start_command),
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "HOST": self.config.host, "PORT": str(self.config.port)},
            start_new_session=True,
        )
        self.pid_path.write_text(str(process.pid), encoding="utf-8")

        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._remove_pid()
                raise RuntimeError(
                    f"God's Eye View exited during startup; inspect {self.log_path}"
                )
            if self._http_ready():
                return self.status()
            time.sleep(0.25)

        return self.status()

    def stop(self) -> dict[str, Any]:
        """Stop only the process group previously started by this manager."""
        pid = self._read_pid()
        if not pid:
            return self.status()
        if not self._pid_alive(pid):
            self._remove_pid()
            return self.status()
        if not self._process_matches(pid):
            self._remove_pid()
            raise RuntimeError(
                f"refusing to stop PID {pid}: it is not the JARVIS-managed "
                "God's Eye process"
            )

        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._remove_pid()
            return self.status()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and self._pid_alive(pid):
            time.sleep(0.1)

        if self._pid_alive(pid):
            os.killpg(pid, signal.SIGKILL)
        self._remove_pid()
        return self.status()

    def open(self) -> str:
        """Open the running local visualization in the default browser."""
        if not self.status()["running"]:
            raise RuntimeError(
                "God's Eye View is not running; run 'jarvis gods-eye start' first"
            )
        webbrowser.open(self.url)
        return self.url

    def _run(self, command: tuple[str, ...] | list[str], cwd: Path) -> None:
        subprocess.run(
            list(command),
            cwd=cwd,
            check=True,
            stdin=subprocess.DEVNULL,
        )

    @staticmethod
    def _require_command(command: str) -> None:
        if shutil.which(command) is None:
            raise RuntimeError(f"required command not found: {command}")

    @staticmethod
    def _require_node() -> None:
        result = subprocess.run(
            ["node", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        raw = result.stdout.strip().lstrip("v")
        try:
            major, minor, *_ = (int(part) for part in raw.split("."))
        except (TypeError, ValueError):
            raise RuntimeError(f"unable to parse Node.js version: {raw!r}") from None
        if not ((major == 24 and minor >= 14) or major == 26):
            raise RuntimeError(
                "God's Eye View requires Node.js 24.14+ on the 24.x line "
                "or Node.js 26.x"
            )

    def _read_pid(self) -> int | None:
        try:
            return int(self.pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _remove_pid(self) -> None:
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _process_matches(self, pid: int) -> bool:
        proc = Path("/proc") / str(pid)
        try:
            cwd = proc.joinpath("cwd").resolve()
            cmdline = proc.joinpath("cmdline").read_bytes().decode(
                "utf-8", errors="replace"
            )
        except OSError:
            return False
        return cwd == self.workspace.resolve() and "vite" in cmdline

    def _http_ready(self) -> bool:
        try:
            with urllib.request.urlopen(self.url, timeout=0.5) as response:
                return 200 <= response.status < 500
        except Exception:
            return False
