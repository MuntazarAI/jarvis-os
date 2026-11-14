"""Voice engine discovery and asset installation.

Three engines can speak for JARVIS:

- **piper**  — local, instant, small ONNX voice files (~60 MB).
- **kokoro** — local, natural, bigger model (~180 MB + 26 MB voices).
- **edge**   — cloud, the most natural voice, but the text leaves the
  machine, so it is never part of the automatic chain.

This module finds the runtimes, finds the downloaded voice assets and
installs them explicitly. Never a silent download.
"""

from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any

#: Where the public Piper voices live.
PIPER_VOICE_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main")

#: Voices worth having. The British male ones are the closest a local
#: model gets to a butler.
PIPER_VOICES: dict[str, str] = {
    "en_GB-northern_english_male-medium":
        "en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium",
    "en_GB-alan-medium":
        "en/en_GB/alan/medium/en_GB-alan-medium",
    "en_GB-alba-medium":
        "en/en_GB/alba/medium/en_GB-alba-medium",
    "en_US-ryan-high":
        "en/en_US/ryan/high/en_US-ryan-high",
}

#: Preferred order when several voices are installed.
PIPER_PREFERENCE = (
    "en_GB-northern_english_male-medium",
    "en_GB-alan-medium",
    "en_GB-alba-medium",
    "en_US-ryan-high",
)

#: The default British male voice JARVIS speaks with.
DEFAULT_PIPER_VOICE = "en_GB-northern_english_male-medium"

#: Kokoro model + voice pack (the British male voice lives inside).
KOKORO_MODEL_URL = ("https://github.com/nazdridoy/kokoro-tts/releases/download/"
                    "v1.0.0/kokoro-v1.0.fp16.onnx")
KOKORO_VOICES_URL = ("https://github.com/nazdridoy/kokoro-tts/releases/download/"
                      "v1.0.0/voices-v1.0.bin")

#: The British male Kokoro voices.
KOKORO_BRITISH_MALE = ("bm_george", "bm_daniel", "bm_fable", "bm_lewis")

#: A voice file larger than this is not a voice file.
MAX_VOICE_BYTES = 512 * 1024 * 1024


def config_home() -> Path:
    """The JARVIS config directory."""
    return Path(os.path.expanduser("~/.config/jarvis"))


def voices_dir() -> Path:
    """Where piper voice models live."""
    return config_home() / "voices"


def kokoro_dir() -> Path:
    """Where the Kokoro model and voice pack live."""
    return config_home() / "kokoro"


def runtime_dirs() -> list[Path]:
    """The bin directories of the JARVIS voice runtimes.

    The voice runtime holds piper, kokoro and edge-tts. The chatterbox
    runtime is kept for the reference-voice provider.
    """
    home = config_home()
    return [home / "voice-venv" / "bin", home / "chatterbox-venv" / "bin"]


def find_binary(name: str) -> str:
    """Find a voice tool: on PATH, else in the JARVIS voice runtimes."""
    found = shutil.which(name)
    if found:
        return found
    for directory in runtime_dirs():
        candidate = directory / name
        if candidate.exists():
            return str(candidate)
    return ""


def installed_piper_voices() -> list[Path]:
    """Every piper voice model present on this machine."""
    try:
        return sorted(p for p in voices_dir().glob("*.onnx")
                      if p.stat().st_size > 0)
    except OSError:
        return []


def find_piper_voice(preferred: str = "") -> Path | None:
    """The piper voice to use: the configured one, else the best British
    male voice installed, else any voice."""
    if preferred:
        candidate = Path(os.path.expanduser(preferred))
        if candidate.exists():
            return candidate
    installed = {p.stem: p for p in installed_piper_voices()}
    for name in PIPER_PREFERENCE:
        if name in installed:
            return installed[name]
    if installed:
        return next(iter(installed.values()))
    return None


def piper_installed() -> bool:
    """Is a piper voice model ready to speak?"""
    return find_piper_voice() is not None


def kokoro_model_path() -> Path:
    """The Kokoro ONNX model, if downloaded."""
    return kokoro_dir() / "kokoro-v1.0.fp16.onnx"


def kokoro_voices_path() -> Path:
    """The Kokoro voice pack, if downloaded."""
    return kokoro_dir() / "voices-v1.0.bin"


