"""Developer intelligence: repo understanding, search, explain, git, coding loop."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import now


@dataclass
class RepoMap:
    root: str
    languages: dict[str, int] = field(default_factory=dict)
    files: int = 0
    tests: int = 0
    entry_points: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    total_lines: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"root": self.root, "languages": self.languages,
                "files": self.files, "tests": self.tests,
                "entry_points": self.entry_points,
                "dependencies": self.dependencies,
                "total_lines": self.total_lines}


EXT_LANG = {".py": "python", ".js": "javascript", ".ts": "typescript",
            ".rs": "rust", ".go": "go", ".java": "java", ".sh": "shell",
            ".md": "markdown", ".toml": "config", ".json": "config",
            ".yaml": "config", ".yml": "config", ".html": "html", ".css": "css"}


class RepoInspector:
    SKIP = {".git", ".venv", "venv", "__pycache__", "node_modules",
            ".pytest_cache", "target", ".tox", "dist", "build", ".idea"}

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def scan(self, max_files: int = 3000) -> RepoMap:
        repo = RepoMap(root=str(self.root))
        if not self.root.exists():
            return repo
        pending = [self.root]
        seen = 0
        while pending and seen < max_files:
            current = pending.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.name in self.SKIP or entry.is_symlink():
                    continue
                if entry.is_dir():
                    pending.append(entry)
                    continue
                seen += 1
                lang = EXT_LANG.get(entry.suffix.lower(), "other")
                repo.languages[lang] = repo.languages.get(lang, 0) + 1
                repo.files += 1
                if entry.name.startswith("test_") or entry.name.endswith("_test.py"):
                    repo.tests += 1
                if entry.name in ("main.py", "cli.py", "app.py", "index.js",
                                  "main.rs", "main.go"):
                    repo.entry_points.append(str(entry.relative_to(self.root)))
                try:
                    if entry.stat().st_size < 200_000:
                        with open(entry, encoding="utf-8", errors="ignore") as fh:
                            repo.total_lines += sum(1 for _ in fh)
                except OSError:
                    pass
        repo.dependencies = self._dependencies()
        return repo

    def _dependencies(self) -> list[str]:
        deps: list[str] = []
        for name in ("requirements.txt", "pyproject.toml", "package.json",
                     "Cargo.toml", "go.mod"):
            candidate = self.root / name
            if candidate.exists():
                try:
                    text = candidate.read_text(encoding="utf-8", errors="ignore")
                    deps.append(f"{name} ({len(text.splitlines())} lines)")
                except OSError:
                    pass
        return deps

    def search(self, pattern: str, suffix: str = ".py",
               limit: int = 20) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return [{"error": f"bad pattern: {exc}"}]
        pending = [self.root]
        while pending and len(found) < limit:
            current = pending.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.name in self.SKIP or entry.is_symlink():
                    continue
                if entry.is_dir():
                    pending.append(entry)
                    continue
                if suffix and not entry.name.endswith(suffix):
                    continue
                try:
                    if entry.stat().st_size > 200_000:
                        continue
                    for lineno, line in enumerate(
                            entry.read_text(encoding="utf-8",
                                            errors="ignore").splitlines(), 1):
                        if regex.search(line):
                            found.append(
                                {"file": str(entry.relative_to(self.root)),
                                 "line": lineno, "text": line.strip()[:160]})
                            if len(found) >= limit:
                                break
                except OSError:
                    continue
        return found


class GitAssistant:
    def __init__(self, repo: str = ".") -> None:
        self.repo = repo

    def _git(self, *args: str) -> tuple[bool, str]:
        import shutil
        if shutil.which("git") is None:
            return False, "git not installed"
        try:
            proc = subprocess.run(["git", "-C", self.repo, *args],
                                  capture_output=True, text=True, timeout=20)
            return proc.returncode == 0, proc.stdout.strip() or proc.stderr.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def status(self) -> dict[str, Any]:
        ok, out = self._git("status", "--short")
        if not ok:
            return {"ok": False, "error": out}
        _, branch = self._git("branch", "--show-current")
        _, log = self._git("log", "--oneline", "-3")
        return {"ok": True, "branch": branch, "changed": out.splitlines() if out else [],
                "clean": not out.strip(), "recent": log.splitlines()}

    def diff_stat(self) -> dict[str, Any]:
        ok, out = self._git("diff", "--stat")
        return {"ok": ok, "stat": out[:2000] if ok else "", "error": "" if ok else out}

    def draft_commit(self, model: Any | None = None) -> dict[str, Any]:
        """Draft a commit message from the staged diff. LLM optional."""
        ok, diff = self._git("diff", "--cached", "--stat")
        if not ok or not diff:
            return {"ok": False, "error": "nothing staged"}
        files = [line.split("|")[0].strip() for line in diff.splitlines()
                 if "|" in line][:8]
        subject = f"update {', '.join(files[:3])}" + ("..." if len(files) > 3 else "")
        body = ""
        if model is not None:
            try:
                result = model.complete("write commit message",
                                        f"Write a conventional-commit message for files: "
                                        f"{', '.join(files)}")
                if result.get("ok"):
                    subject = str(result.get("text", "")).strip().splitlines()[0][:72]
                    body = "\n".join(str(result.get("text", "")).strip().splitlines()[1:])
            except Exception:
                pass
        return {"ok": True, "subject": subject[:72], "body": body[:500],
                "files": files}


class CodingLoop:
    """Understand → inspect → plan → modify → test → review → verify."""

    def __init__(self, jarvis: Any) -> None:
        self.jarvis = jarvis
        self.runs: list[dict[str, Any]] = []

    def run(self, goal: str, path: str = ".",
            test_command: str = "python3 -m pytest tests/ -q") -> dict[str, Any]:
        run: dict[str, Any] = {"goal": goal, "steps": {}, "at": now()}
        inspector = RepoInspector(path)
        repo = inspector.scan()
        run["steps"]["understand"] = {
            "languages": repo.languages, "files": repo.files, "tests": repo.tests}
        hits = inspector.search(re.escape(goal.split()[0]), limit=5) \
            if goal.split() else []
        run["steps"]["inspect"] = {"hits": len(hits)}
        plan = self.jarvis.supervisor.planner.plan(goal)
        run["steps"]["plan"] = {"steps": len(plan)}
        results = self.jarvis.tools.call(
            "terminal_run", command=test_command, timeout=300.0)
        run["steps"]["test"] = {"ok": results.ok,
                                "tail": str(results.output or results.error)[-500:]}
        run["ok"] = results.ok
        self.runs.append(run)
        self.jarvis.palace.store_episode(
            f"coding loop for '{goal}': {'PASS' if results.ok else 'FAIL'}",
            room="Experiences", importance=0.6)
        return run
