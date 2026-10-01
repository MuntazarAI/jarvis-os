"""Developer intelligence + research tests."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.developer.dev import CodingLoop, GitAssistant, RepoInspector  # noqa: E402
from jarvis.research.engine import ResearchEngine  # noqa: E402


def _tiny_repo(tmp_path):
    (tmp_path / "main.py").write_text("def main():\n    print('hi')\n")
    (tmp_path / "test_main.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "requirements.txt").write_text("requests\n")
    return str(tmp_path)


def test_repo_scan_and_search(tmp_path):
    root = _tiny_repo(tmp_path)
    repo = RepoInspector(root).scan()
    assert repo.files == 3 and repo.tests == 1
    assert repo.languages.get("python") == 2
    assert repo.dependencies and "requirements.txt" in repo.dependencies[0]
    hits = RepoInspector(root).search("def main")
    assert len(hits) == 1 and hits[0]["line"] == 1
    assert RepoInspector(root).search("[bad")[0].get("error")
    assert RepoInspector("/nope-missing").scan().files == 0


def test_git_assistant_off_repo(tmp_path):
    status = GitAssistant(str(tmp_path)).status()
    assert not status["ok"]
    assert not GitAssistant(str(tmp_path)).diff_stat()["ok"]
    assert not GitAssistant(str(tmp_path)).draft_commit()["ok"]


def test_coding_loop_structure(tmp_path):
    import tempfile as tf

    from jarvis.core.loop import Jarvis
    jarvis = Jarvis(home=tf.mkdtemp())
    try:
        loop = CodingLoop(jarvis)
        run = loop.run("add logging", path=str(tmp_path), test_command="echo ok")
        assert run["ok"] and run["steps"]["understand"]["files"] >= 0
        assert run["steps"]["plan"]["steps"] > 0
        assert len(loop.runs) == 1
    finally:
        jarvis.close()