def kokoro_installed() -> bool:
    """Are both Kokoro assets present?"""
    model, voices = kokoro_model_path(), kokoro_voices_path()
    return (model.exists() and model.stat().st_size > 0
            and voices.exists() and voices.stat().st_size > 0)


def _download(url: str, target: Path, timeout_s: float) -> dict[str, Any]:
    """Download one file, bounded, atomically (temp file then rename)."""
    temp = target.with_suffix(target.suffix + ".part")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "jarvis-os-voice-setup/7.0"})
        with urllib.request.urlopen(request, timeout=timeout_s) as resp, \
                open(temp, "wb") as out:
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_VOICE_BYTES:
                    out.close()
                    temp.unlink(missing_ok=True)
                    return {"ok": False, "error": "voice exceeds size cap"}
                out.write(chunk)
        temp.replace(target)
        return {"ok": True, "path": str(target), "bytes": total}
    except Exception as exc:
        temp.unlink(missing_ok=True)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def install_piper_voice(name: str = DEFAULT_PIPER_VOICE,
                        timeout_s: float = 300.0) -> dict[str, Any]:
    """Download one piper voice (model + config). Reuses an existing copy."""
    relative = PIPER_VOICES.get(name)
    if not relative:
        return {"ok": False, "error": f"unknown piper voice: {name}",
                "available": sorted(PIPER_VOICES)}
    target_dir = voices_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    model = target_dir / f"{name}.onnx"
    config = target_dir / f"{name}.onnx.json"
    if model.exists() and model.stat().st_size > 0 and config.exists():
        return {"ok": True, "path": str(model), "reused": True,
                "voice": name}
    results = []
    for url, path in ((f"{PIPER_VOICE_BASE}/{relative}.onnx", model),
                      (f"{PIPER_VOICE_BASE}/{relative}.onnx.json", config)):
        outcome = _download(url, path, timeout_s)
        if not outcome.get("ok"):
            return {"ok": False, "error": outcome.get("error", "download failed"),
                    "voice": name}
        results.append(outcome)
    return {"ok": model.exists() and config.exists(), "path": str(model),
            "reused": False, "voice": name}


def install_kokoro_assets(timeout_s: float = 1800.0) -> dict[str, Any]:
    """Download the Kokoro model + voice pack. Large: ~200 MB."""
    target_dir = kokoro_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    model, voices = kokoro_model_path(), kokoro_voices_path()
    if kokoro_installed():
        return {"ok": True, "reused": True,
                "model": str(model), "voices": str(voices)}
    for url, path in ((KOKORO_MODEL_URL, model),
                      (KOKORO_VOICES_URL, voices)):
        outcome = _download(url, path, timeout_s)
        if not outcome.get("ok"):
            return {"ok": False, "error": outcome.get("error", "download failed")}
    return {"ok": kokoro_installed(), "reused": False,
            "model": str(model), "voices": str(voices)}


def engine_status() -> dict[str, Any]:
    """What can speak right now, and what is missing."""
    piper = find_piper_voice()
    return {
        "piper": {
            "available": bool(piper) and bool(find_binary("piper")),
            "binary": find_binary("piper"),
            "voice": piper.stem if piper else "",
            "voices_installed": [p.stem for p in installed_piper_voices()],
        },
        "kokoro": {
            "available": kokoro_installed() and bool(find_binary("kokoro-tts")),
            "binary": find_binary("kokoro-tts"),
            "model": str(kokoro_model_path()) if kokoro_installed() else "",
        },
        "edge": {
            # Cloud: the text leaves this machine. Never automatic.
            "available": bool(find_binary("edge-tts")),
            "binary": find_binary("edge-tts"),
            "cloud": True,
        },
        "chatterbox": {
            "available": bool(find_binary("python")),
            "runtime": str(config_home() / "chatterbox-venv" / "bin"),
        },
    }


__all__ = ["PIPER_VOICES", "PIPER_PREFERENCE", "PIPER_VOICE_BASE",
           "DEFAULT_PIPER_VOICE", "KOKORO_MODEL_URL", "KOKORO_VOICES_URL",
           "KOKORO_BRITISH_MALE", "MAX_VOICE_BYTES", "config_home",
           "voices_dir", "kokoro_dir", "runtime_dirs", "find_binary",
           "installed_piper_voices", "find_piper_voice", "piper_installed",
           "kokoro_model_path", "kokoro_voices_path", "kokoro_installed",
           "install_piper_voice", "install_kokoro_assets", "engine_status"]
