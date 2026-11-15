"""Reference-voice resource installation (5.1).

Explicit setup only — never silent downloads. `ensure_reference()`
creates the voice directory, fetches the configured reference audio
(one bounded, atomic download — the same one the other voice assets
use), verifies existence/readability/format (wav/flac header sniff),
records metadata JSON, and reuses an existing valid copy instead of
duplicating it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .voice_profile import REFERENCE_FILENAME, REFERENCE_URL


def voice_dir() -> Path:
    return Path(os.path.expanduser("~/.config/jarvis/voices"))


def sniff_format(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            head = handle.read(12)
    except OSError:
        return ""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:3] == b"ID3" or head[:2] == b"\xff\xfb":
        return "mp3"
    if head[:4] == b"OggS":
        return "ogg"
    return ""


def verify_reference(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser()
    if not path.exists():
        return {"ok": False, "error": "missing"}
    if not os.access(path, os.R_OK):
        return {"ok": False, "error": "unreadable"}
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:120]}
    if size == 0 or size > 64 * 1024 * 1024:
        return {"ok": False, "error": "invalid size"}
    fmt = sniff_format(path)
    if fmt not in ("wav", "flac"):
        return {"ok": False, "format": fmt or "unknown",
                "error": "unsupported format (need wav/flac)"}
    return {"ok": True, "format": fmt, "bytes": size,
            "path": str(path)}


def ensure_reference(dest: str | Path | None = None,
                     url: str = REFERENCE_URL,
                     timeout_s: float = 120.0) -> dict[str, Any]:
    target = Path(os.path.expanduser(str(dest))) \
        if dest else voice_dir() / REFERENCE_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = verify_reference(target)
    if existing.get("ok"):
        return {"ok": True, "path": str(target), "reused": True,
                **existing}
    if not url:
        return {"ok": False, "path": str(target),
                "error": "reference missing and no URL configured; "
                         "place male_old_movie.flac manually"}
    # One downloader for every voice asset: bounded, atomic, capped.
    from .voice_assets import download_asset
    outcome = download_asset(url, target, timeout_s=timeout_s)
    if not outcome.get("ok"):
        return {"ok": False, "path": str(target),
                "error": str(outcome.get("error", "download failed"))[:300]}
    verified = verify_reference(target)
    meta = {"url": url, "filename": target.name,
            "verified_at": time.time(), **verified}
    try:
        (target.parent / (target.stem + ".json")).write_text(
            json.dumps(meta, indent=2))
    except OSError:
        pass
    return {"ok": bool(verified.get("ok")), "path": str(target),
            "reused": False, **verified}


__all__ = ["voice_dir", "sniff_format", "verify_reference",
           "ensure_reference"]
