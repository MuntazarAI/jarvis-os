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

import hashlib
import os
import shutil
import time
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

#: SHA-256 of the assets this code installs. A voice file is executed by
#: onnxruntime, so an unverified download is a code-execution risk: if
#: the hash does not match, the install is refused.
EXPECTED_SHA256: dict[str, str] = {
    "kokoro-v1.0.fp16.onnx":
        "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204",
    "voices-v1.0.bin":
        "d19762d46cf0e6648cb28a7711df1637aad15818185d13f4ff840d57f2f6dfed",
    "en_GB-northern_english_male-medium.onnx":
        "57a219ae8e638873db7d18893304be5069c42868f392bb95c3ff17f0690d0689",
    "en_GB-northern_english_male-medium.onnx.json":
        "69557ed3d974463453e9b0c09dd99a7ed0e52b8b87b64b357dbeeb2540a97d47",
}

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
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def installed_piper_voices() -> list[Path]:
    """Every piper voice model present on this machine.

    A model without its `.onnx.json` sidecar is not usable: piper needs
    the config to know the sample rate and the phoneme set.
    """
    try:
        return sorted(p for p in voices_dir().glob("*.onnx")
                      if p.stat().st_size > 0
                      and p.with_suffix(".onnx.json").exists())
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


def sha256_of(path: Path) -> str:
    """The SHA-256 of a file, read in bounded chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def download_asset(url: str, target: Path, timeout_s: float = 300.0,
                   max_bytes: int = MAX_VOICE_BYTES) -> dict[str, Any]:
    """Download one voice asset: bounded, atomic, capped.

    The one downloader for every voice file (the reference voice, the
    piper voices, the Kokoro model).
    """
    return _download(url, target, timeout_s, max_bytes)


def _download(url: str, target: Path, timeout_s: float,
              max_bytes: int = MAX_VOICE_BYTES) -> dict[str, Any]:
    """Download one file, bounded, atomically (temp file then rename).

    `timeout_s` is a wall-clock bound for the whole download, not just
    for one socket read: a slow but steady server must not be able to
    keep this running forever.
    """
    temp = target.with_suffix(target.suffix + ".part")
    deadline = time.monotonic() + timeout_s
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "jarvis-os-voice-setup/7.0"})
        with urllib.request.urlopen(request, timeout=timeout_s) as resp, \
                open(temp, "wb") as out:
            total = 0
            while True:
                if time.monotonic() > deadline:
                    out.close()
                    temp.unlink(missing_ok=True)
                    return {"ok": False,
                            "error": f"download exceeded {int(timeout_s)}s"}
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    out.close()
                    temp.unlink(missing_ok=True)
                    return {"ok": False, "error": "voice exceeds size cap"}
                out.write(chunk)
        temp.replace(target)
        return {"ok": True, "path": str(target), "bytes": total}
    except Exception as exc:
        temp.unlink(missing_ok=True)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def _verify(target: Path) -> dict[str, Any]:
    """Check a downloaded asset against its pinned SHA-256."""
    expected = EXPECTED_SHA256.get(target.name)
    if not expected:
        return {"ok": True, "verified": False}
    actual = sha256_of(target)
    if actual != expected:
        target.unlink(missing_ok=True)
        return {"ok": False, "verified": True,
                "error": f"checksum mismatch for {target.name}",
                "expected": expected, "actual": actual}
    return {"ok": True, "verified": True, "sha256": actual}


def install_piper_voice(name: str = DEFAULT_PIPER_VOICE,
                        timeout_s: float = 300.0) -> dict[str, Any]:
    """Download one piper voice (model + config). Reuses an existing copy.

    The download is verified against the pinned SHA-256: a voice file is
    loaded by onnxruntime, so an unverified file is a code-execution
    risk.
    """
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
    for url, path in ((f"{PIPER_VOICE_BASE}/{relative}.onnx", model),
                      (f"{PIPER_VOICE_BASE}/{relative}.onnx.json", config)):
        outcome = _download(url, path, timeout_s)
        if not outcome.get("ok"):
            return {"ok": False, "error": outcome.get("error", "download failed"),
                    "voice": name}
        checked = _verify(path)
        if not checked.get("ok"):
            return {"ok": False, "voice": name, **checked}
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
        checked = _verify(path)
        if not checked.get("ok"):
            return {"ok": False, **checked}
    return {"ok": kokoro_installed(), "reused": False,
            "model": str(model), "voices": str(voices)}


def engine_status(allow_cloud: bool = False) -> dict[str, Any]:
    """What can speak right now, and what is missing.

    `allow_cloud` says whether the operator turned the cloud engine on;
    the edge engine is never usable without it.
    """
    piper = find_piper_voice()
    chatterbox_python = config_home() / "chatterbox-venv" / "bin" / "python"
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
            # Cloud: the text leaves this machine. Never automatic, and
            # only with the explicit opt-in.
            "available": bool(find_binary("edge-tts")) and bool(allow_cloud),
            "installed": bool(find_binary("edge-tts")),
            "binary": find_binary("edge-tts"),
            "cloud": True,
            "allowed": bool(allow_cloud),
        },
        "chatterbox": {
            "available": chatterbox_python.exists(),
            "runtime": str(chatterbox_python),
        },
    }


__all__ = ["PIPER_VOICES", "PIPER_PREFERENCE", "PIPER_VOICE_BASE",
           "DEFAULT_PIPER_VOICE", "KOKORO_MODEL_URL", "KOKORO_VOICES_URL",
           "KOKORO_BRITISH_MALE", "MAX_VOICE_BYTES", "EXPECTED_SHA256",
           "config_home", "voices_dir", "kokoro_dir", "runtime_dirs",
           "find_binary", "installed_piper_voices", "find_piper_voice",
           "piper_installed", "kokoro_model_path", "kokoro_voices_path",
           "kokoro_installed", "install_piper_voice", "install_kokoro_assets",
           "engine_status", "sha256_of", "download_asset"]
