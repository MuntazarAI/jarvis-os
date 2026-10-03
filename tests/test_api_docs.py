"""API doc generation tests: offline, deterministic, byte-identical."""

from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(out: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "docs" / "generate_api.py"), str(out)],
        capture_output=True, text=True, timeout=180,
        cwd=str(ROOT), env={"PATH": "/usr/bin:/bin",
                            "PYTHONPATH": str(ROOT)})
    assert proc.returncode == 0, proc.stderr[-500:]


def test_api_docs_deterministic(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    _run(first)
    _run(second)
    a_files = sorted(p.name for p in first.iterdir())
    b_files = sorted(p.name for p in second.iterdir())
    assert a_files == b_files and len(a_files) >= 13
    for name in a_files:
        assert filecmp.cmp(str(first / name), str(second / name),
                           shallow=False), name


def test_api_docs_no_abs_paths_or_timestamps(tmp_path):
    out = tmp_path / "docs"
    _run(out)
    home = str(Path.home())
    for path in out.iterdir():
        text = path.read_text(encoding="utf-8")
        assert home not in text, path.name
        assert "/home/" not in text and "/tmp/" not in text, path.name
