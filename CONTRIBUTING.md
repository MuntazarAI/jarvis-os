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

## Pull requests

A good pull request should explain what changed and why, identify security or
privacy implications, include tests where practical, update documentation when
public behavior changes, and avoid unrelated refactors.

Use clear commits such as `feat: add bounded device capability` or
`fix: reject expired device command`.

## Review

Changes are reviewed for correctness, security, maintainability, testing, and
architectural compatibility. Passing CI does not replace human review.

Contributions are provided under the project's Apache License 2.0.
