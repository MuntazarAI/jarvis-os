"""Service management tests. Uses ephemeral ports; never touches :8765."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.core.service import ServiceManager, check_dependencies  # noqa: E402


def _manager(tmp_path, port=0):
    cfg = JarvisConfig()
    cfg.paths.home = Path(tmp_path)
    return ServiceManager(cfg)


def test_doctor_checks_structure():
    checks = check_dependencies()
    names = [c.name for c in checks]
    assert "ollama" in names and "camera" in names and "microphone" in names
    assert any(c.required for c in checks)
    for check in checks:
        assert set(check.to_dict()) == {"name", "ok", "detail", "required"}


def test_start_stop_lifecycle(tmp_path):
    manager = _manager(tmp_path)
    assert manager.running() is None
    started = manager.start(port=0)
    assert started["ok"], started
    assert manager.running() == started["pid"]
    assert manager.status()["running"]
    second = manager.start(port=0)
    assert not second["ok"] and "already running" in second["error"]
    stopped = manager.stop()
    assert stopped["ok"] and manager.running() is None
    again = manager.stop()
    assert again["ok"] and "not running" in again.get("note", "")


def test_stale_pidfile_recovery(tmp_path):
    manager = _manager(tmp_path)
    manager.pidfile.write_text("99999999")
    assert manager.running() is None
    started = manager.start(port=0)
    assert started["ok"], started
    manager.stop()


def test_restart_replaces_process(tmp_path):
    manager = _manager(tmp_path)
    first = manager.start(port=0)
    assert first["ok"]
    second = manager.restart(port=0)
    assert second["ok"] and second["pid"] != first["pid"]
    manager.stop()
