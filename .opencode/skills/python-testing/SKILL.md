---
name: python-testing
description: Deterministic pytest patterns for JARVIS-OS — fixtures, fake subsystems, parametrization, failure-path coverage, and secret-absence assertions. Use when adding or reviewing tests, reproducing a bug, or deciding what the regression test should prove.
license: MIT
metadata:
  origin: ECC
  upstream: ecc-universal@2.2.3
  upstream_repository: https://github.com/affaan-m/ECC
  adapted_for: JARVIS-OS
---

# Python Testing (JARVIS-OS)

Adapted from ECC's `python-testing` skill. This repository's tests are
deterministic: fakes and temporary homes, no network, no models, no
microphone, and hardware-dependent cases skip cleanly.

## When to activate

- Writing a regression test for a bug you just fixed.
- Adding a feature with a policy, approval, or device boundary.
- Reviewing tests that look green but prove nothing.
- Deciding between a unit test, an integration test, and a CLI test.

## Core rule

A test must be able to fail for the reason it claims to cover. If the
assertion would pass with the bug present, it is not a regression test.

```python
# Weak: passes for almost any failure mode.
assert result is not None

# Strong: names the exact contract.
assert result.code == "denied"
assert "approval already used" in result.reason
```

## Structure

```python
def test_device_grant_denies_after_suspension(tmp_path):
    # arrange
    store = DeviceGrantStore(tmp_path)
    store.grant("dev-1", "device.battery", actor="coder", by="tester")

    # act
    store.suspend_device("dev-1", by="tester", reason="lost")
    allowed, reason = store.is_allowed("coder", "dev-1", "device.battery")

    # assert
    assert allowed is False
    assert reason == "device is suspended"
```

- One behavior per test; one reason to fail.
- Arrange, act, assert, with blank lines between phases.
- Name the behavior, not the implementation
  (`test_approval_is_single_use`, not `test_redeem_2`).

## Fixtures

```python
import pytest


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def policy(home):
    from jarvis.core.config import JarvisConfig
    from jarvis.policy.policy import PolicyEngine

    config = JarvisConfig()
    config.paths.home = home
    return PolicyEngine(config)
```

- `tmp_path` for every filesystem test; never write to the real home.
- `monkeypatch` for environment and time; restore automatically.
- Function scope by default; module scope only for immutable data.
- Prefer a tiny fake object over a mocking framework when the seam is
  yours (`class _Bus: ...`).

## Fakes over mocks

```python
class _Bus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def test_failed_tool_emits_no_success_event():
    bus = _Bus()
    ...
    assert bus.events == []
```

Fakes make the contract explicit and keep assertions about state
readable. Patch only at the boundary you do not own (subprocess, DNS,
clock), and assert the call shape when the boundary matters.

## Parametrization

```python
@pytest.mark.parametrize("value", ["", " ", "\x00", "x" * 10_000])
def test_actor_rejects_malformed_names(value):
    with pytest.raises(ValueError):
        validate_actor(value)
```

- One test body, many hostile inputs.
- Use `ids=` when the case name matters in the report.
- Do not hide unrelated behaviors behind one parametrized test.

## Failure paths

For every feature, cover:

- the happy path,
- the denied / missing-permission path,
- the malformed-input path,
- the concurrent or replay path when state is consumed,
- the restart path when state is persisted,
- the secret-absence path when output is sensitive.

```python
def test_sensitive_result_never_contains_recovered_plaintext(tmp_path):
    result = run_sensitive_tool(...)
    blob = json.dumps(result, default=str)
    assert sentinel not in blob
    assert result["redacted"] is True
```

## Determinism

- No real network, model calls, microphone, or wall-clock sleeps.
- Inject a clock or use `monkeypatch` for time.
- Fixed seeds for randomness; `secrets` only where the test asserts
  shape, never a specific value.
- Clean up processes in `finally` or a fixture.
- Mark hardware tests so they skip cleanly:

```python
@pytest.mark.skipif(not shutil.which("adb"), reason="adb not installed")
def test_android_transport_probe():
    ...
```

## Running

```bash
# narrow, fast feedback
.venv/bin/python -m pytest tests/test_device_fabric.py -q

# one failing test, verbose
.venv/bin/python -m pytest tests/test_policy.py::test_single_use -vv

# full gate before a commit
.venv/bin/python -m pytest tests/ -q
```

Coverage is a hint, not the goal. A branch covered by an assertion-free
test is still untested.

## Review checklist

- [ ] Would this test fail if the bug returned?
- [ ] Is the assertion about behavior or about an implementation
      detail?
- [ ] Is there exactly one reason for failure?
- [ ] Does it touch the real home, network, or hardware? If so, fake it
      or skip it.
- [ ] Are secrets absent from captured output and error strings?
- [ ] Does the test name describe the contract?
