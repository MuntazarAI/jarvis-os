"""State backup: snapshot, verify, restore, retention.

Backs up irreplaceable JARVIS state only:
- <home>/.jarvis-os (memories, conversations, grants, beliefs, world,
  traces, config) — actually JARVIS_HOME, resolved at runtime
- voices/ reference audio

Never backed up: Python venvs, HF model caches, pid files, temp files.
Code lives on GitHub, not here.

Every archive carries a manifest (file list + sha256 + byte counts).
verify() re-reads the archive and checks every checksum — a backup
that fails verification is reported, never trusted. restore()
requires --force semantics from the caller and refuses to run when
the destination looks live. Retention keeps the newest N archives.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from typing import Any

MANIFEST_NAME = "jarvis-backup-manifest.json"
DEFAULT_KEEP = 10

EXCLUDE_SUFFIXES = (".pid", ".tmp", ".lock")
EXCLUDE_DIRS = {"__pycache__", ".venv", "chatterbox-venv"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_state_files(home: Path, voices_dir: Path | None
                        ) -> list[tuple[Path, str]]:
    """Walk state dirs → [(absolute path, archive name)]. Skips venvs,
    caches, pid/lock/temp files. Deterministic order."""
    collected: list[tuple[Path, str]] = []

    def _walk(root: Path, prefix: str) -> None:
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            if entry.name in EXCLUDE_DIRS:
                continue
            if entry.name.endswith(EXCLUDE_SUFFIXES):
                continue
            if entry.is_symlink():
                continue
            if entry.is_dir():
                _walk(entry, f"{prefix}{entry.name}/")
            elif entry.is_file():
                collected.append(
                    (entry, f"{prefix}{entry.name}"))

    if home.exists():
        _walk(home, "jarvis-os/")
    if voices_dir is not None and voices_dir.exists():
        _walk(voices_dir, "voices/")
    return collected


def create(home: Path, voices_dir: Path | None, dest_dir: Path, *,
           keep: int = DEFAULT_KEEP,
           timestamp: float | None = None) -> dict[str, Any]:
    """Write timestamped tar.gz + manifest. Returns the manifest."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S",
                          time.localtime(timestamp or time.time()))
    files = collect_state_files(home, voices_dir)
    entries = []
    total_bytes = 0
    for path, arcname in files:
        try:
            checksum = _sha256_file(path)
            size = path.stat().st_size
        except OSError:
            continue
        entries.append({"path": arcname, "sha256": checksum,
                        "bytes": size})
        total_bytes += size
    manifest = {"version": 1, "created_at": stamp,
                "files": entries, "total_bytes": total_bytes,
                "file_count": len(entries)}
    archive = dest_dir / f"jarvis-backup-{stamp}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path, arcname in files:
            try:
                tar.add(path, arcname=arcname, recursive=False)
            except OSError:
                continue
        manifest_bytes = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest_bytes)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(manifest_bytes))
    prune(dest_dir, keep=keep)
    manifest["archive"] = str(archive)
    manifest["archive_bytes"] = archive.stat().st_size
    return manifest


def verify(archive: Path) -> dict[str, Any]:
    """Re-read archive, check every checksum. Never trusts blindly."""
    result: dict[str, Any] = {"ok": False, "checked": 0,
                              "mismatches": []}
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            manifest_member = next(
                (m for m in members if m.name == MANIFEST_NAME), None)
            if manifest_member is None:
                result["error"] = "no manifest in archive"
                return result
            manifest = json.loads(tar.extractfile(
                manifest_member).read().decode())
            expected = {e["path"]: e["sha256"]
                        for e in manifest.get("files", [])}
            for member in members:
                if member.name == MANIFEST_NAME or not member.isfile():
                    continue
                data = tar.extractfile(member).read()
                actual = hashlib.sha256(data).hexdigest()
                result["checked"] += 1
                if expected.get(member.name) != actual:
                    result["mismatches"].append(member.name)
    except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["ok"] = not result["mismatches"] and result["checked"] > 0
    result["files"] = len(expected)
    return result


def restore(archive: Path, home: Path, voices_dir: Path | None,
            *, force: bool = False) -> dict[str, Any]:
    """Restore a verified archive. Refuses without force=True and
    refuses when a presence PID claims the state is live."""
    if not force:
        return {"ok": False,
                "error": "restore requires force=True"}
    check = verify(archive)
    if not check["ok"]:
        return {"ok": False,
                "error": f"archive failed verification: {check}"}
    live_pid = home / "presence.pid"
    if live_pid.exists():
        return {"ok": False,
                "error": "presence claims this state (presence.pid "
                         "exists); stop presence first"}
    restored: list[str] = []
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name == MANIFEST_NAME:
                    continue
                if member.name.startswith("jarvis-os/"):
                    dest = home / member.name[len("jarvis-os/"):]
                elif member.name.startswith("voices/") and \
                        voices_dir is not None:
                    dest = voices_dir / member.name[len("voices/"):]
                else:
                    continue
                if ".." in Path(member.name).parts:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as handle:
                    handle.write(tar.extractfile(member).read())
                restored.append(str(dest))
    except (OSError, tarfile.TarError) as exc:
        return {"ok": False, "restored": restored,
                "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "restored": restored,
            "count": len(restored)}


def prune(dest_dir: Path, keep: int = DEFAULT_KEEP) -> list[str]:
    """Keep newest N archives, delete the rest. Returns deleted names."""
    archives = sorted(dest_dir.glob("jarvis-backup-*.tar.gz"),
                      key=lambda p: p.name)
    doomed = archives[:max(0, len(archives) - max(1, keep))]
    deleted = []
    for path in doomed:
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            continue
    return deleted


def list_backups(dest_dir: Path) -> list[dict[str, Any]]:
    """Newest-first archive inventory with verification status."""
    out = []
    try:
        archives = sorted(dest_dir.glob("jarvis-backup-*.tar.gz"),
                          key=lambda p: p.name, reverse=True)
    except OSError:
        return out
    for archive in archives:
        info: dict[str, Any] = {"archive": str(archive),
                                "bytes": archive.stat().st_size}
        check = verify(archive)
        info["verified"] = check["ok"]
        info["files"] = check.get("files", 0)
        out.append(info)
    return out


__all__ = ["create", "verify", "restore", "prune", "list_backups",
           "collect_state_files"]
