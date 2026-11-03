---
name: python-patterns
description: Pythonic idioms, PEP 8, type hints, dataclasses, and stdlib-first structure for JARVIS-OS. Use when writing or reviewing Python code, choosing data structures, or deciding whether a dependency is justified.
license: MIT
metadata:
  origin: ECC
  upstream: ecc-universal@2.2.3
  upstream_repository: https://github.com/affaan-m/ECC
  adapted_for: JARVIS-OS
---

# Python Patterns (JARVIS-OS)

Adapted from ECC's `python-patterns` skill. This repository is
stdlib-first, CLI-first, and local-first; the examples below prefer the
standard library and explicit failure over clever abstraction.

## When to activate

- Writing a new module, dataclass, tool, or CLI handler.
- Reviewing Python for readability, typing, or structure.
- Deciding whether a third-party dependency is worth adding.
- Refactoring code that has grown implicit or stateful.

## Core principles

1. **Readability wins.** Obvious code beats clever code. A short
   docstring that states the contract is part of the code.
2. **Explicit over implicit.** Pass dependencies in; do not reach for
   global state or hidden I/O inside a constructor.
3. **Stdlib first.** `pathlib`, `json`, `dataclasses`, `argparse`,
   `subprocess`, `tempfile`, `hashlib`, and `secrets` cover most needs.
   A dependency must justify itself with capability, not convenience.
4. **Fail closed.** Raise on illegal state; return an explicit `None`
   or `unknown` when the answer genuinely is unknown. Never guess.
5. **Bound everything.** Sizes, depths, retries, timeouts, and
   retention are part of the interface.

## Type hints

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Device:
    device_id: str
    name: str
    capabilities: frozenset[str] = field(default_factory=frozenset)


def load_device(path: Path) -> Device | None:
    """Return None when the record is absent; raise on corrupt state."""
```

- Use built-in generics (`list[str]`, `dict[str, Any]`) on modern
  Python.
- Prefer `X | None` over `Optional[X]`.
- Use `Protocol` for duck-typed seams instead of inheritance for its
  own sake.
- Type the boundary, not every local variable.

## Dataclasses and value objects

```python
@dataclass(frozen=True)
class Budget:
    max_calls: int = 15
    max_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls must be positive")
```

- Frozen dataclasses for values that cross a boundary.
- Validate invariants in `__post_init__`; never accept an illegal
  state and repair it silently.
- Avoid mutable default arguments; use `field(default_factory=...)`.

## Error handling

```python
try:
    record = json.loads(text)
except json.JSONDecodeError as exc:
    raise StateError(f"corrupt store: {exc}") from exc
```

- Catch the narrowest exception that you can actually handle.
- Chain with `raise ... from exc` so the cause survives.
- Never use a bare `except:` or swallow an exception to keep a loop
  alive.
- Error strings are part of the public surface: keep them useful and
  free of secrets.

## Resources and paths

```python
from pathlib import Path

path = Path(home) / "state.json"
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(".tmp")
tmp.write_text(payload, encoding="utf-8")
tmp.replace(path)  # atomic on the same filesystem
```

- Use `pathlib`, explicit encodings, and context managers.
- Atomic replace for state that must survive a crash.
- Resolve and validate paths before comparing them.

## Comprehensions and generators

```python
active = [device for device in devices if device.can_execute()]

def rows(items: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for item in items:
        yield {"id": item["id"], "state": item["state"]}
```

- Comprehensions for one simple transform/filter; a named function
  when the condition needs a comment.
- Generators for large or streamed data.
- Do not materialize an unbounded list just to iterate once.

## Protocols and seams

```python
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...


def stamp(clock: Clock) -> float:
    return clock.now()
```

- A small protocol is a test seam without a mocking framework.
- Inject the clock, filesystem root, or policy object; do not patch
  module globals in production code.

## CLI and exit codes

- `argparse` subcommands live in `jarvis/cli.py`.
- Exit codes are API: `0` success, non-zero failure or unknown.
- Print machine-readable JSON behind `--json`; keep human output
  stable and short.
- A CLI handler must close resources and return an integer code.

## Anti-patterns

- A second scheduler, bus, policy engine, memory store, or registry.
- God objects that read the environment, parse input, and execute.
- `assert` for runtime validation (it disappears under `-O`).
- Mutable module-level state without a lock or an owner.
- Catching `Exception` to return `{"ok": True}`.
- Magic numbers for timeouts, limits, or retry counts.

## Review checklist

- [ ] Does it reuse an existing subsystem instead of adding a second?
- [ ] Are inputs bounded and validated at the boundary?
- [ ] Does failure close, rather than widen, authority?
- [ ] Are secrets absent from output, logs, and errors?
- [ ] Is there a deterministic test for the new behavior?
