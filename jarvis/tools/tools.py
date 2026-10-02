"""Tool registry and safe built-in tools."""

from __future__ import annotations

import ast
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.types import RiskLevel, new_id, now


@dataclass
class ToolSpec:
    name: str
    description: str
    risk: RiskLevel = RiskLevel.LOW
    timeout: float = 30.0
    required_permissions: list[str] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool: str
    ok: bool
    output: Any = None
    error: str = ""
    duration: float = 0.0
    risk: RiskLevel = RiskLevel.SAFE
    call_id: str = field(default_factory=lambda: new_id("tool"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool, "ok": self.ok, "output": self.output,
            "error": self.error, "duration": round(self.duration, 3),
            "risk": self.risk.value, "call_id": self.call_id,
        }


class Tool:
    def __init__(self, spec: ToolSpec, func: Callable[..., ToolResult]) -> None:
        self.spec = spec
        self.func = func

    def run(self, **kwargs: Any) -> ToolResult:
        started = now()
        try:
            result = self.func(**kwargs)
            result.duration = now() - started
            result.risk = self.spec.risk
            return result
        except Exception as exc:  # tool failures become results, never crashes
            return ToolResult(tool=self.spec.name, ok=False,
                             error=f"{type(exc).__name__}: {exc}",
                             duration=now() - started, risk=self.spec.risk)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self.history: list[ToolResult] = []

    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"tool already registered: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": t.spec.name, "description": t.spec.description,
             "risk": t.spec.risk.value, "timeout": t.spec.timeout,
             "permissions": t.spec.required_permissions}
            for t in self._tools.values()
        ]

    def call(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(tool=name, ok=False, error=f"unknown tool: {name}")
        result = tool.run(**kwargs)
        self.history.append(result)
        return result

    def stats(self) -> dict[str, Any]:
        total = len(self.history)
        return {
            "registered": sorted(self._tools),
            "calls": total,
            "success_rate": round(sum(1 for r in self.history if r.ok) / total, 4)
            if total else 1.0,
        }


# -- built-in tools ------------------------------------------------------
def _ok(tool: str, output: Any) -> ToolResult:
    return ToolResult(tool=tool, ok=True, output=output)


def _fail(tool: str, error: str) -> ToolResult:
    return ToolResult(tool=tool, ok=False, error=error)


def filesystem_read(path: str, max_bytes: int = 65536) -> ToolResult:
    try:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return _fail("filesystem_read", f"not found: {path}")
        if target.is_dir():
            entries = []
            for item in sorted(target.iterdir())[:500]:
                try:
                    entries.append({"name": item.name, "is_dir": item.is_dir(),
                                    "size": item.stat().st_size})
                except OSError:
                    continue
            return _ok("filesystem_read", {"path": str(target), "entries": entries})
        data = target.read_bytes()[:max_bytes]
        try:
            return _ok("filesystem_read", {"path": str(target), "text": data.decode("utf-8")})
        except UnicodeDecodeError:
            return _ok("filesystem_read", {"path": str(target),
                                           "bytes": len(data), "binary": True})
    except Exception as exc:
        return _fail("filesystem_read", f"{type(exc).__name__}: {exc}")


def filesystem_write(path: str, content: str, create_dirs: bool = False) -> ToolResult:
    try:
        target = Path(path).expanduser()
        if create_dirs:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return _ok("filesystem_write", {"path": str(target), "bytes": len(content)})
    except Exception as exc:
        return _fail("filesystem_write", f"{type(exc).__name__}: {exc}")


def terminal_run(command: str, timeout: float = 30.0, cwd: str = ".") -> ToolResult:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return _fail("terminal_run", f"cannot parse command: {exc}")
    if not parts:
        return _fail("terminal_run", "empty command")
    if shutil.which(parts[0]) is None and parts[0] not in ("cd", "echo"):
        return _fail("terminal_run", f"binary not found: {parts[0]}")
    try:
        proc = subprocess.run(parts, capture_output=True, text=True,
                              timeout=min(timeout, 120.0), cwd=cwd)
        return _ok("terminal_run", {
            "command": command, "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:],
        })
    except subprocess.TimeoutExpired:
        return _fail("terminal_run", f"timed out after {timeout}s")
    except Exception as exc:
        return _fail("terminal_run", f"{type(exc).__name__}: {exc}")


def python_run(code: str, timeout: float = 15.0) -> ToolResult:
    """Restricted evaluation: math/logic only, no imports, no dunders.

    Hardened with an AST whitelist (not substring matching): only pure
    expression/assignment statements over safe builtins are accepted.
    Loops, definitions, imports, attribute access, and dunder names are
    rejected before compilation, so neither branch can hang the process
    or reach host internals.
    """
    safe_builtins = {
        "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
        "round": round, "sorted": sorted, "range": range, "enumerate": enumerate,
        "str": str, "int": int, "float": float, "bool": bool, "list": list,
        "dict": dict, "tuple": tuple, "set": set,
    }
    if not isinstance(code, str) or not code.strip():
        return _fail("python_run", "empty code")
    if len(code) > 4000:
        return _fail("python_run", "blocked: code exceeds 4000 characters")
    allowed, reason = _python_ast_allowed(code, set(safe_builtins))
    if not allowed:
        return _fail("python_run", f"blocked: {reason}")
    try:
        compiled = compile(code, "<jarvis>", "eval")
        import time
        deadline = time.time() + min(timeout, 15.0)
        result = eval(compiled, {"__builtins__": safe_builtins}, {})  # noqa: S307
        if time.time() > deadline:
            return _fail("python_run", "budget exceeded")
        return _ok("python_run", {"result": _capped_result(result)})
    except SyntaxError:
        try:
            compiled = compile(code, "<jarvis>", "exec")
            namespace: dict[str, Any] = {}
            exec(compiled, {"__builtins__": safe_builtins}, namespace)  # noqa: S102
            namespace.pop("__builtins__", None)
            return _ok("python_run", {"result": _capped_result(namespace.get("result")),
                                      "defined": sorted(namespace)})
        except Exception as exc:
            return _fail("python_run", f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        return _fail("python_run", f"{type(exc).__name__}: {exc}")


_SAFE_EXPR_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.IfExp, ast.Call, ast.Name, ast.Load, ast.Store,
    ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    ast.comprehension, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Not,
    ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
    ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.Subscript, ast.Slice, ast.If, ast.Assign, ast.AnnAssign,
    ast.AugAssign, ast.Expr, ast.Module, ast.keyword,
)

_BANNED_STMT_NAMES = (
    "Import", "ImportFrom", "FunctionDef", "AsyncFunctionDef",
    "ClassDef", "Lambda", "While", "For", "AsyncFor", "With",
    "AsyncWith", "Global", "Nonlocal", "Delete", "Try", "Raise",
    "Assert", "Yield", "YieldFrom", "Await", "NamedExpr",
)


def _python_ast_allowed(code: str, safe_names: set[str]) -> tuple[bool, str]:
    """Whitelist check for python_run: (allowed, reason)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax error: {exc}"[:160]
    for node in ast.walk(tree):
        name = type(node).__name__
        if name in _BANNED_STMT_NAMES:
            return False, f"{name} is not allowed"
        if name == "Attribute":
            attr = getattr(node, "attr", "")
            if attr.startswith("_"):
                return False, "dunder/private attribute access is not allowed"
            return False, "attribute access is not allowed"
        if name == "Name" and str(getattr(node, "id", "")).startswith("_"):
            return False, "dunder/private names are not allowed"
        if name == "Call":
            func = getattr(node, "func", None)
            if not isinstance(func, ast.Name) or func.id not in safe_names:
                return False, "only safe builtins may be called"
        elif not isinstance(node, _SAFE_EXPR_NODES):
            return False, f"{name} is not allowed"
    return True, "ok"


def _capped_result(result: Any, limit: int = 2000) -> Any:
    try:
        text = repr(result)
    except Exception:
        return "[unrepresentable result]"
    if len(text) > limit:
        return text[:limit] + "…[truncated]"
    return result


def git_status(repo: str = ".") -> ToolResult:
    if shutil.which("git") is None:
        return _fail("git_status", "git binary not available")
    try:
        proc = subprocess.run(["git", "-C", repo, "status", "--short"],
                              capture_output=True, text=True, timeout=15)
        log = subprocess.run(["git", "-C", repo, "log", "--oneline", "-5"],
                             capture_output=True, text=True, timeout=15)
        return _ok("git_status", {
            "status": proc.stdout, "recent": log.stdout,
            "clean": not proc.stdout.strip(),
        })
    except Exception as exc:
        return _fail("git_status", f"{type(exc).__name__}: {exc}")


def system_probe() -> ToolResult:
    import platform
    return _ok("system_probe", {
        "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "cwd": os.getcwd(), "path_entries": len(os.environ.get("PATH", "").split(":")),
    })


def web_fetch(url: str, timeout: float = 15.0, max_bytes: int = 65536) -> ToolResult:
    import urllib.request
    from ..security.guards import is_safe_url, sanitize_for_context, scan_injection
    safe, reason = is_safe_url(url)
    if not safe:
        return _fail("web_fetch", f"blocked: {reason}")
    try:
        with urllib.request.urlopen(url, timeout=min(timeout, 30.0)) as resp:  # noqa: S310
            body = resp.read(max_bytes + 1)
            truncated = len(body) > max_bytes
            text = body[:max_bytes].decode("utf-8", errors="replace")
        scan = scan_injection(text)
        return _ok("web_fetch", {"url": url, "status": 200,
                                 "truncated": truncated,
                                 "injection": None if scan["clean"] else scan,
                                 "text": sanitize_for_context(text)})
    except Exception as exc:
        return _fail("web_fetch", f"{type(exc).__name__}: {exc}")


def default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(ToolSpec("filesystem_read", "Read a file or list a directory",
                               RiskLevel.SAFE, 10.0, ["fs.read"]), filesystem_read))
    reg.register(Tool(ToolSpec("filesystem_write", "Write text to a file",
                                RiskLevel.MEDIUM, 10.0, ["fs.write"]), filesystem_write))
    reg.register(Tool(ToolSpec("terminal_run", "Run a shell command with timeout",
                                RiskLevel.HIGH, 30.0, ["exec"]), terminal_run))
    reg.register(Tool(ToolSpec("python_run", "Evaluate restricted Python (no imports)",
                                RiskLevel.LOW, 15.0, ["exec.eval"]), python_run))
    reg.register(Tool(ToolSpec("git_status", "Show git status and recent commits",
                                RiskLevel.SAFE, 15.0, ["vcs.read"]), git_status))
    reg.register(Tool(ToolSpec("system_probe", "Platform, CPU and environment facts",
                                RiskLevel.SAFE, 5.0, []), system_probe))
    reg.register(Tool(ToolSpec("web_fetch", "Fetch a URL over http(s)",
                                RiskLevel.LOW, 15.0, ["net.fetch"]), web_fetch))
    return reg


def describe_json_schema(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.spec.name,
        "description": tool.spec.description,
        "risk": tool.spec.risk.value,
        "timeout": tool.spec.timeout,
        "required_permissions": tool.spec.required_permissions,
    }


def audit_log_entry(result: ToolResult, actor: str = "agent") -> dict[str, Any]:
    return {"actor": actor, **result.to_dict(), "at": now()}


__all__ = [
    "RiskLevel", "Tool", "ToolRegistry", "ToolResult", "ToolSpec",
    "audit_log_entry", "default_registry", "describe_json_schema",
    "filesystem_read", "filesystem_write", "git_status", "python_run",
    "system_probe", "terminal_run", "web_fetch",
]
