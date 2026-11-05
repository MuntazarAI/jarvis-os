"""
Tests for Code Execution Sandbox
"""

import asyncio
import json
import tempfile
import os
import pytest
from pathlib import Path

from jarvis.autonomy.code_sandbox import (
    ResourceLimits,
    SandboxPolicy,
    ExecutionResult,
    ResourceLimiter,
    ArtifactStore,
    SecureExecutor,
    CodeSandbox,
    create_sandbox,
    execute_python,
    execute_python_async,
)


class TestResourceLimits:
    """Test resource limits configuration."""

    def test_default_limits(self):
        limits = ResourceLimits()
        assert limits.cpu_time_seconds == 30.0
        assert limits.wall_time_seconds == 60.0
        assert limits.memory_bytes == 512 * 1024 * 1024

    def test_custom_limits(self):
        limits = ResourceLimits(
            cpu_time_seconds=10.0,
            memory_bytes=256 * 1024 * 1024,
        )
        assert limits.cpu_time_seconds == 10.0
        assert limits.memory_bytes == 256 * 1024 * 1024


class TestSandboxPolicy:
    """Test sandbox security policy."""

    def test_default_policy(self):
        policy = SandboxPolicy()
        assert "math" in policy.allowed_imports
        assert "os" in policy.blocked_imports
        assert "abs" in policy.allowed_builtins
        assert policy.allow_network is False

    def test_is_import_allowed(self):
        policy = SandboxPolicy()
        assert policy.is_import_allowed("math")
        assert policy.is_import_allowed("json")
        assert not policy.is_import_allowed("os")
        assert not policy.is_import_allowed("subprocess")

    def test_add_allowed_import(self):
        policy = SandboxPolicy()
        policy.allowed_imports.add("numpy")
        assert policy.is_import_allowed("numpy")


class TestResourceLimiter:
    """Test resource limiter."""

    def test_get_usage(self):
        usage = ResourceLimiter.get_usage()
        # Just verify it returns a dict without error
        assert isinstance(usage, dict)


class TestArtifactStore:
    """Test artifact storage."""

    def test_capture_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(Path(tmpdir))
            path = store.capture_text("test.txt", "hello world")
            assert os.path.exists(path)
            assert Path(path).read_text() == "hello world"

    def test_capture_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(Path(tmpdir))
            path = store.capture_json("data.json", {"key": "value", "num": 42})
            assert os.path.exists(path)
            data = json.loads(Path(path).read_text())
            assert data == {"key": "value", "num": 42}

    def test_capture_pickle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(Path(tmpdir))
            path = store.capture_pickle("data.pkl", {"complex": [1, 2, 3]})
            assert os.path.exists(path)
            import pickle
            data = pickle.loads(Path(path).read_bytes())
            assert data == {"complex": [1, 2, 3]}

    def test_list_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(Path(tmpdir))
            store.capture_text("a.txt", "a")
            store.capture_text("b.txt", "b")
            artifacts = store.list_artifacts()
            assert "a.txt" in artifacts
            assert "b.txt" in artifacts


class TestSecureExecutor:
    """Test secure code execution."""

    def test_simple_execution(self):
        executor = SecureExecutor()
        try:
            result = executor.execute("print('hello')")
            assert result.success
            assert "hello" in result.stdout
        finally:
            executor.cleanup()

    def test_return_value(self):
        executor = SecureExecutor()
        try:
            result = executor.execute("__result__ = 42")
            assert result.success
            assert result.return_value == 42
        finally:
            executor.cleanup()

    def test_math_operations(self):
        executor = SecureExecutor()
        try:
            result = executor.execute("import math; __result__ = math.sqrt(16)")
            assert result.success
            assert result.return_value == 4.0
        finally:
            executor.cleanup()

    def test_blocked_import(self):
        executor = SecureExecutor()
        try:
            result = executor.execute("import os")
            assert not result.success
            assert "blocked" in result.error.lower() or "import" in result.error.lower()
        finally:
            executor.cleanup()

    def test_timeout(self):
        executor = SecureExecutor(limits=ResourceLimits(wall_time_seconds=1.0))
        try:
            result = executor.execute("import time; time.sleep(5)")
            assert not result.success
            assert "timed out" in result.error.lower() or result.exit_code == -1
        finally:
            executor.cleanup()

    def test_artifact_capture(self):
        executor = SecureExecutor()
        try:
            result = executor.execute("""
import json
with open('artifact.txt', 'w') as f:
    f.write('test artifact')
""")
            assert result.success
            artifacts = result.artifacts
            assert "artifact.txt" in artifacts
            assert artifacts["artifact.txt"] == b"test artifact"
        finally:
            executor.cleanup()


