# Contributing to JARVIS-OS

Thanks for helping build JARVIS-OS.

## Before you start

- Read the README and relevant documentation.
- Search existing issues and pull requests before opening a new one.
- For security vulnerabilities, do not open a public issue; follow SECURITY.md.

## Development principles

JARVIS-OS is designed around local-first operation, evidence and provenance,
bounded autonomy, least privilege, explicit consent, deterministic tests, and
small reviewable changes.

Do not add unrestricted shell execution, arbitrary code evaluation, hidden
persistence, credential exfiltration, or bypasses around the policy/security
layer.

Four rules decide most review outcomes:

1. **Reuse, never duplicate.** A second scheduler, bus, policy engine or
   memory store is a bug. Extend the existing one.
2. **Bound everything.** Payloads, buffers, retries, timeouts, retention and
   in-memory collections all need an explicit limit. Long-lived processes
   must not grow without bound.
3. **Fail closed.** Corrupt state is quarantined, never parsed into
   authority. An unreadable emergency stop blocks actions; it does not
   permit them.
4. **No secrets in logs, traces, memory or snapshots.** Scrub at the
   boundary, and assert absence in a test.

## Workflow

- One branch per milestone: `feature/<name>-<n>`.
- Tests first where practical — a bug fix starts with a test that fails.
- `pytest tests/ -q` must be green before a pull request. The suite is
  deterministic: no network, no models, no microphone, no hardware.
- Hardware-dependent tests skip cleanly rather than fail.
- Squash-merge, with a clear commit message.

```bash
git checkout -b feature/my-change-1
python3 -m pytest tests/ -q
```

## CLI is an API

Exit codes are part of the contract. `jarvis doctor`, `jarvis service
doctor` and `jarvis task doctor` exit non-zero on failure, and so must any
command that prints a failure. If a command reports an error, it must not
exit 0 — scripts gate on that.

## Adding a model provider

Model providers are configuration, not code. A new provider usually needs
no code at all:

```bash
jarvis models add myprovider --type openai --base-url https://example/v1 \
  --model reasoning=my-model-id --api-key-secret my_provider_key
cat key.txt | jarvis models key myprovider
jarvis models use reasoning myprovider --allow-remote
```

Only add a new backend *type* in `jarvis/models/backends.py` when the
provider does not speak Ollama's protocol or the OpenAI-compatible one.
Keys always live in the vault, never in `config.json`, never in argv.

## Pull requests

A good pull request should explain what changed and why, identify security or
privacy implications, include tests where practical, update documentation when
public behavior changes, and avoid unrelated refactors.

Use clear commits such as `feat: add bounded device capability` or
`fix: reject expired device command`.

## AI-generated contributions

Contributions written with AI assistance are welcome, and are held to the
same standard as any other: the author has read the code, understands it,
and stands behind it. Say so in the pull request if a tool generated a
substantial part of the change — this is a transparency request, not a
restriction. AI-generated code that has not been reviewed is not
contributable.

## Review

Changes are reviewed for correctness, security, maintainability, testing, and
architectural compatibility. Passing CI does not replace human review.

Contributions are provided under the project's Apache License 2.0.
