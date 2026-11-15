"""Voice runtime installation — the tools that actually speak.

piper, kokoro and edge-tts do not install on the system Python: the
TTS packages cap at Python < 3.13 and `onnxruntime` has no build for
newer interpreters. So the runtime lives in its own Python 3.12
environment under `~/.config/jarvis/voice-venv`, created with `uv`.

Explicit setup only — never a silent download. Every step is bounded
and reports what it did.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

#: Where the voice runtime lives (resolved at call time by
#: `runtime_dir()`, so the home directory can be redirected).
RUNTIME_DIR = Path(os.path.expanduser("~/.config/jarvis/voice-venv"))

#: The Python version the voice packages support.
RUNTIME_PYTHON = "3.12"

#: The packages that make up the voice runtime.
RUNTIME_PACKAGES = ("piper-tts", "kokoro-tts", "edge-tts")

#: The binaries the runtime provides.
RUNTIME_TOOLS = ("piper", "kokoro-tts", "edge-tts")

#: Upper bounds, so a stuck download cannot hang the installer.
UV_TIMEOUT_S = 900.0
PIP_TIMEOUT_S = 1800.0


def runtime_dir() -> Path:
    """Where the voice runtime lives."""
    return Path(os.path.expanduser("~/.config/jarvis/voice-venv"))


def runtime_bin() -> Path:
    """The bin directory of the voice runtime."""
    return runtime_dir() / "bin"


def runtime_python() -> Path:
    """The interpreter of the voice runtime."""
    return runtime_bin() / "python"


def find_uv() -> str:
    """The `uv` binary: the user install first, then PATH."""
    local = Path(os.path.expanduser("~/.local/bin/uv"))
    if local.exists():
        return str(local)
    return shutil.which("uv") or ""


def installed_tools() -> list[str]:
    """The voice tools present in the runtime."""
    tools = []
    for name in RUNTIME_TOOLS:
        if (runtime_bin() / name).exists():
            tools.append(name)
    return tools


def runtime_ready() -> bool:
    """Is the voice runtime complete?

    A runtime with only some of the tools is not ready: it is repaired
    by running the install again, not silently accepted.
    """
    return all(name in installed_tools() for name in RUNTIME_TOOLS)


def _run(argv: list[str], timeout_s: float) -> tuple[int, str]:
    """Run a command, bounded. Returns (returncode, output tail)."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {int(timeout_s)}s"
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"[:200]
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output.strip()[-400:]


def install_runtime(timeout_s: float = PIP_TIMEOUT_S) -> dict[str, Any]:
    """Create the voice runtime and install piper, kokoro and edge-tts.

    Reuses an existing complete runtime. A partial one is repaired: the
    packages are installed again over it. Never fails loudly: the
    result carries the reason so the caller can report it honestly.
    """
    steps: list[dict[str, Any]] = []

    def _step(name: str, code: int, detail: str) -> bool:
        steps.append({"step": name, "ok": code == 0, "detail": detail})
        return code == 0

    if runtime_ready():
        return {"ok": True, "reused": True, "steps": steps,
                "runtime": str(runtime_dir()),
                "tools": installed_tools()}

    uv = find_uv()
    if not uv:
        return {"ok": False, "reused": False, "steps": steps,
                "error": "uv is not installed — install it with "
                         "`python3 -m pip install --user uv`",
                "runtime": str(runtime_dir())}

    code, detail = _run([uv, "python", "install", RUNTIME_PYTHON], UV_TIMEOUT_S)
    if not _step("python", code, detail or f"python {RUNTIME_PYTHON} ready"):
        return {"ok": False, "reused": False, "steps": steps,
                "error": detail or "could not install python",
                "runtime": str(runtime_dir())}

    # --allow-existing repairs a runtime that a failed install left
    # half-built, instead of refusing a non-empty directory.
    code, detail = _run([uv, "venv", "--allow-existing", "--python",
                          RUNTIME_PYTHON, str(runtime_dir())], UV_TIMEOUT_S)
    if not _step("venv", code, detail or str(runtime_dir())):
        return {"ok": False, "reused": False, "steps": steps,
                "error": detail or "could not create the voice runtime",
                "runtime": str(runtime_dir())}

    code, detail = _run([uv, "pip", "install", "--python",
                          str(runtime_python()),
                          *RUNTIME_PACKAGES], timeout_s)
    if not _step("packages", code, detail or ", ".join(RUNTIME_PACKAGES)):
        return {"ok": False, "reused": False, "steps": steps,
                "error": detail or "could not install the voice packages",
                "runtime": str(runtime_dir())}

    return {"ok": runtime_ready(), "reused": False, "steps": steps,
            "runtime": str(runtime_dir()), "tools": installed_tools()}


__all__ = ["RUNTIME_DIR", "RUNTIME_PYTHON", "RUNTIME_PACKAGES",
           "RUNTIME_TOOLS", "runtime_dir", "runtime_bin", "runtime_python",
           "find_uv", "installed_tools", "runtime_ready", "install_runtime"]