class TestCodeSandbox:
    """Test high-level CodeSandbox interface."""

    def test_basic_execution(self):
        sandbox = CodeSandbox()
        try:
            result = sandbox.execute("print('hello from sandbox')")
            assert result.success
            assert "hello from sandbox" in result.stdout
        finally:
            sandbox.cleanup()

    def test_allowed_imports(self):
        sandbox = create_sandbox(allowed_imports=["statistics"])
        try:
            result = sandbox.execute("import statistics; __result__ = statistics.mean([1,2,3,4,5])")
            assert result.success
            assert result.return_value == 3.0
        finally:
            sandbox.cleanup()

    def test_add_allowed_import(self):
        sandbox = CodeSandbox()
        sandbox.add_allowed_import("fractions")
        try:
            result = sandbox.execute("from fractions import Fraction; __result__ = str(Fraction(1, 3))")
            assert result.success
            assert result.return_value == "1/3"
        finally:
            sandbox.cleanup()

    def test_convenience_function(self):
        result = execute_python("__result__ = 2 + 2")
        assert result.success
        assert result.return_value == 4

    @pytest.mark.asyncio
    async def test_async_execution(self):
        sandbox = CodeSandbox()
        try:
            result = await sandbox.execute_async("__result__ = 'async works'")
            assert result.success
            assert result.return_value == "async works"
        finally:
            sandbox.cleanup()

    @pytest.mark.asyncio
    async def test_async_convenience(self):
        result = await execute_python_async("__result__ = 'async convenience'")
        assert result.success
        assert result.return_value == "async convenience"


class TestSandboxSecurity:
    """Test security boundaries."""

    def test_no_network_access(self):
        """Verify network is blocked by default."""
        result = execute_python("""
import socket
s = socket.socket()
s.connect(('8.8.8.8', 53))
__result__ = 'connected'
""")
        assert not result.success
        assert "blocked" in result.error.lower() or "permission" in result.error.lower()

    def test_no_filesystem_outside_sandbox(self):
        """Verify cannot access files outside sandbox."""
        result = execute_python("""
with open('/etc/passwd', 'r') as f:
    __result__ = f.read()
""")
        assert not result.success

    def test_no_subprocess(self):
        """Verify subprocess is blocked."""
        result = execute_python("""
import subprocess
subprocess.run(['ls'])
__result__ = 'ran'
""")
        assert not result.success

    def test_cpu_limit_enforced(self):
        """Verify CPU time limit works."""
        limits = ResourceLimits(cpu_time_seconds=1.0, wall_time_seconds=5.0)
        sandbox = CodeSandbox(limits=limits)
        try:
            result = sandbox.execute("""
# Busy loop
i = 0
while True:
    i += 1
""")
            # Should be killed by CPU limit
            assert not result.success or result.exit_code != 0
        finally:
            sandbox.cleanup()


class TestIntegration:
    """Integration tests with realistic use cases."""

    def test_data_processing(self):
        """Test data processing workflow."""
        code = """
import json
import statistics
from datetime import datetime

data = [{"value": i, "time": str(datetime.now())} for i in range(100)]
values = [d["value"] for d in data]

__result__ = {
    "count": len(values),
    "mean": statistics.mean(values),
    "stdev": statistics.stdev(values),
    "min": min(values),
    "max": max(values),
}
"""
        result = execute_python(code)
        assert result.success
        assert result.return_value["count"] == 100
        assert result.return_value["mean"] == 49.5

    def test_json_processing(self):
        """Test JSON processing."""
        code = """
import json

input_data = '{"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}'
data = json.loads(input_data)
adults = [u for u in data["users"] if u["age"] >= 18]
__result__ = {"adults": len(adults), "names": [u["name"] for u in adults]}
"""
        result = execute_python(code)
        assert result.success
        assert result.return_value["adults"] == 2

    def test_artifact_generation(self):
        """Test generating files as artifacts."""
        code = """
import json
import csv
from io import StringIO

# Generate CSV
output = StringIO()
writer = csv.writer(output)
writer.writerow(["name", "value"])
for i in range(10):
    writer.writerow([f"item_{i}", i * 2])

with open("report.csv", "w") as f:
    f.write(output.getvalue())

# Generate JSON summary
summary = {"rows": 10, "sum": sum(i * 2 for i in range(10))}
with open("summary.json", "w") as f:
    json.dump(summary, f)

__result__ = "files created"
"""
        result = execute_python(code)
        assert result.success
        assert "report.csv" in result.artifacts
        assert "summary.json" in result.artifacts
        assert b"name,value" in result.artifacts["report.csv"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])