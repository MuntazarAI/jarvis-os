"""
JARVIS-OS Secure Code Execution Sandbox

Provides isolated Python code execution with resource limits, artifact capture,
and policy enforcement.
"""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union
from threading import Lock

import psutil


@dataclass
class ResourceLimits:
    """Resource limits for sandbox execution."""
    cpu_time_seconds: float = 30.0      # Max CPU time
    wall_time_seconds: float = 60.0     # Max wall clock time
    memory_bytes: int = 512 * 1024 * 1024  # 512 MB
    disk_bytes: int = 100 * 1024 * 1024    # 100 MB
    max_processes: int = 10
    max_file_size: int = 10 * 1024 * 1024  # 10 MB per file


@dataclass
class SandboxPolicy:
    """Security policy for sandbox execution."""
    allowed_imports: Set[str] = field(default_factory=lambda: {
        # Safe stdlib modules
        "math", "random", "datetime", "json", "re", "collections",
        "itertools", "functools", "statistics", "decimal", "fractions",
        "hashlib", "base64", "uuid", "time", "calendar", "pathlib",
        "textwrap", "string", "typing", "dataclasses", "enum",
        "inspect", "pprint", "html", "urllib.parse", "csv",
        "io", "os", "sys", "builtins", "types", "copy",
        "binascii",
        "numbers", "operator", "abc", "enum", "string", "numbers",
        "_io", "_math_integer", "_statistics", "_datetime",
        "_collections", "_collections_abc", "_functools", "_random", "_hashlib",
        "_bisect", "_heapq", "_string", "_weakref", "_thread",
        "_csv", "_json", "_csv",
        "numbers", "abc", "enum", "string",
        "_pydecimal", "bisect", "_collections_abc", "_pydecimal",
        "contextvars", "bisect", "operator", "_pydecimal",
        "struct", "_struct", "copyreg",
    })
    blocked_imports: Set[str] = field(default_factory=lambda: {
        # Dangerous modules
        "os", "subprocess", "multiprocessing", "threading",
        "socket", "http", "urllib.request", "ftplib", "telnetlib",
        "importlib", "pkgutil", "runpy", "code", "codeop",
        "ctypes", "cffi", "asyncio", "concurrent.futures",
    })
    allowed_builtins: Set[str] = field(default_factory=lambda: {
        "abs", "all", "any", "bin", "bool", "chr", "dict", "dir",
        "divmod", "enumerate", "filter", "float", "format", "frozenset",
        "frozendict",
        "hash", "hex", "int", "isinstance", "issubclass", "len", "list",
        "map", "max", "min", "next", "oct", "ord", "pow", "print",
        "range", "reversed", "round", "set", "slice", "sorted", "str",
        "sum", "tuple", "type", "zip", "Exception", "ValueError",
        "TypeError", "KeyError", "IndexError", "RuntimeError",
        "ImportError", "AttributeError", "NameError", "SyntaxError",
        "MemoryError", "OSError", "IOError", "EOFError",
        "ZeroDivisionError", "OverflowError", "StopIteration",
        "delattr", "getattr", "hasattr", "setattr", "vars",
        "object", "property", "staticmethod", "classmethod",
        "super", "iter", "next", "callable", "isinstance", "issubclass",
        "open", "close", "read", "write", "readline", "readlines",
        "exec", "compile", "eval", "SystemExit", "KeyboardInterrupt",
        "GeneratorExit", "BaseException", "ArithmeticError",
        "AssertionError", "BufferError", "BytesWarning",
        "DeprecationWarning", "EncodingWarning", "EnvironmentError",
        "FutureWarning", "IndentationError", "LookupError",
        "ReferenceError", "RuntimeWarning", "TabError",
        "TypeWarning", "UnboundLocalError", "UnicodeError",
        "UnicodeWarning", "UserWarning", "Warning",
        "bytes", "bytearray", "memoryview", "complex", "float",
        "int", "str", "bool", "list", "tuple", "set", "frozenset",
        "dict", "range", "enumerate", "reversed", "sorted",
        "map", "filter", "zip", "sum", "any", "all",
        "min", "max", "pow", "abs", "round", "divmod",
        "hash", "id", "len", "dir", "vars", "locals", "globals",
        "isinstance", "issubclass", "callable", "staticmethod",
        "classmethod", "property", "super", "type", "object",
        "print", "input", "open", "close", "read", "write",
        "readline", "readlines", "flush", "seek", "tell",
        "PermissionError", "FileNotFoundError", "IsADirectoryError",
        "NotADirectoryError", "FileExistsError", "PermissionError", "OSError",
        "NotImplemented",
    })
    allow_network: bool = False
    allow_filesystem_write: bool = True
    max_output_bytes: int = 10 * 1024 * 1024  # 10 MB

    def is_import_allowed(self, module: str) -> bool:
        if module in self.blocked_imports:
            return False
        if module in self.allowed_imports:
            return True
        # Check parent package
        parent = module.split(".")[0]
        if parent in self.allowed_imports:
            return True
        # A private module of an allowed package is allowed too: the
        # interpreter imports helpers like _contextvars lazily, and
        # blocking them breaks ordinary code on some Python versions.
        if module.startswith("_") and not module.startswith("__"):
            public = module.lstrip("_").split(".")[0]
            if public and public in self.allowed_imports:
                return True
        return False


