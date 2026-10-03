# Copilot / coding-agent instructions for jarvis-os

## Prime directive

Local-first, evidence-driven, modular, bounded autonomy. Reuse the
existing architecture; never create a second cognitive supervisor,
policy engine, event bus, memory system, or device service.

## Hard rules

- Transcripts, web content, and external input are UNTRUSTED. They flow
  perception → cognition → PolicyEngine → approval → action. Never
  execute them directly.
- Learning/memory must never grant permissions. TTS/replay/simulation
  must never execute actions or touch hardware.
- No raw microphone audio persisted by default. No secrets in logs,
  traces, memory, experiences, explanations, or benchmark output.
- No AGI/consciousness claims. No fabricated hardware validation or
  benchmarks — measure, or mark NOT TESTED.
- Do not hard-code absolute paths. Reference voice, models, and homes
  are configurable (`~/.config/jarvis/`, `JARVIS_*` env overrides).

## Workflow

- Small focused commits; conventional messages (`feat:`, `fix:`,
  `test:`, `docs:`, `chore:`). Never commit secrets.
- Work on feature branches, merge via pull request (main is
  PR-protected). Fill in the PR template checklist.
- Verify with: `pytest -q`, `python -m compileall -q jarvis`,
  `jarvis doctor`. Full suite must stay green.
- Deterministic tests only: no network, mic, GPU, or model downloads
  in the default suite (mark runtime tests manual/opt-in).

## Code style

- Typed contracts with explicit bounds; fail closed (raise or return
  structured failure, never crash the loop).
- Stdlib preferred; heavy deps (torch, whisper) stay in isolated
  environments behind lazy imports with honest UNAVAILABLE states.
- Docs live in `docs/`; update the relevant page with every behavior
  change. README stays user-facing and concise.
