# Contributing to JARVIS-OS

Thanks for contributing.

JARVIS-OS is an evolving systems project. Small, well-tested changes are preferred over large rewrites.

## Before changing code

1. Read the relevant subsystem.
2. Search for existing interfaces and callers.
3. Read the existing tests.
4. Identify compatibility constraints.
5. Keep the change focused.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run the test suite:

```bash
pytest tests/ -q
```

For system-level changes, also run:

```bash
jarvis doctor
jarvis status
jarvis benchmark
```

## Engineering principles

- Prefer standard-library solutions when practical.
- Do not rewrite stable subsystems without a strong reason.
- Preserve existing public behavior unless the change explicitly requires it.
- Add regression tests for bugs.
- Keep expensive operations out of the normal cognitive fast path.
- Preserve provenance and uncertainty.
- Route privileged actions through the existing policy/security layer.
- Do not treat hypotheses or predictions as facts.
- Keep failures observable and isolated.

## Pull requests

A useful PR should explain:

- what changed
- why it changed
- which files/subsystems are affected
- compatibility considerations
- tests added or updated
- verification performed
- known limitations

Keep commits focused and descriptive.

## Commit style

Prefer:

```text
area: concise description
```

Examples:

```text
memory: preserve provenance during correction
world: add temporal state queries
agents: add bounded specialist orchestration
security: harden tool approval gate
docs: reorganize architecture guide
```

## Reporting bugs

Include:

- expected behavior
- actual behavior
- reproduction steps
- relevant logs/errors
- environment information
- whether the problem is deterministic

Do not include secrets, API keys, private credentials, or sensitive personal data.

## Scope

By contributing, you agree that your contribution should fit the project's existing architecture, safety boundaries, and verification-first development style.