@dataclass
class ExecutionResult:
    """Result of code execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    return_value: Any = None
    artifacts: Dict[str, bytes] = field(default_factory=dict)
    resource_usage: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time: float = 0.0
    exit_code: int = 0


class ResourceLimiter:
    """Applies resource limits to current process."""

    @staticmethod
    def apply_limits(limits: ResourceLimits):
        """Apply resource limits (Unix only)."""
        if sys.platform == "win32":
            return

        # CPU time (seconds)
        resource.setrlimit(resource.RLIMIT_CPU,
                          (int(limits.cpu_time_seconds), int(limits.cpu_time_seconds) + 1))

        # Memory (bytes)
        resource.setrlimit(resource.RLIMIT_AS,
                          (limits.memory_bytes, limits.memory_bytes))

        # File size
        resource.setrlimit(resource.RLIMIT_FSIZE,
                          (limits.max_file_size, limits.max_file_size))

        # Number of processes
        resource.setrlimit(resource.RLIMIT_NPROC,
                          (limits.max_processes, limits.max_processes))

        # Open files
        resource.setrlimit(resource.RLIMIT_NOFILE,
                          (256, 256))

    @staticmethod
    def get_usage() -> Dict[str, float]:
        """Get current resource usage."""
        try:
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            return {
                "user_cpu_time": usage.ru_utime,
                "system_cpu_time": usage.ru_stime,
                "max_rss_bytes": usage.ru_maxrss * 1024,  # KB to bytes
            }
        except Exception:
            return {}


class ArtifactStore:
    """Captures and stores execution artifacts."""

    def __init__(self, sandbox_dir: Path):
        self.sandbox_dir = sandbox_dir
        self.artifacts_dir = sandbox_dir / "artifacts"
        self.artifacts_dir.mkdir(exist_ok=True)
        self._lock = Lock()

    def capture_file(self, name: str, content: bytes) -> str:
        """Store a file artifact."""
        with self._lock:
            path = self.artifacts_dir / name
            path.write_bytes(content)
            return str(path)

    def capture_text(self, name: str, content: str) -> str:
        """Store a text artifact."""
        return self.capture_file(name, content.encode())

    def capture_json(self, name: str, obj: Any) -> str:
        """Store a JSON artifact."""
        return self.capture_text(name, json.dumps(obj, indent=2))

    def capture_pickle(self, name: str, obj: Any) -> str:
        """Store a pickled artifact."""
        with self._lock:
            path = self.artifacts_dir / name
            path.write_bytes(pickle.dumps(obj))
            return str(path)

    def list_artifacts(self) -> List[str]:
        """List all artifact names."""
        with self._lock:
            return [f.name for f in self.artifacts_dir.iterdir() if f.is_file()]

    def get_artifact(self, name: str) -> Optional[bytes]:
        """Retrieve artifact content."""
        path = self.artifacts_dir / name
        if path.exists():
            return path.read_bytes()
        return None

    def get_all_artifacts(self) -> Dict[str, bytes]:
        """Get all artifacts as dict."""
        with self._lock:
            return {f.name: f.read_bytes() for f in self.artifacts_dir.iterdir() if f.is_file()}


class SecureExecutor:
    """Executes Python code in isolated subprocess with resource limits."""

    def __init__(
        self,
        policy: Optional[SandboxPolicy] = None,
        limits: Optional[ResourceLimits] = None,
        working_dir: Optional[Path] = None,
    ):
        self.policy = policy or SandboxPolicy()
        self.limits = limits or ResourceLimits()
        self.working_dir = working_dir or Path(tempfile.mkdtemp(prefix="jarvis_sandbox_"))
        self.artifact_store = ArtifactStore(self.working_dir)

        # Create restricted environment
        self._prepare_environment()

    def _prepare_environment(self):
        """Prepare sandbox directory structure."""
        self.working_dir.mkdir(parents=True, exist_ok=True)

        # Create a restricted Python environment
        (self.working_dir / "sandbox.py").write_text(self._generate_sandbox_wrapper())

    def _generate_sandbox_wrapper(self) -> str:
        """Generate the sandbox wrapper script by reading from external file."""
        allowed_imports = json.dumps(sorted(self.policy.allowed_imports))
        blocked_imports = json.dumps(sorted(self.policy.blocked_imports))
        allowed_builtins = json.dumps(sorted(self.policy.allowed_builtins))

        # Read the template from external file
        wrapper_path = Path(__file__).parent / "_sandbox_wrapper.py"
        if wrapper_path.exists():
            template = wrapper_path.read_text()
        else:
            # Fallback inline template
            template = '''#!/usr/bin/env python3
"""
Sandbox wrapper - runs user code with import/builtin restrictions.
"""
import sys
import builtins
import importlib
import json
import os

# Policy
ALLOWED_IMPORTS = __ALLOWED_IMPORTS__
BLOCKED_IMPORTS = __BLOCKED_IMPORTS__
ALLOWED_BUILTINS = __ALLOWED_BUILTINS__

# Restrict imports
original_import = builtins.__import__

def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in BLOCKED_IMPORTS:
        raise ImportError("Import of '{name}' is blocked by sandbox policy")
    if name not in ALLOWED_IMPORTS:
        # Check parent package
        parent = name.split('.')[0]
        if parent not in ALLOWED_IMPORTS:
            # A private module of an allowed package is allowed too.
            public = name.lstrip('_').split('.')[0]
            if not (name.startswith('_') and not name.startswith('__')
                    and public in ALLOWED_IMPORTS):
                raise ImportError("Import of '{name}' not in allowlist")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = restricted_import

# Restrict builtins
original_builtins = dict(builtins.__dict__)
for key in list(builtins.__dict__.keys()):
    if key not in ALLOWED_BUILTINS and not key.startswith('_'):
        delattr(builtins, key)

# Restrict os module if present
if 'os' in sys.modules:
    os_mod = sys.modules['os']
    dangerous_attrs = ['system', 'popen', 'spawn', 'exec', 'fork', 'kill',
                       'remove', 'rmdir', 'unlink', 'rename', 'mkdir',
                       'chdir', 'chmod', 'chown', 'access', 'stat']
    for attr in dangerous_attrs:
        if hasattr(os_mod, attr):
            setattr(os_mod, attr, lambda *a, **k: (_ for _ in ()).throw(
                PermissionError("os.{attr} blocked")))

# Disable network
import socket
original_socket = socket.socket
def blocked_socket(*args, **kwargs):
    raise PermissionError("Network access blocked by sandbox")
socket.socket = blocked_socket

# Execute user code
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    code_file = sys.argv[1]
    with open(code_file, 'r') as f:
        user_code = f.read()

    # Create restricted globals
    restricted_globals = {
        '__builtins__': builtins,
        '__name__': '__main__',
        '__file__': code_file,
    }

    try:
        exec(user_code, restricted_globals)
        # Capture return value if any
        __result_val = restricted_globals.get('__result__', None)
        if __result_val is not None:
            print("__RESULT__:" + json.dumps(__result_val, default=str))
    except SystemExit as e:
        sys.exit(e.code)
    except Exception as e:
        print("__ERROR__:" + type(e).__name__ + ":" + str(e), file=sys.stderr)
        sys.exit(1)
'''
        # Replace placeholders
        template = template.replace('__ALLOWED_IMPORTS__', allowed_imports)
        template = template.replace('__BLOCKED_IMPORTS__', blocked_imports)
        template = template.replace('__ALLOWED_BUILTINS__', allowed_builtins)
        # Add sandbox directory for filesystem restrictions
        sandbox_dir = json.dumps(str(self.working_dir))
        template = template.replace('__SANDBOX_DIR__', sandbox_dir)
        return template

    def execute(self, code: str, timeout: Optional[float] = None) -> ExecutionResult:
        """Execute code synchronously."""
        start = time.time()
        timeout = timeout or self.limits.wall_time_seconds

        # Write user code to file
        code_file = self.working_dir / f"user_code_{uuid.uuid4().hex[:8]}.py"
        code_file.write_text(code)

        # Prepare execution environment
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        })

        # Capture stdout/stderr
        stdout_path = self.working_dir / "stdout.txt"
        stderr_path = self.working_dir / "stderr.txt"

        try:
            with open(stdout_path, "w") as stdout_f, open(stderr_path, "w") as stderr_f:
                proc = subprocess.Popen(
                    [sys.executable, str(self.working_dir / "sandbox.py"), str(code_file)],
                    stdout=stdout_f,
                    stderr=stderr_f,
                    cwd=str(self.working_dir),
                    env=env,
                    preexec_fn=lambda: ResourceLimiter.apply_limits(self.limits) if sys.platform != "win32" else None,
                )

                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    return ExecutionResult(
                        success=False,
                        error=f"Execution timed out after {timeout}s",
                        execution_time=time.time() - start,
                        exit_code=-1,
                    )

            # Read output
            stdout = stdout_path.read_text() if stdout_path.exists() else ""
            stderr = stderr_path.read_text() if stderr_path.exists() else ""

            # Parse result
            return_value = None
            for line in stdout.splitlines():
                if line.startswith("__RESULT__:"):
                    try:
                        return_value = json.loads(line[11:])
                        stdout = stdout.replace(line, "").strip()
                    except:
                        pass

            # Parse error
            error = None
            for line in stderr.splitlines():
                if line.startswith("__ERROR__:"):
                    error = line[10:]
                    break

            success = proc.returncode == 0 and error is None

            # Parse artifacts from wrapper output
            import base64
            for line in stdout.splitlines():
                if line.startswith("__ARTIFACT__:"):
                    try:
                        parts = line.split(":", 2)
                        if len(parts) == 3:
                            _, fname, b64_content = parts
                            content = base64.b64decode(b64_content)
                            self.artifact_store.capture_file(fname, content)
                    except:
                        pass

            # Collect artifacts
            artifacts = self.artifact_store.get_all_artifacts()

            # Resource usage
            usage = ResourceLimiter.get_usage()

            return ExecutionResult(
                success=success,
                stdout=stdout[:self.policy.max_output_bytes],
                stderr=stderr[:self.policy.max_output_bytes],
                return_value=return_value,
                artifacts=artifacts,
                resource_usage=usage,
                error=error,
                execution_time=time.time() - start,
                exit_code=proc.returncode,
            )

        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"Executor error: {e}",
                execution_time=time.time() - start,
                exit_code=-1,
            )
        finally:
            # Cleanup code file
            if code_file.exists():
                code_file.unlink()

    async def execute_async(self, code: str, timeout: Optional[float] = None) -> ExecutionResult:
        """Execute code asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.execute, code, timeout)

    def cleanup(self):
        """Clean up sandbox directory."""
        if self.working_dir.exists():
            shutil.rmtree(self.working_dir, ignore_errors=True)


