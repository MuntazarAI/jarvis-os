"""State backup tests: roundtrip, tamper, force, exclusions, retention."""

from __future__ import annotations

import json
import tarfile

from jarvis import backup as _backup


def _state(home, voices):
    (home / "jarvis.db").write_text("memory-bytes")
    (home / "config.json").write_text("{}")
    (home / "events.db").write_text("events")
    voices.mkdir(parents=True, exist_ok=True)
    (voices / "ref.flac").write_text("audio-bytes")
    (home / "presence.pid").write_text("999999")
    venv = home / "chatterbox-venv"
    venv.mkdir(exist_ok=True)
    (venv / "big.bin").write_text("x" * 1000)


def test_create_verify_roundtrip(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    voices = tmp_path / "voices"
    _state(home, voices)
    manifest = _backup.create(home, voices, tmp_path / "backups")
    assert manifest["file_count"] >= 4
    check = _backup.verify(__import__("pathlib").Path(
        manifest["archive"]))
    assert check["ok"] is True and check["checked"] >= 4


def test_exclusions(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    voices = tmp_path / "voices"
    _state(home, voices)
    manifest = _backup.create(home, voices, tmp_path / "backups")
    paths = [e["path"] for e in manifest["files"]]
    assert not any("chatterbox-venv" in p for p in paths)
    assert not any(p.endswith(".pid") for p in paths)
    assert any(p.endswith("ref.flac") for p in paths)


def test_tamper_detected(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    voices = tmp_path / "voices"
    _state(home, voices)
    manifest = _backup.create(home, voices, tmp_path / "backups")
    from pathlib import Path
    archive = Path(manifest["archive"])
    with tarfile.open(archive, "r:gz") as tar:
        members = {m.name: tar.extractfile(m).read()
                   for m in tar.getmembers() if m.isfile()
                   and m.name != "jarvis-backup-manifest.json"}
    first = next(iter(members))
    members[first] = b"tampered-bytes"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            import io
            tar.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo("jarvis-backup-manifest.json")
        manifest_bytes = json.dumps(
            {"version": 1,
             "files": [{"path": n, "sha256": "x", "bytes": len(d)}
                       for n, d in members.items()]}).encode()
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))
    check = _backup.verify(archive)
    assert check["ok"] is False


def test_restore_requires_force_and_verifies(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    voices = tmp_path / "voices"
    _state(home, voices)
    manifest = _backup.create(home, voices, tmp_path / "backups")
    from pathlib import Path
    archive = Path(manifest["archive"])
    assert _backup.restore(
        archive, tmp_path / "r1", tmp_path / "rvoices")[
            "ok"] is False  # no force
    (tmp_path / "r1").mkdir(exist_ok=True)
    result = _backup.restore(archive, tmp_path / "r1",
                             tmp_path / "rvoices", force=True)
    assert result["ok"] is True
    assert (tmp_path / "r1" / "jarvis.db").read_text() == "memory-bytes"
    assert (tmp_path / "rvoices" / "ref.flac").read_text() == \
        "audio-bytes"


def test_restore_refuses_live_presence(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    voices = tmp_path / "voices"
    _state(home, voices)
    manifest = _backup.create(home, voices, tmp_path / "backups")
    from pathlib import Path
    (tmp_path / "r2").mkdir(exist_ok=True)
    (tmp_path / "r2" / "presence.pid").write_text("123")
    result = _backup.restore(Path(manifest["archive"]),
                             tmp_path / "r2", tmp_path / "rvoices",
                             force=True)
    assert result["ok"] is False


def test_retention_and_listing(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    voices = tmp_path / "voices"
    _state(home, voices)
    dest = tmp_path / "backups"
    for ts in (1000.0, 2000.0, 3000.0):
        _backup.create(home, voices, dest, keep=2, timestamp=ts)
    import os
    assert len(os.listdir(dest)) == 2
    listed = _backup.list_backups(dest)
    assert len(listed) == 2
    assert all(f["verified"] for f in listed)


def test_cli_backup_lifecycle(tmp_path):
    import subprocess
    import sys as _sys
    from pathlib import Path
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    dest = tmp_path / "backups"

    def _cli(*argv):
        return subprocess.run(
            [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
             *argv], capture_output=True, text=True, timeout=120)

    created = _cli("backup", "create", "--dest", str(dest))
    assert created.returncode == 0, created.stderr[-300:]
    assert "verified=yes" in created.stdout.lower() or \
        "verified" in created.stdout.lower()
    listed = _cli("backup", "list", "--dest", str(dest))
    assert listed.returncode == 0 and "verified" in listed.stdout
    archive = sorted(Path(dest).glob("*.tar.gz"))[0]
    assert _cli("backup", "verify", "--file",
                str(archive)).returncode == 0
    refused = _cli("backup", "restore", "--file", str(archive))
    assert refused.returncode == 2  # force required