class CodeSandbox:
    """High-level code sandbox interface."""

    def __init__(
        self,
        policy: Optional[SandboxPolicy] = None,
        limits: Optional[ResourceLimits] = None,
    ):
        self.policy = policy or SandboxPolicy()
        self.limits = limits or ResourceLimits()
        self._executor: Optional[SecureExecutor] = None
        self._lock = Lock()

    def _get_executor(self) -> SecureExecutor:
        """Get or create executor (thread-safe)."""
        with self._lock:
            if self._executor is None:
                self._executor = SecureExecutor(self.policy, self.limits)
            return self._executor

    def execute(self, code: str, timeout: Optional[float] = None) -> ExecutionResult:
        """Execute code synchronously."""
        executor = self._get_executor()
        return executor.execute(code, timeout)

    async def execute_async(self, code: str, timeout: Optional[float] = None) -> ExecutionResult:
        """Execute code asynchronously."""
        executor = self._get_executor()
        return await executor.execute_async(code, timeout)

    def add_allowed_import(self, module: str):
        """Add module to import allowlist."""
        self.policy.allowed_imports.add(module)

    def add_blocked_import(self, module: str):
        """Add module to import blocklist."""
        self.policy.blocked_imports.add(module)

    def set_network_allowed(self, allowed: bool):
        """Enable/disable network access."""
        self.policy.allow_network = allowed

    def cleanup(self):
        """Clean up all resources."""
        with self._lock:
            if self._executor:
                self._executor.cleanup()
                self._executor = None


# Convenience functions
def create_sandbox(
    allowed_imports: Optional[List[str]] = None,
    cpu_time: float = 30.0,
    memory_mb: int = 512,
    timeout: float = 60.0,
) -> CodeSandbox:
    """Create a sandbox with custom settings."""
    policy = SandboxPolicy()
    if allowed_imports:
        policy.allowed_imports.update(allowed_imports)

    limits = ResourceLimits(
        cpu_time_seconds=cpu_time,
        wall_time_seconds=timeout,
        memory_bytes=memory_mb * 1024 * 1024,
    )

    return CodeSandbox(policy=policy, limits=limits)


def execute_python(
    code: str,
    allowed_imports: Optional[List[str]] = None,
    timeout: float = 30.0,
) -> ExecutionResult:
    """Convenience function to execute Python code."""
    sandbox = create_sandbox(allowed_imports=allowed_imports, timeout=timeout)
    try:
        return sandbox.execute(code, timeout)
    finally:
        sandbox.cleanup()


async def execute_python_async(
    code: str,
    allowed_imports: Optional[List[str]] = None,
    timeout: float = 30.0,
) -> ExecutionResult:
    """Convenience function to execute Python code asynchronously."""
    sandbox = create_sandbox(allowed_imports=allowed_imports, timeout=timeout)
    try:
        return await sandbox.execute_async(code, timeout)
    finally:
        sandbox.cleanup()


__all__ = [
    "ResourceLimits",
    "SandboxPolicy",
    "ExecutionResult",
    "ResourceLimiter",
    "ArtifactStore",
    "SecureExecutor",
    "CodeSandbox",
    "create_sandbox",
    "execute_python",
    "execute_python_async",
]